# `show text "string" with dissolve` is valid Ren'Py syntax — `text` is a
# keyword that creates a text displayable, not an image name.
# RPY502 currently fires thinking 'text' is an undefined image — FP.
# Pattern from aqua_guardians/game/script.rpy (line 19).
#
# When fixed, RPY502 should NOT fire on `show text "..."`.
label start:
    show text "NeuroWarriors presents AquaGuardians" with dissolve
    with Pause(2.0)
    hide text with dissolve
    return
