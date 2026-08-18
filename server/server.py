import json
import os
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


app = FastAPI()
HEARTBEAT_INTERVAL = 5

# ============================================================
# Гравці
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
# Відправити позицію іншим гравцям
# ============================================================

async def broadcast_position(sender_id, x, y):

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

    for player_id, player in list(players.items()):

        # Не відправляємо самому собі
        if player_id == sender_id:
            continue

        try:

            await player["websocket"].send_text(message)

        except Exception:

            disconnected.append(player_id)


    # Прибираємо мертвих клієнтів
    for player_id in disconnected:

        if player_id in players:

            del players[player_id]


# ============================================================
# Повідомити інших про вихід
# ============================================================

async def broadcast_player_left(player_id):

    message = json.dumps(
        {
            "t": "l",
            "i": player_id
        },
        separators=(",", ":")
    )

    disconnected = []

    for other_id, player in list(players.items()):

        if other_id == player_id:
            continue

        try:

            await player["websocket"].send_text(message)

        except Exception:

            disconnected.append(other_id)


    for other_id in disconnected:

        if other_id in players:

            del players[other_id]


# ============================================================
# Повідомити інших про нового гравця
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

    for other_id, player in list(players.items()):

        if other_id == player_id:
            continue

        try:

            await player["websocket"].send_text(message)

        except Exception:

            disconnected.append(other_id)


    for other_id in disconnected:

        if other_id in players:

            del players[other_id]


async def heartbeat(player_id, websocket):

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
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    player_id = None
    heartbeat_task = None

    try:

        # ====================================================
        # Чекаємо реєстрацію
        # ====================================================

        message = await websocket.receive_text()

        data = json.loads(message)


        if data.get("t") != "r":

            await websocket.close()

            return


        nickname = str(
            data.get("n", "Player")
        )[:10]


        # ====================================================
        # Отримуємо найменший вільний ID
        # ====================================================

        player_id = get_player_id()


        # ====================================================
        # Створюємо гравця
        # ====================================================

        players[player_id] = {

            "websocket": websocket,

            "nickname": nickname,

            "x": 640,

            "y": 360
        }


        print(
            f"Player {player_id} connected as {nickname}"
        )


        # ====================================================
        # Відправляємо ID
        # ====================================================

        await websocket.send_text(

            json.dumps(
                {
                    "t": "w",
                    "i": player_id
                },
                separators=(",", ":")
            )
        )


        # ====================================================
        # Відправляємо новому гравцю
        # існуючих гравців
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
        # Повідомляємо інших про нового
        # ====================================================

        await broadcast_player_joined(
            player_id,
            nickname,
            640,
            360
        )

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


                # Перевіряємо, що гравець ще існує

                if player_id not in players:
                    break


                players[player_id]["x"] = x
                players[player_id]["y"] = y


                await broadcast_position(
                    player_id,
                    x,
                    y
                )


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

        # ====================================================
        # Видаляємо гравця
        # ====================================================

        if player_id is not None:

            if player_id in players:

                del players[player_id]

                print(
                    f"Player {player_id} removed"
                )


                # ============================================
                # Миттєво повідомляємо інших
                # ============================================

                await broadcast_player_left(
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