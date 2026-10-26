default global_gold = 100

screen shop(discount_rate=0.1):
    default selected_item = "none"
    default is_confirmed = False

    textbutton "Legit Pick" action SetScreenVariable("selected_item", "axe")
    textbutton "Legit Toggle" action ToggleScreenVariable("is_confirmed")
    textbutton "Global Buy" action SetVariable("global_gold", 50)