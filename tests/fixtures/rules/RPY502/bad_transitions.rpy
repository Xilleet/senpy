image sayori 1a = "sayori_1a.png"
define custom_fade = Fade(0.5, 0.0, 0.5)

label start:
    show sayori 1a with disolve            # Опечатка в 'dissolve'
    with fdae                              # Опечатка в 'fade'
    with missing_transition                # Несуществующий переход
    show sayori with missing_wipe(0.5)     # Несуществующий переход с аргументами
    return