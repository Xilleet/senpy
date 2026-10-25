label start:
    if is_game_over:
        $ renpy.full_restart()
    else:
        $ score = 100

    # Первая ветка выходит через $ renpy.full_restart().
    # Переменная score гарантирована, здесь НЕ должно быть ошибки RPY404!
    if score > 50:
        "Победа: [score]"
    return