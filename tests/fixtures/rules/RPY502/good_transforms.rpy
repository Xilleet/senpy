image sayori 1a = "sayori_1a.png"

transform custom_bounce:
    yoffset 0
    easein 0.2 yoffset -20
    easeout 0.2 yoffset 0

label start:
    show sayori 1a at center
    show sayori 1a at left, custom_bounce with dissolve
    show sayori at truecenter
    return