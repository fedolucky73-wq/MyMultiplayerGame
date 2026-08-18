import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


app = FastAPI()


# ============================================================
# Гравці
# ============================================================

players = {}

next_player_id = 1


# ============================================================
# Отримати ID
# ============================================================

def get_player_id():

    global next_player_id

    player_id = next_player_id

    next_player_id += 1

    return player_id


# ============================================================
# Відправити позицію іншому гравцю
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


    for player_id in disconnected:

        players.pop(player_id, None)


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

        try:

            await player["websocket"].send_text(message)

        except Exception:

            disconnected.append(other_id)


    for other_id in disconnected:

        players.pop(other_id, None)


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    player_id = get_player_id()


    # ========================================================
    # Чекаємо реєстрацію
    # ========================================================

    try:

        message = await websocket.receive_text()

        data = json.loads(message)

        if data.get("t") != "r":

            await websocket.close()

            return

        nickname = str(
            data.get("n", "Player")
        )[:10]


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
        # Відправляємо ID гравцю
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
        # Передаємо новому гравцю існуючих гравців
        #
        # Тут нік потрібен тільки ОДИН раз.
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
        # Повідомляємо старих гравців про нового
        # ====================================================

        new_player_message = json.dumps(

            {
                "t": "j",
                "i": player_id,
                "n": nickname,
                "x": 640,
                "y": 360
            },

            separators=(",", ":")
        )


        disconnected = []


        for other_id, player in list(players.items()):

            if other_id == player_id:
                continue

            try:

                await player["websocket"].send_text(
                    new_player_message
                )

            except Exception:

                disconnected.append(other_id)


        for other_id in disconnected:

            players.pop(other_id, None)


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

                x = int(data.get("x", 0))
                y = int(data.get("y", 0))


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

        if player_id in players:

            del players[player_id]

            await broadcast_player_left(
                player_id
            )

            print(
                f"Player {player_id} removed"
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