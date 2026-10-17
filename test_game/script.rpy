init python:
    # Функции из init python теперь автоматически регистрируются в памяти линтера
    def calculate_bonus(x):
        return x * 2

    import random   # RPY106

image bg room = "room_day.png"
image bg room = "room_night.png"   # RPY504

default friend_name = "Дима"

# НОВОЕ: объявляем константу через define:
define max_hp = 100

label start:
    "Добро пожаловать в игру!"

    # 1. НОВОЕ (RPY105): попытка изменить define через +=:
    $ max_hp += 10

    # Проверяем многострочный блок:
    python:
        unregistered_var = 100       # RPY104: переменная без default
        magic_points += 5            # RPY102: += до default

    call sub_scene   # RPY306

default player_gold = 100

# Тестовый экран магазина с опасными ошибками:
screen shop():
    # 1. Прямая мутация переменной прямо в теле экрана (RPY201):
    $ player_gold -= 10 

    # 2. Обращение к переменной, которой нет в default (RPY202):
    if special_discount_active: 
        text "Скидка активна!"

    # 3. НОВОЕ (RPY203): Кнопка без действия (action):
    textbutton "Купить меч"

label bad_end:
    "Это тупиковая концовка, и линтер на нее НЕ ругается!"

label chapter_two:
    # 1. Незакрытый тег {b} (RPY301):
    "Внимание: {b}опасная зона!"  

    # 2. Прыжок с опечаткой в имени метки (RPY302):
    jump bad_edd 

$ player_gold -= 10 

label test_flow:
    menu:
        "Взять факел":
            $ has_torch = True
            "Вы берете факел."

        "Идти в темноте":
            "Вы идете наощупь."

        # 1. НОВОЕ (RPY402): Пункт меню объявлен, а кода под ним нет!
        "Сдаться и лечь спать":

    # Обе ветки сошлись сюда (RPY401):
    if has_torch:
        "Свет факела разгоняет тьму."

label test_new_rules:
    # 1. Битый hex-цвет в теге {color} (RPY304):
    "Этот текст покрашен {color=#12345}странным цветом{/color}."

    # 2. Несуществующая музыка (RPY501):
    play music "bgm/non_existent_track.ogg"

# 3. Мертвая метка (на нее нигде во всей игре нет jump/call):
label forgotten_secret_draft:
    jump missing_secret_room
    "Привет [ghost_character], добро пожаловать в {b}подвал!"
    "Этот кусок сценарист написал и забыл подключить к сюжету."