screen inventory_hud():
    text "Inventory"

screen main_ui():
    textbutton "Open" action Show("inventroy_hud")          # Опечатка в inventory_hud
    textbutton "Custom" action ShowMenu("ghost_menu")       # Несуществующий экран