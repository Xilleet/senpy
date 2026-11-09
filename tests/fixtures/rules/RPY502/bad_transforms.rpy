image sayori 1a = "sayori_1a.png"

transform custom_bounce:
    yoffset 0
    easein 0.2 yoffset -20
    easeout 0.2 yoffset 0

label start:
    show sayori 1a at cneter                # Опечатка в 'center'
    show sayori at missing_transform        # Необъявленный трансформ
    show sayori at missing_anim(0.5)        # Необъявленный трансформ с аргументами
    return