label dungeon_hub:
    "You enter the hub."
    jump .armory

label .armory:
    "Inside the local armory sub-scene."
    return

label outside:
    # Ошибка: прыжок на несуществующую локальную под-метку
    jump .missing_sub