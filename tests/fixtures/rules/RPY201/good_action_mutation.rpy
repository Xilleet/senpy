screen shop():
    textbutton "Buy (-10 gold)" action SetVariable("player_gold", player_gold - 10)
    text "Gold: [player_gold]"
