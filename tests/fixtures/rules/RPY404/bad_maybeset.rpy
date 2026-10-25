label start:
    menu:
        "Поговорить с Юри":
            $ met_yuri = True
        "Уйти":
            pass

    # Переменная met_yuri может не существовать
    if met_yuri:
        "Вы вспоминаете Юри."
        
    "В инвентаре: [met_yuri]"
    return