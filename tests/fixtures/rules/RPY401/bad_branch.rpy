label start:
    menu:
        "Взять меч":
            $ weapon = "sword"
            "Вы взяли меч."
        "Сбежать":
            "Вы убежали с пустыми руками."
    
    if weapon:
        "Атакуем!"
    return