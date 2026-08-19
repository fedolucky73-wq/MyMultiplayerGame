import json
import os
import asyncio
import math

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


app = FastAPI()

HEARTBEAT_INTERVAL = 5

DATABASE_URL = os.environ.get("DATABASE_URL")


# ============================================================
# PostgreSQL
# ============================================================

def get_db_connection():

    if not DATABASE_URL:
        raise Exception("DATABASE_URL is not set")

    return psycopg2.connect(
        DATABASE_URL
    )


def init_database():

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (

                id SERIAL PRIMARY KEY,

                nickname VARCHAR(15) UNIQUE NOT NULL,

                password_hash TEXT NOT NULL,

                money INTEGER NOT NULL DEFAULT 100,

                x INTEGER NOT NULL DEFAULT 640,

                y INTEGER NOT NULL DEFAULT 360
            )
        """)

        connection.commit()

        cursor.close()

        print("Database initialized")

    finally:

        connection.close()


# ============================================================
# Гравці онлайн
# ============================================================

players = {}


# ============================================================
# Отримати найменший вільний ID
# ============================================================

def get_player_id():

    player_id = 1

    while player_id in players:

        player_id += 1

    return player_id


# ============================================================
# Монети (кинуті гроші)
#
# Зберігаються тільки в пам'яті — це відповідає тому, як
# клієнт (main.py) працює з монетами: coins = {} з тим самим
# форматом {id: {"x":.., "y":..}}.
# ============================================================

coins = {}

next_coin_id = 1

COIN_DROP_COST = 5

# На скільки пікселів монета відлітає від гравця
# у напрямку курсора (dx, dy з клієнта)
COIN_DROP_DISTANCE = 60

# Максимальна дистанція, з якої сервер приймає "collect".
# Трохи більша за клієнтську COIN_PICKUP_DISTANCE
# (PLAYER_SIZE/2 + COIN_RADIUS + 4 = 36), щоб не відхиляти
# легітимні підбори через затримку мережі (лаг).
COIN_PICKUP_DISTANCE = 60


def get_coin_id():

    global next_coin_id

    coin_id = next_coin_id

    next_coin_id += 1

    return coin_id


# ============================================================
# Реєстрація
# ============================================================

def register_user(nickname, password):

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # Перевіряємо, чи існує нік
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE nickname = %s
            """,
            (nickname,)
        )

        existing = cursor.fetchone()

        if existing:

            return False, "Nickname already exists"


        # ----------------------------------------------------
        # Тимчасово використовуємо SHA-256.
        #
        # Пізніше можемо замінити на bcrypt/argon2.
        # ----------------------------------------------------

        import hashlib

        password_hash = hashlib.sha256(
            password.encode("utf-8")
        ).hexdigest()


        cursor.execute(
            """
            INSERT INTO users
            (
                nickname,
                password_hash,
                money,
                x,
                y
            )

            VALUES
            (
                %s,
                %s,
                100,
                640,
                360
            )

            RETURNING id
            """,

            (
                nickname,
                password_hash
            )
        )


        user_id = cursor.fetchone()[0]

        connection.commit()

        cursor.close()


        return True, user_id


    except Exception as e:

        connection.rollback()

        print(
            "Registration error:",
            e
        )

        return False, "Database error"


    finally:

        connection.close()


# ============================================================
# Вхід
# ============================================================

def login_user(nickname, password):

    connection = get_db_connection()

    try:

        cursor = connection.cursor(
            cursor_factory=RealDictCursor
        )


        cursor.execute(
            """
            SELECT
                id,
                nickname,
                password_hash,
                money,
                x,
                y

            FROM users

            WHERE nickname = %s
            """,

            (nickname,)
        )


        user = cursor.fetchone()


        if not user:

            return None


        import hashlib

        password_hash = hashlib.sha256(
            password.encode("utf-8")
        ).hexdigest()


        if password_hash != user["password_hash"]:

            return None


        return user


    finally:

        connection.close()


# ============================================================
# Зберегти дані гравця
# ============================================================

def save_user_position(
    account_id,
    x,
    y,
    money
):

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users

            SET
                x = %s,
                y = %s,
                money = %s

            WHERE id = %s
            """,

            (
                x,
                y,
                money,
                account_id
            )
        )

        connection.commit()

        cursor.close()

    finally:

        connection.close()


# ============================================================
# Повідомлення позиції
# ============================================================

async def broadcast_position(
    sender_id,
    x,
    y
):

    message = json.dumps(
        {
            "t": "p",
            "i": sender_id,
            "x": x,
            "y": y
        },
        separators=(",", ":")
    )


    disconnected = []


    for player_id, player in list(
        players.items()
    ):

        if player_id == sender_id:
            continue


        try:

            await player[
                "websocket"
            ].send_text(message)


        except Exception:

            disconnected.append(
                player_id
            )


    for player_id in disconnected:

        if player_id in players:

            del players[player_id]


# ============================================================
# Видалення гравця
# ============================================================

async def remove_player(player_id):

    if player_id not in players:

        return


    player = players[player_id]


    try:

        save_user_position(
            player["account_id"],
            player["x"],
            player["y"],
            player["money"]
        )

    except Exception as e:

        print(
            "Could not save player:",
            e
        )


    del players[player_id]


    print(
        f"Player {player_id} removed"
    )


    await broadcast_player_left(
        player_id
    )

# ============================================================
# Повідомити про вихід
# ============================================================

async def broadcast_player_left(
    player_id
):

    message = json.dumps(
        {
            "t": "l",
            "i": player_id
        },
        separators=(",", ":")
    )


    disconnected = []


    for other_id, player in list(
        players.items()
    ):

        if other_id == player_id:
            continue


        try:

            await player[
                "websocket"
            ].send_text(message)


        except Exception:

            disconnected.append(
                other_id
            )


    for other_id in disconnected:

        if other_id in players:

            del players[other_id]


# ============================================================
# Повідомити про нового гравця
# ============================================================

async def broadcast_player_joined(
    player_id,
    nickname,
    x,
    y
):

    message = json.dumps(
        {
            "t": "j",
            "i": player_id,
            "n": nickname,
            "x": x,
            "y": y
        },
        separators=(",", ":")
    )


    disconnected = []


    for other_id, player in list(
        players.items()
    ):

        if other_id == player_id:
            continue


        try:

            await player[
                "websocket"
            ].send_text(message)


        except Exception:

            disconnected.append(
                other_id
            )


    for other_id in disconnected:

        if other_id in players:

            del players[other_id]


# ============================================================
# З'явилась нова монета (усім гравцям)
# ============================================================

async def broadcast_new_coin(
    coin_id,
    x,
    y
):

    message = json.dumps(
        {
            "t": "c",
            "i": coin_id,
            "x": x,
            "y": y
        },
        separators=(",", ":")
    )


    disconnected = []


    for player_id, player in list(
        players.items()
    ):

        try:

            await player[
                "websocket"
            ].send_text(message)


        except Exception:

            disconnected.append(
                player_id
            )


    for player_id in disconnected:

        if player_id in players:

            del players[player_id]


# ============================================================
# Монету підібрали — прибрати в усіх
# ============================================================

async def broadcast_coin_removed(
    coin_id
):

    message = json.dumps(
        {
            "t": "cr",
            "i": coin_id
        },
        separators=(",", ":")
    )


    disconnected = []


    for player_id, player in list(
        players.items()
    ):

        try:

            await player[
                "websocket"
            ].send_text(message)


        except Exception:

            disconnected.append(
                player_id
            )


    for player_id in disconnected:

        if player_id in players:

            del players[player_id]


# ============================================================
# Heartbeat
# ============================================================

async def heartbeat(
    player_id,
    websocket
):

    while True:

        await asyncio.sleep(
            HEARTBEAT_INTERVAL
        )


        if player_id not in players:

            return


        try:

            await websocket.send_text(
                '{"t":"h"}'
            )


        except Exception:

            print(
                f"Player {player_id} heartbeat disconnected"
            )

            await remove_player(
                player_id
            )

            return


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()


    player_id = None

    account_id = None

    heartbeat_task = None


    try:

        # ====================================================
        # Чекаємо LOGIN / REGISTER
        # ====================================================

        message = await websocket.receive_text()

        data = json.loads(message)


        message_type = data.get("t")


        # ====================================================
        # REGISTER
        # ====================================================

        if message_type == "register":

            nickname = str(
                data.get(
                    "n",
                    ""
                )
            ).strip()[:15]


            password = str(
                data.get(
                    "p",
                    ""
                )
            )


            if not nickname:

                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "error",
                            "m": "Nickname is required"
                        },
                        separators=(",", ":")
                    )
                )

                await websocket.close()

                return


            if not password:

                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "error",
                            "m": "Password is required"
                        },
                        separators=(",", ":")
                    )
                )

                await websocket.close()

                return


            success, result = register_user(
                nickname,
                password
            )


            if not success:

                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "error",
                            "m": result
                        },
                        separators=(",", ":")
                    )
                )

                await websocket.close()

                return


            account_id = result


            await websocket.send_text(
                json.dumps(
                    {
                        "t": "registered",
                        "id": account_id
                    },
                    separators=(",", ":")
                )
            )


            await websocket.close()

            return


        # ====================================================
        # LOGIN
        # ====================================================

        if message_type != "login":

            await websocket.send_text(
                json.dumps(
                    {
                        "t": "error",
                        "m": "Login required"
                    },
                    separators=(",", ":")
                )
            )

            await websocket.close()

            return


        nickname = str(
            data.get(
                "n",
                ""
            )
        ).strip()[:15]


        password = str(
            data.get(
                "p",
                ""
            )
        )


        user = login_user(
            nickname,
            password
        )


        if not user:

            await websocket.send_text(
                json.dumps(
                    {
                        "t": "error",
                        "m": "Invalid nickname or password"
                    },
                    separators=(",", ":")
                )
            )

            await websocket.close()

            return


        account_id = user["id"]


        # ====================================================
        # Перевірка: чи акаунт уже онлайн
        # ====================================================

        for existing_player in players.values():

            if existing_player[
                "account_id"
            ] == account_id:

                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "error",
                            "m": "Account already online"
                        },
                        separators=(",", ":")
                    )
                )

                await websocket.close()

                return


        # ====================================================
        # Отримуємо ID сесії
        # ====================================================

        player_id = get_player_id()


        # ====================================================
        # Створюємо гравця
        # ====================================================

        players[player_id] = {

            "websocket": websocket,

            "account_id": account_id,

            "nickname": user["nickname"],

            "x": user["x"],

            "y": user["y"],

            "money": user["money"]
        }


        print(
            f"Player {player_id} logged in as {user['nickname']}"
        )


        # ====================================================
        # Відправляємо ID та дані
        # ====================================================

        await websocket.send_text(

            json.dumps(
                {
                    "t": "w",

                    "i": player_id,

                    "account_id": account_id,

                    "n": user["nickname"],

                    "money": user["money"],

                    "x": user["x"],

                    "y": user["y"]
                },

                separators=(",", ":")
            )
        )


        # ====================================================
        # Існуючі гравці
        # ====================================================

        existing_players = []


        for other_id, player in players.items():

            if other_id == player_id:

                continue


            existing_players.append(

                {
                    "i": other_id,

                    "n": player["nickname"],

                    "x": player["x"],

                    "y": player["y"]
                }
            )


        await websocket.send_text(

            json.dumps(
                {
                    "t": "s",
                    "p": existing_players
                },

                separators=(",", ":")
            )
        )


        # ====================================================
        # Активні монети (актуальний стан)
        # ====================================================

        active_coins = [

            {
                "i": coin_id,
                "x": coin["x"],
                "y": coin["y"]
            }

            for coin_id, coin in coins.items()
        ]


        await websocket.send_text(

            json.dumps(
                {
                    "t": "cs",
                    "c": active_coins
                },

                separators=(",", ":")
            )
        )


        # ====================================================
        # Повідомляємо інших
        # ====================================================

        await broadcast_player_joined(

            player_id,

            user["nickname"],

            user["x"],

            user["y"]
        )


        # ====================================================
        # Heartbeat
        # ====================================================

        heartbeat_task = asyncio.create_task(

            heartbeat(
                player_id,
                websocket
            )
        )


        # ====================================================
        # Основний цикл
        # ====================================================

        while True:

            message = await websocket.receive_text()

            data = json.loads(message)


            message_type = data.get("t")


            # =================================================
            # HEARTBEAT ACK
            # =================================================

            if message_type == "a":

                continue


            # =================================================
            # Позиція
            # =================================================

            if message_type == "p":

                try:

                    x = int(
                        data.get(
                            "x",
                            0
                        )
                    )

                    y = int(
                        data.get(
                            "y",
                            0
                        )
                    )

                except (TypeError, ValueError):

                    continue


                # ========================================================
                # Захист від неправильних координат
                # ========================================================

                x = max(
                    25,
                    min(
                        1255,
                        x
                    )
                )

                y = max(
                    25,
                    min(
                        695,
                        y
                    )
                )


                if player_id not in players:

                    break


                players[
                    player_id
                ]["x"] = x

                players[
                    player_id
                ]["y"] = y


                await broadcast_position(

                    player_id,

                    x,

                    y
                )

                continue


            # =================================================
            # Викинути гроші (5) у напрямку курсора
            # =================================================

            if message_type == "drop":

                if player_id not in players:
                    break


                try:

                    dx = float(
                        data.get("dx", 0)
                    )

                    dy = float(
                        data.get("dy", 0)
                    )

                except (TypeError, ValueError):

                    continue


                current_money = players[
                    player_id
                ]["money"]


                if current_money < COIN_DROP_COST:

                    await websocket.send_text(
                        json.dumps(
                            {
                                "t": "drop_error",
                                "m": "Not enough money"
                            },
                            separators=(",", ":")
                        )
                    )

                    continue


                # ========================================
                # Нормалізуємо напрямок
                # ========================================

                length = math.sqrt(
                    dx * dx + dy * dy
                )

                if length == 0:

                    norm_dx, norm_dy = 1.0, 0.0

                else:

                    norm_dx = dx / length
                    norm_dy = dy / length


                player_x = players[player_id]["x"]
                player_y = players[player_id]["y"]

                coin_x = int(
                    round(
                        player_x +
                        norm_dx * COIN_DROP_DISTANCE
                    )
                )

                coin_y = int(
                    round(
                        player_y +
                        norm_dy * COIN_DROP_DISTANCE
                    )
                )

                # Ті самі межі світу, що й для позиції гравця
                coin_x = max(25, min(1255, coin_x))
                coin_y = max(25, min(695, coin_y))


                # ========================================
                # Списуємо гроші та створюємо монету
                # ========================================

                players[player_id]["money"] = (
                    current_money - COIN_DROP_COST
                )

                coin_id = get_coin_id()

                coins[coin_id] = {
                    "x": coin_x,
                    "y": coin_y
                }


                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "money",
                            "money": players[
                                player_id
                            ]["money"]
                        },
                        separators=(",", ":")
                    )
                )

                await broadcast_new_coin(
                    coin_id,
                    coin_x,
                    coin_y
                )

                continue


            # =================================================
            # Гравець підібрав монету
            # =================================================

            if message_type == "collect":

                if player_id not in players:
                    break


                coin_id = data.get("i")

                coin = coins.get(coin_id)

                if coin is None:

                    # Монету вже підібрав хтось інший —
                    # просто ігноруємо
                    continue


                # ========================================
                # Захист від "телепортного" підбору:
                # перевіряємо реальну відстань гравця
                # до монети за координатами на сервері
                # ========================================

                player_x = players[player_id]["x"]
                player_y = players[player_id]["y"]

                distance = math.hypot(
                    player_x - coin["x"],
                    player_y - coin["y"]
                )

                if distance > COIN_PICKUP_DISTANCE:

                    continue


                # Прибираємо монету саме зараз,
                # щоб два гравці не забрали її одночасно

                del coins[coin_id]

                players[player_id]["money"] += (
                    COIN_DROP_COST
                )


                await broadcast_coin_removed(
                    coin_id
                )

                await websocket.send_text(
                    json.dumps(
                        {
                            "t": "money",
                            "money": players[
                                player_id
                            ]["money"]
                        },
                        separators=(",", ":")
                    )
                )

                continue


    except WebSocketDisconnect:

        print(
            f"Player {player_id} disconnected"
        )


    except Exception as e:

        print(
            f"Player {player_id} error:",
            e
        )


    finally:

        if heartbeat_task:

            heartbeat_task.cancel()


        if player_id is not None:

            await remove_player(
                player_id
            )


# ============================================================
# HTTP
# ============================================================

@app.get("/")
def home():

    return {

        "status": "online",

        "players": len(players)
    }


# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
async def startup():

    init_database()


# ============================================================
# Запуск
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )


    uvicorn.run(

        app,

        host="0.0.0.0",

        port=port
    )