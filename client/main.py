import pygame
import sys
import math
import threading
import json
import hashlib
import websocket


# ============================================================
# Налаштування
# ============================================================

WIDTH = 1280
HEIGHT = 720

FPS = 60

PLAYER_SIZE = 50
PLAYER_SPEED = 300

SERVER_URL = "wss://mymultiplayergame.onrender.com/ws"


# ============================================================
# Pygame
# ============================================================

pygame.init()

screen = pygame.display.set_mode(
    (WIDTH, HEIGHT)
)

pygame.display.set_caption(
    "Multiplayer Game"
)

clock = pygame.time.Clock()

font = pygame.font.SysFont(
    None,
    32
)

input_font = pygame.font.SysFont(
    None,
    42
)


# ============================================================
# Реєстрація
# ============================================================

nickname = ""
password = ""

registration_done = False

auth_mode = "login"

auth_message = ""

auth_waiting = False
auth_pending = False

input_field = "nickname"


# ============================================================
# Поля вводу
# ============================================================

nickname_rect = pygame.Rect(
    WIDTH // 2 - 50,
    215,
    350,
    50
)

password_rect = pygame.Rect(
    WIDTH // 2 - 50,
    285,
    350,
    50
)

# ============================================================
# Мій гравець
# ============================================================

my_id = None

player_x = WIDTH / 2
player_y = HEIGHT / 2

money = 0


# ============================================================
# Інші гравці
# ============================================================

other_players = {}


# ============================================================
# Монети (кинуті гроші)
# ============================================================

coins = {}

COIN_RADIUS = 7

COIN_DROP_COST = 5

COIN_PICKUP_DISTANCE = PLAYER_SIZE / 2 + COIN_RADIUS + 4

pending_collect = set()


# ============================================================
# WebSocket
# ============================================================

ws = None

connected = False

reconnect_lock = threading.Lock()

reconnecting = False
registration_reconnect = False


# ============================================================
# Завершення
# ============================================================

running = True
reconnect_thread = None


# ============================================================
# Колір з ніку
# ============================================================

def nickname_color(name):

    digest = hashlib.sha256(
        name.encode("utf-8")
    ).digest()

    r = max(digest[0], 80)
    g = max(digest[1], 80)
    b = max(digest[2], 80)

    return (r, g, b)


# ============================================================
# Отримання повідомлень
# ============================================================

def receive_messages(socket_connection):

    global my_id
    global connected
    global other_players

    global registration_done
    global password
    global auth_mode
    global nickname
    global auth_waiting
    global auth_pending
    global registration_reconnect
    global auth_message

    global player_x
    global player_y

    global money
    global coins
    global pending_collect

    try:

        while True:

            message = socket_connection.recv()

            if not message:
                break

            data = json.loads(message)

            message_type = data.get("t")

            # =================================================
            # Успішний вхід
            # =================================================

            if message_type == "w":

                my_id = data["i"]

                nickname = data["n"]

                print(
                    "Logged in as:",
                    nickname
                )

                print(
                    "Your ID:",
                    my_id
                )

                print(
                    "Money:",
                    data["money"]
                )

                registration_done = True
                auth_waiting = False

                player_x = data["x"]
                player_y = data["y"]

                money = data["money"]

                continue


            # =================================================
            # Успішна реєстрація
            # =================================================

            if message_type == "registered":

                auth_message = (
                    "Account created! Please login."
                )

                auth_mode = "login"

                auth_waiting = False

                password = ""

                registration_reconnect = True

                continue


            # =================================================
            # Помилка авторизації
            # =================================================

            if message_type == "error":

                auth_message = data.get(
                    "m",
                    "Unknown error"
                )

                auth_waiting = False

                print(
                    "Server:",
                    auth_message
                )

                continue

            # =================================================
            # Heartbeat від сервера
            # =================================================

            if message_type == "h":

                try:

                    socket_connection.send(
                        '{"t":"a"}'
                    )

                except:

                    pass

                continue


            # =================================================
            # Оновлення суми грошей (після drop / collect)
            # =================================================

            if message_type == "money":

                money = data.get(
                    "money",
                    money
                )

                continue


            # =================================================
            # Помилка при спробі викинути гроші
            # =================================================

            if message_type == "drop_error":

                print(
                    "Drop error:",
                    data.get("m", "Unknown error")
                )

                continue


            # =================================================
            # Початковий список активних монет
            # (після логіну / reconnect)
            # =================================================

            if message_type == "cs":

                new_coins = {}

                for coin in data.get("c", []):

                    new_coins[coin["i"]] = {
                        "x": coin["x"],
                        "y": coin["y"]
                    }

                coins.clear()
                coins.update(new_coins)

                pending_collect.clear()

                continue


            # =================================================
            # З'явилась нова монета
            # =================================================

            if message_type == "c":

                coins[data["i"]] = {
                    "x": data["x"],
                    "y": data["y"]
                }

                continue


            # =================================================
            # Монету підібрали (видалити у всіх)
            # =================================================

            if message_type == "cr":

                coins.pop(
                    data.get("i"),
                    None
                )

                pending_collect.discard(
                    data.get("i")
                )

                continue


            # =================================================
            # Список існуючих гравців
            # =================================================

            elif message_type == "s":

                # Повністю оновлюємо список
                # після підключення / reconnect

                new_players = {}

                for player in data.get("p", []):

                    player_id = player["i"]

                    if player_id == my_id:
                        continue

                    new_players[player_id] = {

                        "name": player["n"],

                        "x": player["x"],

                        "y": player["y"],

                        "target_x": player["x"],

                        "target_y": player["y"]
                    }


                other_players = new_players


            # =================================================
            # Новий гравець
            # =================================================

            elif message_type == "j":

                player_id = data["i"]

                if player_id == my_id:
                    continue


                other_players[player_id] = {

                    "name": data["n"],

                    "x": data["x"],

                    "y": data["y"],

                    "target_x": data["x"],

                    "target_y": data["y"]
                }


            # =================================================
            # Позиція
            # =================================================

            elif message_type == "p":

                player_id = data["i"]


                # Не приймаємо власні координати

                if player_id == my_id:
                    continue


                # Якщо гравець ще не був
                # зареєстрований через j/s —
                # НЕ створюємо його

                if player_id not in other_players:
                    continue


                other_players[player_id]["target_x"] = data["x"]

                other_players[player_id]["target_y"] = data["y"]


            # =================================================
            # Гравець вийшов
            # =================================================

            elif message_type == "l":

                player_id = data["i"]

                other_players.pop(
                    player_id,
                    None
                )


    except Exception as e:

        print(
            "WebSocket error:",
            e
        )


    finally:

        # ================================================
        # Дуже важливо:
        #
        # перевіряємо саме ЦЕ з'єднання.
        #
        # Старий socket не повинен закрити
        # новий socket після reconnect.
        # ================================================

        global ws

        if ws is socket_connection:

            connected = False

            # ================================================
            # Якщо з'єднання розірвалось саме тоді, коли ми
            # чекали відповідь на login/register (auth_waiting
            # було True) — запит фактично "загубився":
            # сервер міг його не отримати або відповідь не
            # дійшла. Позначаємо auth_pending, щоб
            # reconnect_loop() автоматично повторив цей самий
            # запит після відновлення з'єднання, а не чекав
            # повторного натискання ENTER користувачем.
            # ================================================

            if auth_waiting and not registration_done:
                auth_pending = True

            auth_waiting = False

            try:
                socket_connection.close()
            except:
                pass


# ============================================================
# Підключення
# ============================================================

def connect_to_server(auto_login=False):

    global ws
    global connected
    global my_id
    global other_players
    global coins
    global pending_collect
    global auth_waiting
    global auth_pending
    global auth_mode

    try:

        print(
            "Connecting to server..."
        )


        # ====================================================
        # Створюємо НОВИЙ socket
        # ====================================================

        new_ws = websocket.create_connection(
            SERVER_URL,
            timeout=10
        )

        new_ws.settimeout(None)


        # ====================================================
        # Робимо його поточним
        # ====================================================

        ws = new_ws

        connected = True

        my_id = None


        # ====================================================
        # Очищаємо старих гравців та монети
        # (актуальний список монет прийде через "cs"
        # одразу після успішного логіну)
        # ====================================================

        other_players.clear()

        coins.clear()

        pending_collect.clear()


        print(
            "Connected!"
        )


        print(
            "Authentication socket ready."
        )


        # ====================================================
        # Потік отримання
        # ====================================================

        thread = threading.Thread(

            target=receive_messages,

            args=(new_ws,),

            daemon=True
        )

        thread.start()


        if (
            (auto_login or auth_pending)
            and nickname
            and password
        ):

            try:

                # ====================================================
                # Для reconnect вже залогіненого гравця (auto_login)
                # завжди повторюємо саме "login". Але якщо реконект
                # стався ще на екрані логіну/реєстрації (auth_pending),
                # повторюємо той самий запит, який надсилав користувач
                # (login або register) — а не завжди "login".
                # ====================================================

                request_type = (
                    "login" if auto_login else auth_mode
                )

                new_ws.send(
                    json.dumps(
                        {
                            "t": request_type,
                            "n": nickname,
                            "p": password
                        },
                        separators=(",", ":")
                    )
                )

                auth_waiting = True
                auth_pending = False

                print(
                    "Sending login request after reconnect..."
                )

            except Exception as e:

                print(
                    "Reconnect login error:",
                    e
                )

                auth_pending = True


        return True


    except Exception as e:

        print(
            "Connection failed:",
            e
        )

        connected = False

        return False


def send_auth():

    global auth_waiting
    global auth_pending
    global connected

    if not nickname:
        return

    if not password:
        return

    # ============================================
    # Якщо socket відсутній —
    # запам'ятовуємо LOGIN.
    # ============================================

    if not connected:

        auth_pending = True

        print(
            "Login queued. Waiting for connection..."
        )

        return

    try:

        message = {
            "t": auth_mode,
            "n": nickname,
            "p": password
        }

        ws.send(
            json.dumps(
                message,
                separators=(",", ":")
            )
        )

        auth_waiting = True
        auth_pending = False

        print(
            "Sending",
            auth_mode,
            "request..."
        )

    except Exception as e:

        print(
            "Auth error:",
            e
        )

        auth_pending = True
        connected = False

# ============================================================
# Reconnect
# ============================================================

def reconnect_loop():

    global reconnecting
    global registration_reconnect
    global auth_waiting
    global auth_pending

    while running:

        # ====================================================
        # Після успішної реєстрації потрібно створити
        # нове з'єднання для входу
        # ====================================================

        if registration_reconnect:

            registration_reconnect = False

            print(
                "Registration completed. Reconnecting for login..."
            )

            auth_waiting = False

            connect_to_server()

            continue


        # ====================================================
        # Ми ще на екрані LOGIN / REGISTER
        #
        # Якщо сервер закрив socket після помилки —
        # автоматично створюємо новий socket.
        # ====================================================

        if not registration_done:

            if not connected:

                with reconnect_lock:

                    if reconnecting:

                        pygame.time.wait(100)

                        continue

                    reconnecting = True


                print(
                    "Authentication connection lost. Reconnecting..."
                )

                auth_waiting = False

                success = connect_to_server()

                if success:

                    print(
                        "Authentication socket restored."
                    )

                    # ============================================
                    # Якщо користувач уже натиснув ENTER,
                    # поки socket був відсутній —
                    # автоматично повторюємо LOGIN.
                    # ============================================

                else:

                    print(
                        "Authentication reconnect failed. Retrying..."
                    )

                    pygame.time.wait(500)


                reconnecting = False

            else:

                pygame.time.wait(100)

            continue


        # ====================================================
        # Гравець вже увійшов.
        # Якщо з'єднання втрачено — робимо reconnect
        # і автоматично повторюємо LOGIN.
        # ====================================================

        if not connected:

            with reconnect_lock:

                if reconnecting:

                    pygame.time.wait(100)

                    continue

                reconnecting = True


            print(
                "Connection lost. Reconnecting..."
            )

            success = connect_to_server(
                auto_login=True
            )

            if success:

                print(
                    "Reconnected!"
                )

            else:

                print(
                    "Retrying in 3 seconds..."
                )

                pygame.time.wait(3000)


            reconnecting = False

        else:

            pygame.time.wait(500)


# ============================================================
# Відправлення позиції
# ============================================================

def send_position():

    global ws
    global connected
    if not connected:
        return


    try:

        x = int(
            round(player_x)
        )

        y = int(
            round(player_y)
        )


        # ====================================================
        # Мінімальне повідомлення
        # ====================================================

        message = json.dumps(

            {
                "t": "p",
                "x": x,
                "y": y
            },

            separators=(",", ":")
        )


        ws.send(message)


    except Exception as e:

        print(
            "Send error:",
            e
        )

        connected = False


# ============================================================
# Викинути гроші (5) у напрямку курсора
# ============================================================

def send_drop():

    global ws
    global connected
    global money

    if not connected:
        return

    if not registration_done:
        return

    if money < COIN_DROP_COST:

        print(
            "Not enough money to drop"
        )

        return


    # ========================================================
    # Напрямок від гравця до курсора миші.
    # Сам курсор і world-координати збігаються 1:1,
    # оскільки камера не зміщується.
    # ========================================================

    mouse_x, mouse_y = pygame.mouse.get_pos()

    dx = mouse_x - player_x
    dy = mouse_y - player_y

    try:

        message = json.dumps(

            {
                "t": "drop",
                "dx": dx,
                "dy": dy
            },

            separators=(",", ":")
        )

        ws.send(message)

        print(
            "Dropped",
            COIN_DROP_COST,
            "money"
        )

    except Exception as e:

        print(
            "Drop send error:",
            e
        )

        connected = False


send_timer = 0.0

was_moving = False

last_sent_x = None
last_sent_y = None

# ============================================================
# Початкове підключення
# ============================================================

connect_to_server()

reconnect_thread = threading.Thread(
    target=reconnect_loop,
    daemon=True
)

reconnect_thread.start()

# ============================================================
# Головний цикл
# ============================================================

while running:

    dt = clock.tick(FPS) / 1000.0


    # ========================================================
    # Події
    # ========================================================

    for event in pygame.event.get():

        if event.type == pygame.QUIT:

            running = False


        # ====================================================
        # Введення ніку
        # ====================================================

        if not registration_done:

            if event.type == pygame.MOUSEBUTTONDOWN:

                if event.button == 1:

                    if nickname_rect.collidepoint(event.pos):

                        input_field = "nickname"

                        auth_message = ""


                    elif password_rect.collidepoint(event.pos):

                        input_field = "password"

                        auth_message = ""

            if event.type == pygame.KEYDOWN:

                # =================================================
                # TAB — перемикання LOGIN / REGISTER
                # =================================================

                if event.key == pygame.K_TAB:

                    if auth_mode == "login":

                        auth_mode = "register"

                    else:

                        auth_mode = "login"


                    auth_message = ""

                    password = ""

                    auth_waiting = False


                # =================================================
                # ENTER — відправити
                # =================================================

                elif event.key == pygame.K_RETURN:

                    if not auth_waiting:

                        send_auth()


                # =================================================
                # BACKSPACE
                # =================================================

                elif event.key == pygame.K_BACKSPACE:

                    if input_field == "nickname":

                        nickname = nickname[:-1]

                    else:

                        password = password[:-1]


                # =================================================
                # Перемикання поля
                # =================================================

                elif event.key == pygame.K_UP:

                    input_field = "nickname"


                elif event.key == pygame.K_DOWN:

                    input_field = "password"


                # =================================================
                # Символ
                # =================================================

                else:

                    if not event.unicode.isprintable():

                        continue


                    if input_field == "nickname":

                        if len(nickname) < 15:

                            nickname += event.unicode


                    else:

                        if len(password) < 64:

                            password += event.unicode


        # ====================================================
        # Гра: викинути гроші (Q)
        # ====================================================

        else:

            if event.type == pygame.KEYDOWN:

                if event.key == pygame.K_q:

                    send_drop()


    # ========================================================
    # Екран LOGIN / REGISTER
    # ========================================================

    if not registration_done:

        screen.fill(
            (100, 100, 100)
        )


        # ----------------------------------------------------
        # Заголовок
        # ----------------------------------------------------

        title_text = (
            "LOGIN"
            if auth_mode == "login"
            else
            "REGISTER"
        )


        title = input_font.render(
            title_text,
            True,
            (255, 255, 255)
        )


        screen.blit(
            title,
            (
                WIDTH // 2 -
                title.get_width() // 2,
                120
            )
        )


        # ----------------------------------------------------
        # Nickname
        # ----------------------------------------------------

        nickname_label = font.render(
            "Nickname:",
            True,
            (230, 230, 230)
        )


        screen.blit(
            nickname_label,
            (
                WIDTH // 2 - 250,
                230
            )
        )


        # ----------------------------------------------------
        # Поле Nickname
        # ----------------------------------------------------

        nickname_background = pygame.Surface(
            nickname_rect.size,
            pygame.SRCALPHA
        )

        nickname_background.fill(
            (50, 50, 50, 180)
        )

        screen.blit(
            nickname_background,
            nickname_rect.topleft
        )


        nickname_border_color = (

            (255, 255, 255)

            if input_field == "nickname"

            else

            (130, 130, 130)
        )


        pygame.draw.rect(
            screen,
            nickname_border_color,
            nickname_rect,
            3
        )


        nickname_display = font.render(
            nickname,
            True,
            (255, 255, 255)
        )


        screen.blit(
            nickname_display,
            (
                nickname_rect.x + 12,
                nickname_rect.y + 8
            )
        )


        # ----------------------------------------------------
        # Password
        # ----------------------------------------------------

        password_label = font.render(
            "Password:",
            True,
            (230, 230, 230)
        )


        screen.blit(
            password_label,
            (
                WIDTH // 2 - 250,
                300
            )
        )


        # ----------------------------------------------------
        # Поле Password
        # ----------------------------------------------------

        password_background = pygame.Surface(
            password_rect.size,
            pygame.SRCALPHA
        )

        password_background.fill(
            (50, 50, 50, 180)
        )

        screen.blit(
            password_background,
            password_rect.topleft
        )


        password_border_color = (

            (255, 255, 255)

            if input_field == "password"

            else

            (130, 130, 130)
        )


        pygame.draw.rect(
            screen,
            password_border_color,
            password_rect,
            3
        )


        password_display = "*" * len(password)


        password_text = font.render(
            password_display,
            True,
            (255, 255, 255)
        )


        screen.blit(
            password_text,
            (
                password_rect.x + 12,
                password_rect.y + 8
            )
        )


        # ----------------------------------------------------
        # Кнопка / підказка
        # ----------------------------------------------------

        if auth_mode == "login":

            info_text = (
                "ENTER - Login    TAB - Register"
            )

        else:

            info_text = (
                "ENTER - Register    TAB - Login"
            )


        info = font.render(
            info_text,
            True,
            (220, 220, 220)
        )


        screen.blit(
            info,
            (
                WIDTH // 2 -
                info.get_width() // 2,
                400
            )
        )


        # ----------------------------------------------------
        # Повідомлення сервера
        # ----------------------------------------------------

        if auth_message:

            message_text = font.render(
                auth_message,
                True,
                (255, 220, 100)
            )


            screen.blit(
                message_text,
                (
                    WIDTH // 2 -
                    message_text.get_width() // 2,
                    470
                )
            )


        # ----------------------------------------------------
        # Очікування
        # ----------------------------------------------------

        if auth_waiting:

            waiting = font.render(
                "Connecting...",
                True,
                (220, 220, 220)
            )


            screen.blit(
                waiting,
                (
                    WIDTH // 2 -
                    waiting.get_width() // 2,
                    520
                )
            )


        pygame.display.flip()

        continue


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

        length = math.sqrt(
            dx * dx +
            dy * dy
        )

        dx /= length
        dy /= length


    # ========================================================
    # Рух
    # ========================================================

    player_x += (
        dx *
        PLAYER_SPEED *
        dt
    )

    player_y += (
        dy *
        PLAYER_SPEED *
        dt
    )


    # ========================================================
    # Межі
    # ========================================================

    half = PLAYER_SIZE / 2


    player_x = max(

        half,

        min(
            WIDTH - half,
            player_x
        )
    )


    player_y = max(

        half,

        min(
            HEIGHT - half,
            player_y
        )
    )


    # ========================================================
    # Відправлення позиції
    # ========================================================

    is_moving = (

        dx != 0 or
        dy != 0
    )


    if is_moving:

        send_timer += dt


        if send_timer >= 0.1:

            send_timer = 0.0


            current_x = int(
                round(player_x)
            )

            current_y = int(
                round(player_y)
            )


            if (

                current_x != last_sent_x

                or

                current_y != last_sent_y

            ):

                send_position()

                last_sent_x = current_x

                last_sent_y = current_y


    elif was_moving:

        current_x = int(
            round(player_x)
        )

        current_y = int(
            round(player_y)
        )


        if (

            current_x != last_sent_x

            or

            current_y != last_sent_y

        ):

            send_position()

            last_sent_x = current_x

            last_sent_y = current_y


        send_timer = 0.0


    was_moving = is_moving


    # ========================================================
    # Підбір монет (дотик гравця до кульки)
    # ========================================================

    if connected and registration_done:

        for coin_id, coin in list(coins.items()):

            if coin_id in pending_collect:
                continue

            distance = math.hypot(
                player_x - coin["x"],
                player_y - coin["y"]
            )

            if distance <= COIN_PICKUP_DISTANCE:

                pending_collect.add(coin_id)

                try:

                    ws.send(
                        json.dumps(
                            {
                                "t": "collect",
                                "i": coin_id
                            },
                            separators=(",", ":")
                        )
                    )

                except Exception as e:

                    print(
                        "Collect send error:",
                        e
                    )

                    pending_collect.discard(coin_id)


    # ========================================================
    # Плавність інших гравців
    # ========================================================

    interpolation_speed = 12


    for player in other_players.values():

        player["x"] += (

            player["target_x"] -
            player["x"]

        ) * interpolation_speed * dt


        player["y"] += (

            player["target_y"] -
            player["y"]

        ) * interpolation_speed * dt


    # ========================================================
    # Малювання
    # ========================================================

    screen.fill(
        (30, 30, 30)
    )


    # ========================================================
    # Монети
    # ========================================================

    for coin_id, coin in coins.items():

        pygame.draw.circle(

            screen,

            (255, 215, 0),

            (
                int(coin["x"]),
                int(coin["y"])
            ),

            COIN_RADIUS
        )


    # ========================================================
    # Інші гравці
    # ========================================================

    for player in other_players.values():

        color = nickname_color(
            player["name"]
        )


        pygame.draw.rect(

            screen,

            color,

            (
                int(
                    player["x"] -
                    half
                ),

                int(
                    player["y"] -
                    half
                ),

                PLAYER_SIZE,

                PLAYER_SIZE
            )
        )


        text = font.render(

            player["name"],

            True,

            (255, 255, 255)
        )


        screen.blit(

            text,

            (
                int(
                    player["x"] -
                    text.get_width() / 2
                ),

                int(
                    player["y"] -
                    half -
                    30
                )
            )
        )


    # ========================================================
    # Наш гравець
    # ========================================================

    my_color = nickname_color(
        nickname
    )


    pygame.draw.rect(

        screen,

        my_color,

        (
            int(
                player_x -
                half
            ),

            int(
                player_y -
                half
            ),

            PLAYER_SIZE,

            PLAYER_SIZE
        )
    )


    text = font.render(

        nickname,

        True,

        (255, 255, 255)
    )


    screen.blit(

        text,

        (
            int(
                player_x -
                text.get_width() / 2
            ),

            int(
                player_y -
                half -
                30
            )
        )
    )


    # ========================================================
    # Статус
    # ========================================================

    status = (

        "ONLINE"

        if connected

        else

        "OFFLINE"
    )


    status_text = font.render(

        status,

        True,

        (255, 255, 255)
    )


    screen.blit(

        status_text,

        (10, 10)
    )


    # ========================================================
    # Гроші
    # ========================================================

    money_text = font.render(
        f"Money: {money}",
        True,
        (255, 215, 0)
    )

    screen.blit(
        money_text,
        (10, 40)
    )


    pygame.display.flip()


# ============================================================
# Завершення
# ============================================================

running = False


if ws:

    try:

        ws.close()

    except:

        pass


pygame.quit()

sys.exit()