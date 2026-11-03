screen main_menu():
    textbutton "Start" action Start()

label start:
    call screen main_menu
    "Game starts."
    return
