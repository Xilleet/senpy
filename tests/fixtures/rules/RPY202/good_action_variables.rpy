default player_gold = 100
default sound_muted = False

screen shop():
    textbutton "Legit Buy" action SetVariable("player_gold", 90)
    textbutton "Legit Mute" action ToggleVariable("sound_muted")