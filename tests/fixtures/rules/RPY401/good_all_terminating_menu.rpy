label start:
    menu:
        "Take Left Tunnel":
            menu:
                "Step into fire":
                    $ fate = "burned"
                    jump death_ending
                "Drink poison":
                    $ fate = "poisoned"
                    return
        "Take Right Tunnel":
            $ fate = "crushed"
            jump rock_ending

    # Сюда управление никогда не дойдет (все ветки завершаются), поэтому ошибки нет
    if fate == "burned":
        "Impossible point."

label death_ending:
    return

label rock_ending:
    return