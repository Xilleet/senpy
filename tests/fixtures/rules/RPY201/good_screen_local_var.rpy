# `$ X = ...` inside a screen block to a non-declared name creates a
# screen-local variable, NOT a store mutation. Ren'Py screen language
# has its own scope. RPY201 must NOT fire on this pattern (CORPUS-6 fix:
# plain Assign to non-global is a screen-local declaration; only
# AugAssign like `$ X -= 1` is a real mutation).
# Pattern from aqua_guardians/game/screens.rpy (history screen, line 633).
screen history():
    $ what = renpy.filter_text_tags(h.what, allow=gui.history_allow_tags)
