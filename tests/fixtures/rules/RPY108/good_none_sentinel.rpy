default help_sayori = None
default quest_item = None
default active_enemy = "Goblin"
default enemy_health = 100

label start:
    # 1. Присваивание типа переменной со значением по умолчанию None
    $ help_sayori = True
    $ quest_item = "Sword"

    # 2. Сброс типизированных переменных обратно в sentinel None
    $ active_enemy = None
    $ enemy_health = None
    return