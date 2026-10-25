screen inventory_hud():
    text "Inventory"

screen main_ui():
    textbutton "Legit" action Show("inventory_hud")
    textbutton "Save" action ShowMenu("save")
    textbutton "Close" action Hide()