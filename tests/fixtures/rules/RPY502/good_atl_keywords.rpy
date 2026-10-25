image sayori 1a = "sayori.png"

transform pulse_effect(delay=0.5):
    alpha 0.0
    linear delay alpha 1.0
    pause delay
    repeat

label start:
    show sayori 1a at pulse_effect(0.2) with dissolve
    return