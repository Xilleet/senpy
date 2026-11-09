image sayori 1a = "sayori_1a.png"
define custom_fade = Fade(0.5, 0.0, 0.5)

label start:
    show sayori 1a with dissolve
    with fade
    with None
    with custom_fade
    with Dissolve(1.0)
    "Диалог с переходом" with dissolve
    return