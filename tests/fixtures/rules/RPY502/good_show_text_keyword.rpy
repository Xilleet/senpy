# `show text "string" with dissolve` is valid Ren'Py syntax — `text` is a
# keyword that creates a text displayable, not an image name. RPY502 must
# NOT fire on `show text "..."` (CORPUS-6 fix: _extract_show_image_tokens
# returns None when img_tokens[0] == "text", symmetric with the existing
# "layer" keyword guard).
# Pattern from aqua_guardians/game/script.rpy (line 19).
label start:
    show text "NeuroWarriors presents AquaGuardians" with dissolve
    with Pause(2.0)
    hide text with dissolve
    return
