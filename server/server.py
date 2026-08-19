import json
import os
import asyncio
import hashlib
import secrets

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import psycopg2
import uvicorn


app = FastAPI()

HEARTBEAT_INTERVAL = 5


# ============================================================
# PostgreSQL
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():

    return psycopg2.connect(
        DATABASE_URL
    )


# ============================================================
# Створення таблиці
# ============================================================

def init_database():

    connection = get_db()

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (

            id SERIAL PRIMARY KEY,

            nickname VARCHAR(15) UNIQUE NOT NULL,

            password_hash TEXT NOT NULL,

            money INTEGER NOT NULL DEFAULT 100,

            x INTEGER NOT NULL DEFAULT 640,

            y INTEGER NOT NULL DEFAULT 360

        );
    """)

    connection.commit()

    cursor.close()
    connection.close()

    print("Database initialized")


# ============================================================
# Пароль
# ============================================================

def hash_password(password):

    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100_000
    )

    return (
        salt.hex()
        + ":"
        + password_hash.hex()
    )


def verify_password(password, stored_hash):

    try:

        salt_hex, hash_hex = stored_hash.split(":")

        salt = bytes.fromhex(
            salt_hex
        )

        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            100_000
        )

        return secrets.compare_digest(
            password_hash.hex(),
            hash_hex
        )

    except Exception:

        return False


# ============================================================
# Створення акаунта
# ============================================================

def create_account(
    nickname,
    password
):

    connection = get_db()

    cursor = connection.cursor()

    try:

        password_hash = hash_password(
            password
        )

        cursor.execute(
            """
            INSERT INTO players
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

        player_id = cursor.fetchone()[0]

        connection.commit()

        return {
            "success": True,
            "id": player_id,
            "money": 100,
            "x": 640,
            "y": 360
        }

    except psycopg2.errors.UniqueViolation:

        connection.rollback()

        return {
            "success": False,
            "error": "nickname_taken"
        }

    except Exception as e:

        connection.rollback()

        print(
            "Create account error:",
            e
        )

        return {
            "success": False,
            "error": "database_error"
        }

    finally:

        cursor.close()
        connection.close()


# ============================================================
# Вхід
# ============================================================

def login_account(
    nickname,
    password
):

    connection = get_db()

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                password_hash,
                money,
                x,
                y
            FROM players
            WHERE nickname = %s
            """,
            (nickname,)
        )

        row = cursor.fetchone()

        if row is None:

            return {
                "success": False,
                "error": "invalid_login"
            }

        player_id = row[0]
        stored_hash = row[1]
        money = row[2]
        x = row[3]
        y = row[4]

        if not verify_password(
            password,
            stored_hash
        ):

            return {
                "success": False,
                "error": "invalid_login"
            }

        return {
            "success": True,
            "id": player_id,
            "money": money,
            "x": x,
            "y": y
        }

    except Exception as e:

        print(
            "Login error:",
            e
        )

        return {
            "success": False,
            "error": "database_error"
        }

    finally:

        cursor.close()
        connection.close()


# ============================================================
# Збереження даних гравця
# ============================================================

def save_player(
    player_id,
    money,
    x,
    y
):

    connection = get_db()

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            UPDATE players
            SET
                money = %s,
                x = %s,
                y = %s
            WHERE id = %s
            """,
            (
                money,
                x,
                y,
                player_id
            )
        )

        connection.commit()

    except Exception as e:

        connection.rollback()

        print(
            "Save player error:",
            e
        )

    finally:

        cursor.close()
        connection.close()


# ============================================================
# Онлайн-гравці
# ============================================================

players = {}


# ============================================================
# Отримати найменший вільний WebSocket ID
# ============================================================

def get_player_id():

    player_id = 1

    while player_id in players:

        player_id += 1

    return player_id


# ============================================================
# Відправити позицію іншим
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

            if player_id in players:

                del players[player_id]

                print(
                    f"Player {player_id} heartbeat disconnected"
                )

                await broadcast_player_left(
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

    connection_id = None

    account_id = None

    heartbeat_task = None

    try:

        # ====================================================
        # Авторизація
        # ====================================================

        message = await websocket.receive_text()

        data = json.loads(message)

        message_type = data.get("t")


        # ====================================================
        # REGISTER
        # ====================================================

        if message_type == "register":

            nickname = str(
                data.get("n", "")
            ).strip()

            password = str(
                data.get("p", "")
            )


            if not nickname:

                await websocket.send_text(
                    json.dumps({
                        "t": "auth_error",
                        "e": "empty_nickname"
                    })
                )

                await websocket.close()

                return


            if len(nickname) > 15:

                await websocket.send_text(
                    json.dumps({
                        "t": "auth_error",
                        "e": "nickname_too_long"
                    })
                )

                await websocket.close()

                return


            if not password:

                await websocket.send_text(
                    json.dumps({
                        "t": "auth_error",
                        "e": "empty_password"
                    })
                )

                await websocket.close()

                return


            result = create_account(
                nickname,
                password
            )


            if not result["success"]:

                await websocket.send_text(
                    json.dumps({
                        "t": "auth_error",
                        "e": result["error"]
                    })
                )

                await websocket.close()

                return


            account_id = result["id"]

            money = result["money"]

            x = result["x"]

            y = result["y"]


        # ====================================================
        # LOGIN
        # ====================================================

        elif message_type == "login":

            nickname = str(
                data.get("n", "")
            ).strip()

            password = str(
                data.get("p", "")
            )


            result = login_account(
                nickname,
                password
            )


            if not result["success"]:

                await websocket.send_text(
                    json.dumps({
                        "t": "auth_error",
                        "e": result["error"]
                    })
                )

                await websocket.close()

                return


            account_id = result["id"]

            money = result["money"]

            x = result["x"]

            y = result["y"]


        else:

            await websocket.close()

            return


        # ====================================================
        # Отримуємо тимчасовий WebSocket ID
        # ====================================================

        connection_id = get_player_id()


        # ====================================================
        # Створюємо онлайн-гравця
        # ====================================================

        players[connection_id] = {

            "websocket": websocket,

            "account_id": account_id,

            "nickname": nickname,

            "money": money,

            "x": x,

            "y": y
        }


        print(
            f"Player {connection_id} "
            f"(account {account_id}) "
            f"connected as {nickname}"
        )


        # ====================================================
        # Відправляємо дані власнику
        # ====================================================

        await websocket.send_text(

            json.dumps(
                {
                    "t": "w",
                    "i": connection_id,
                    "a": account_id,
                    "n": nickname,
                    "m": money,
                    "x": x,
                    "y": y
                },
                separators=(",", ":")
            )
        )


        # ====================================================
        # Існуючі гравці
        # ====================================================

        existing_players = []


        for other_id, player in players.items():

            if other_id == connection_id:

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
        # Повідомляємо інших
        # ====================================================

        await broadcast_player_joined(
            connection_id,
            nickname,
            x,
            y
        )


        # ====================================================
        # Heartbeat
        # ====================================================

        heartbeat_task = asyncio.create_task(
            heartbeat(
                connection_id,
                websocket
            )
        )


        # ====================================================
        # Основний цикл
        # ====================================================

        while True:

            message = await websocket.receive_text()

            data = json.loads(message)


            # =================================================
            # Heartbeat response
            # =================================================

            if data.get("t") == "a":

                continue


            # =================================================
            # Позиція
            # =================================================

            if data.get("t") == "p":

                x = int(
                    data.get("x", 0)
                )

                y = int(
                    data.get("y", 0)
                )


                if connection_id not in players:

                    break


                players[
                    connection_id
                ]["x"] = x

                players[
                    connection_id
                ]["y"] = y


                await broadcast_position(
                    connection_id,
                    x,
                    y
                )


    except WebSocketDisconnect:

        print(
            f"Player {connection_id} disconnected"
        )


    except Exception as e:

        print(
            f"Player {connection_id} error:",
            e
        )


    finally:

        if heartbeat_task:

            heartbeat_task.cancel()


        if connection_id is not None:

            if connection_id in players:

                player = players[
                    connection_id
                ]


                # ============================================
                # Зберігаємо дані в БД
                # ============================================

                save_player(

                    player["account_id"],

                    player["money"],

                    player["x"],

                    player["y"]
                )


                # ============================================
                # Видаляємо онлайн-гравця
                # ============================================

                del players[
                    connection_id
                ]


                print(
                    f"Player {connection_id} removed"
                )


                await broadcast_player_left(
                    connection_id
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
# Запуск
# ============================================================

if __name__ == "__main__":

    init_database()


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