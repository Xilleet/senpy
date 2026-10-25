default met_yuri = False

label start:
    menu:
        "Поговорить с Юри":
            $ met_yuri = True
        "Уйти":
            pass

    if met_yuri:
        "Вы вспоминаете Юри."
    return