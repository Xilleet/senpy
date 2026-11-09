default player_gold = 100

label shop_hub:
    menu:
        # Выбор с аргументами в скобках
        "Buy Excalibur" ("legendary", cost=100) if player_gold >= 100:
            $ got_excalibur = True
            "You obtained Excalibur!"

        "Leave empty-handed" (icon="door"):
            "You left."

    # Асимметрия: переменная есть только в первой ветке
    if got_excalibur:
        "Wielding the sword!"
    return