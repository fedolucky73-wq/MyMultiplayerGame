import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


app = FastAPI()


# ============================================================
# Гравці
# ============================================================

players = {}

# Наприклад:
#
# {
#     "Player1": {
#         "x": 640,
#         "y": 360,
#         "websocket": ...
#     }
# }


# ============================================================
# Отримати вільний номер
# ============================================================

def get_player_name():

    number = 1

    while f"Player{number}" in players:
        number += 1

    return f"Player{number}"


# ============================================================
# Відправити стан усім
# ============================================================

async def broadcast():

    if not players:
        return

    data = {
        "type": "players",
        "players": {}
    }

    for name, player in players.items():

        data["players"][name] = {
            "x": player["x"],
            "y": player["y"]
        }

    message = json.dumps(data)

    disconnected = []

    for name, player in players.items():

        try:
            await player["websocket"].send_text(message)

        except Exception:
            disconnected.append(name)

    for name in disconnected:

        if name in players:
            del players[name]


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    player_name = get_player_name()

    players[player_name] = {
        "websocket": websocket,
        "x": 640,
        "y": 360
    }

    print(f"{player_name} connected")

    # Повідомляємо новому гравцю його ім'я
    await websocket.send_text(
        json.dumps({
            "type": "welcome",
            "name": player_name
        })
    )

    # Оновлюємо всіх
    await broadcast()

    try:

        while True:

            message = await websocket.receive_text()

            data = json.loads(message)

            # ------------------------------------------------
            # Позиція гравця
            # ------------------------------------------------

            if data.get("type") == "position":

                x = float(data.get("x", 0))
                y = float(data.get("y", 0))

                players[player_name]["x"] = x
                players[player_name]["y"] = y

                # Розсилаємо нову позицію всім гравцям
                await broadcast()

    except WebSocketDisconnect:

        print(f"{player_name} disconnected")

    except Exception as e:

        print(f"{player_name} error:", e)

    finally:

        if player_name in players:
            del players[player_name]

        await broadcast()

        print(f"{player_name} removed")


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

    port = int(os.environ.get("PORT", 10000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )