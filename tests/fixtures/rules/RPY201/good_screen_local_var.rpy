# `$ X = ...` inside a screen block creates a screen-local variable,
# NOT a store mutation. Ren'Py screen language has its own scope.
# RPY201 currently fires treating it as state mutation — FP.
# Pattern from aqua_guardians/game/screens.rpy (history screen, line 633).
#
# When fixed, RPY201 should NOT fire on `$ local_var = ...` inside screens.
screen history():
    $ what = renpy.filter_text_tags(h.what, allow=gui.history_allow_tags)
