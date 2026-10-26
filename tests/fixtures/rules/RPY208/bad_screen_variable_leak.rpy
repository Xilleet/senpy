screen shop(discount_rate=0.1):
    default selected_item = "none"
    default is_confirmed = False

    # 1. SetVariable на локальной переменной
    textbutton "Sword" action SetVariable("selected_item", "sword")

    # 2. ToggleVariable на локальной переменной
    textbutton "Confirm" action ToggleVariable("is_confirmed")

    # 3. Мутация аргумента экрана через Python
    $ discount_rate = 0.2