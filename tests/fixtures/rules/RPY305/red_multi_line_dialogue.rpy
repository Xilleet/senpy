# Multi-line dialogue: Ren'Py supports strings spanning multiple physical
# lines. The opening " is on one line, closing " is on a later line.
# RPY305 currently fires on each line containing a " — FP.
# Pattern from aqua_guardians/game/red_route.rpy (lines 29-33).
#
# When fixed, RPY305 should NOT fire on multi-line dialogue strings.
label start:
    e "He plans to
    implement sustainable practices and efficient crop
    rotation, aiming to conserve water resources. "
    e "However, he is confused about which method
    is most appropriate. Can you suggest one for him?"
    return
