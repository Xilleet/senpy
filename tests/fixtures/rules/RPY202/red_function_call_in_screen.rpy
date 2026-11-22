# `CurrentScreenName()` and `GamepadExists()` are function CALLS (parens),
# not variable accesses. RPY202 treats them as undeclared variables — FP.
# Also: both are documented Ren'Py built-in screen functions.
#   - CurrentScreenName() returns the name of the currently-showing screen
#   - GamepadExists() returns True if a gamepad is connected
# Pattern from aqua_guardians/game/screens.rpy (lines 462, 683).
#
# When fixed, RPY202 should NOT fire on `if X():` where X is a function call.
screen file_slots(title):
    if CurrentScreenName() == "save":
        pass
    if GamepadExists():
        pass
