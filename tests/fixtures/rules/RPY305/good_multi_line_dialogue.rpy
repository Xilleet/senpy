# Multi-line dialogue: Ren'Py supports strings spanning multiple physical
# lines. The opening " is on one line, closing " is on a later line.
# RPY305 must NOT fire on multi-line dialogue strings (CORPUS-6 fix:
# DialogueChecker tracks _in_multiline_dialogue state — a line with odd
# " count toggles the state, and while inside, RPY305 is skipped).
# Pattern from aqua_guardians/game/red_route.rpy (lines 29-33).
label start:
    e "He plans to
    implement sustainable practices and efficient crop
    rotation, aiming to conserve water resources. "
    e "However, he is confused about which method
    is most appropriate. Can you suggest one for him?"
    return
