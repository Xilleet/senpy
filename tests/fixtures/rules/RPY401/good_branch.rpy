default weapon = None

label start:
    menu:
        "Взять меч":
            $ weapon = "sword"
        "Сбежать":
            $ weapon = "none"
            
    if weapon == "sword":
        "Атакуем!"
    return