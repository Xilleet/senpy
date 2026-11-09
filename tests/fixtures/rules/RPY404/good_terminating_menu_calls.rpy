label start:
    menu:
        "Сдаться и выйти":
            $ renpy.quit()
        "Продолжить бой":
            $ sword_durability = 100

    # Первая ветка меню завершилась через $ renpy.quit().
    # Асимметрии нет, здесь НЕ должно быть ошибки RPY401!
    if sword_durability > 0:
        "Меч готов к бою."
    return