default player_gold = 100
default sound_muted = False

screen shop():
    textbutton "Buy" action SetVariable("plater_gold", 50)     # Опечатка в player_gold
    textbutton "Mute" action ToggleVariable("snd_muted")       # Опечатка в sound_muted