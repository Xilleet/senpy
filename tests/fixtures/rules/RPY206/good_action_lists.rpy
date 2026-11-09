default is_hovered = False
default money = 100

screen complex_ui():
    textbutton "Click Me":
        # Списки экшенов и события hovered/unhovered безопасны
        action [SetVariable("money", money + 10), Return()]
        hovered SetVariable("is_hovered", True)
        unhovered SetVariable("is_hovered", False)

label start:
    call screen complex_ui
    return