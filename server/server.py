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


# ============================================================
# Отримати вільний номер
# ============================================================

def get_player_name():

    number = 1

    while f"Player{number}" in players:
        number += 1

    return f"Player{number}"


# ============================================================
# Відправити початковий список гравців
# ============================================================

async def send_initial_players(websocket, player_name):

    data = {
        "type": "players",
        "players": {}
    }

    for name, player in players.items():

        data["players"][name] = {
            "x": player["x"],
            "y": player["y"]
        }

    try:

        await websocket.send_text(
            json.dumps(
                data,
                separators=(",", ":")
            )
        )

    except Exception as e:

        print(f"Initial players send error: {e}")


# ============================================================
# Відправити нову позицію всім ІНШИМ гравцям
# ============================================================

async def broadcast_position(
    sender_name,
    x,
    y
):

    message = json.dumps(
        {
            "type": "position",
            "name": sender_name,
            "x": x,
            "y": y
        },
        separators=(",", ":")
    )

    disconnected = []

    for name, player in list(players.items()):

        # ================================================
        # НЕ відправляємо самому собі
        # ================================================

        if name == sender_name:
            continue

        try:

            await player["websocket"].send_text(
                message
            )

        except Exception as e:

            print(
                f"{name} send error:",
                e
            )

            disconnected.append(name)


    # ================================================
    # Видаляємо відключених
    # ================================================

    for name in disconnected:

        if name in players:

            del players[name]

            print(
                f"{name} removed after send error"
            )


# ============================================================
# Повідомити інших, що гравець вийшов
# ============================================================

async def broadcast_player_left(
    player_name
):

    message = json.dumps(
        {
            "type": "player_left",
            "name": player_name
        },
        separators=(",", ":")
    )

    disconnected = []

    for name, player in list(players.items()):

        try:

            await player["websocket"].send_text(
                message
            )

        except Exception:

            disconnected.append(name)


    for name in disconnected:

        if name in players:

            del players[name]


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    # ========================================================
    # Отримуємо ім'я
    # ========================================================

    player_name = get_player_name()


    # ========================================================
    # Створюємо гравця
    # ========================================================

    players[player_name] = {

        "websocket": websocket,

        "x": 640,

        "y": 360
    }


    print(
        f"{player_name} connected"
    )


    # ========================================================
    # Повідомляємо його ім'я
    # ========================================================

    await websocket.send_text(

        json.dumps(
            {
                "type": "welcome",
                "name": player_name
            },
            separators=(",", ":")
        )
    )


    # ========================================================
    # Відправляємо новому гравцю
    # поточний список інших гравців
    # ========================================================

    await send_initial_players(
        websocket,
        player_name
    )


    # ========================================================
    # Повідомляємо старих гравців,
    # що з'явився новий
    # ========================================================

    await broadcast_position(
        player_name,
        640,
        360
    )


    try:

        while True:

            message = await websocket.receive_text()

            data = json.loads(message)


            # =================================================
            # Позиція
            # =================================================

            if data.get("type") == "position":

                # ---------------------------------------------
                # Отримуємо цілі координати
                # ---------------------------------------------

                x = int(
                    round(
                        float(
                            data.get("x", 0)
                        )
                    )
                )

                y = int(
                    round(
                        float(
                            data.get("y", 0)
                        )
                    )
                )


                # ---------------------------------------------
                # Перевіряємо, чи гравець ще існує
                # ---------------------------------------------

                if player_name not in players:

                    break


                # ---------------------------------------------
                # Оновлюємо позицію на сервері
                # ---------------------------------------------

                players[player_name]["x"] = x
                players[player_name]["y"] = y


                # ---------------------------------------------
                # Відправляємо ТІЛЬКИ іншим
                # ---------------------------------------------

                await broadcast_position(
                    player_name,
                    x,
                    y
                )


    except WebSocketDisconnect:

        print(
            f"{player_name} disconnected"
        )


    except Exception as e:

        print(
            f"{player_name} error:",
            e
        )


    finally:

        # ====================================================
        # Видаляємо гравця
        # ====================================================

        if player_name in players:

            del players[player_name]


        # ====================================================
        # Повідомляємо інших
        # ====================================================

        await broadcast_player_left(
            player_name
        )


        print(
            f"{player_name} removed"
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