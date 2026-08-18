import pygame
import sys
import math
import threading
import json
import time
import websocket


# ============================================================
# Налаштування
# ============================================================

WIDTH = 1280
HEIGHT = 720

FPS = 60

PLAYER_SIZE = 50
PLAYER_SPEED = 300

# ------------------------------------------------------------
# ПОКИ ЩО ЛОКАЛЬНИЙ СЕРВЕР
# ------------------------------------------------------------

SERVER_URL = "wss://mymultiplayergame.onrender.com/ws"


# ============================================================
# Pygame
# ============================================================

pygame.init()

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Multiplayer Game")

clock = pygame.time.Clock()

font = pygame.font.SysFont(None, 32)


# ============================================================
# Мій гравець
# ============================================================

my_name = "Connecting..."

player_x = WIDTH / 2
player_y = HEIGHT / 2


# ============================================================
# Інші гравці
# ============================================================

other_players = {}


# ============================================================
# WebSocket
# ============================================================

ws = None

connected = False


# ============================================================
# WebSocket отримання повідомлень
# ============================================================

def receive_messages():

    global my_name
    global connected
    global other_players

    try:

        while True:

            message = ws.recv()

            if not message:
                break

            data = json.loads(message)

            # -----------------------------------------------
            # Наше ім'я
            # -----------------------------------------------

            if data.get("type") == "welcome":

                my_name = data["name"]

                print("You are:", my_name)

            # -----------------------------------------------
            # Позиції гравців
            # -----------------------------------------------

            elif data.get("type") == "players":

                server_players = data["players"]

                for name, position in server_players.items():

                    if name == my_name:
                        continue

                    # Якщо нового гравця ще немає
                    if name not in other_players:

                        other_players[name] = {
                            "x": position["x"],
                            "y": position["y"],
                            "target_x": position["x"],
                            "target_y": position["y"]
                        }

                    else:

                        # Нова ціль для плавного руху
                        other_players[name]["target_x"] = position["x"]
                        other_players[name]["target_y"] = position["y"]

                # Видаляємо тих, хто вийшов
                for name in list(other_players.keys()):

                    if name not in server_players:

                        del other_players[name]

    except Exception as e:

        print("WebSocket error:", e)

        connected = False


# ============================================================
# Підключення
# ============================================================

def connect_to_server():

    global ws
    global connected

    try:

        print("Connecting to server...")

        ws = websocket.create_connection(
            SERVER_URL
        )

        ws.settimeout(None)

        connected = True

        print("Connected!")

        thread = threading.Thread(
            target=receive_messages,
            daemon=True
        )

        thread.start()

    except Exception as e:

        print("Connection failed:", e)

        connected = False


# ============================================================
# Відправлення позиції
# ============================================================

def send_position():

    if not connected:
        return

    try:

        ws.send(
            json.dumps({
                "type": "position",
                "x": player_x,
                "y": player_y
            })
        )

    except Exception as e:

        print("Send error:", e)


# ============================================================
# Підключаємося
# ============================================================

connect_to_server()


# ============================================================
# Таймер відправки
# ============================================================

send_timer = 0


# ============================================================
# Головний цикл
# ============================================================

running = True

while running:

    dt = clock.tick(FPS) / 1000.0

    # ========================================================
    # Події
    # ========================================================

    for event in pygame.event.get():

        if event.type == pygame.QUIT:

            running = False

    # ========================================================
    # Керування
    # ========================================================

    keys = pygame.key.get_pressed()

    dx = 0
    dy = 0

    if keys[pygame.K_a] or keys[pygame.K_LEFT]:
        dx -= 1

    if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
        dx += 1

    if keys[pygame.K_w] or keys[pygame.K_UP]:
        dy -= 1

    if keys[pygame.K_s] or keys[pygame.K_DOWN]:
        dy += 1

    # ========================================================
    # Нормалізація
    # ========================================================

    if dx != 0 or dy != 0:

        length = math.sqrt(dx * dx + dy * dy)

        dx /= length
        dy /= length

    # ========================================================
    # Рух
    # ========================================================

    player_x += dx * PLAYER_SPEED * dt
    player_y += dy * PLAYER_SPEED * dt

    # ========================================================
    # Межі
    # ========================================================

    half = PLAYER_SIZE / 2

    player_x = max(
        half,
        min(WIDTH - half, player_x)
    )

    player_y = max(
        half,
        min(HEIGHT - half, player_y)
    )

    # ========================================================
    # Відправляємо позицію кожні 0.1 секунди
    # ========================================================

    send_timer += dt

    if send_timer >= 0.1:

        send_timer = 0

        send_position()

    # ========================================================
    # Плавний рух інших гравців
    # ========================================================

    interpolation_speed = 12

    for player in other_players.values():

        player["x"] += (
            player["target_x"] - player["x"]
        ) * interpolation_speed * dt

        player["y"] += (
            player["target_y"] - player["y"]
        ) * interpolation_speed * dt

    # ========================================================
    # Малювання
    # ========================================================

    screen.fill((30, 30, 30))

    # --------------------------------------------------------
    # Інші гравці
    # --------------------------------------------------------

    for name, player in other_players.items():

        pygame.draw.rect(
            screen,
            (255, 0, 0),
            (
                int(player["x"] - half),
                int(player["y"] - half),
                PLAYER_SIZE,
                PLAYER_SIZE
            )
        )

        text = font.render(
            name,
            True,
            (255, 255, 255)
        )

        screen.blit(
            text,
            (
                int(player["x"] - text.get_width() / 2),
                int(player["y"] - half - 30)
            )
        )

    # --------------------------------------------------------
    # Наш гравець
    # --------------------------------------------------------

    pygame.draw.rect(
        screen,
        (255, 0, 0),
        (
            int(player_x - half),
            int(player_y - half),
            PLAYER_SIZE,
            PLAYER_SIZE
        )
    )

    text = font.render(
        my_name,
        True,
        (255, 255, 255)
    )

    screen.blit(
        text,
        (
            int(player_x - text.get_width() / 2),
            int(player_y - half - 30)
        )
    )

    # --------------------------------------------------------
    # Статус
    # --------------------------------------------------------

    status = "ONLINE" if connected else "OFFLINE"

    status_text = font.render(
        status,
        True,
        (255, 255, 255)
    )

    screen.blit(
        status_text,
        (10, 10)
    )

    pygame.display.flip()


# ============================================================
# Завершення
# ============================================================

if ws:

    try:
        ws.close()
    except:
        pass

pygame.quit()
sys.exit()