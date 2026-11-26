# `CurrentScreenName()` and `GamepadExists()` are function CALLS (parens),
# not variable accesses. RPY202 must NOT fire on `if X():` — the callee
# Name in a Call expression is a function call, not an undeclared variable
# access (CORPUS-6 fix: collect id() of Call.func Name nodes and skip
# them in _check_undeclared_vars_in_condition).
# Both are documented Ren'Py built-in screen functions:
#   - CurrentScreenName() returns the name of the currently-showing screen
#   - GamepadExists() returns True if a gamepad is connected
# Pattern from aqua_guardians/game/screens.rpy (lines 462, 683).
screen file_slots(title):
    if CurrentScreenName() == "save":
        pass
    if GamepadExists():
        pass
