# RPY103 must NOT fire on screen parameters declared via `init <N> screen`.
#
# Originally found as a false positive in:
#   corpus/ddlc/ddlc-renpy-project/game/screens.rpy:443, 459, 468, 825
#   corpus/learntocode/game/code_snippet_example_screen.rpy:601+
#
# Ren'Py supports `init <priority> screen NAME(params):` as a way to
# control the init priority of a screen declaration. The screen's
# parameters are local to the screen body — same as for a bare
# `screen NAME(params):`. Senpy's RE_SCREEN_START regex did not match
# the `init <N> ` prefix, so no SCREEN scope was pushed and the
# parameters were not registered as local symbols. RPY103 then fired
# on every use of a parameter inside the body.

init -501 screen game_menu(title, scroll=None):
    if scroll == "viewport":
        pass
    elif scroll == "vpgrid":
        pass

init 100 screen other_screen(flag, mode="auto"):
    if flag and mode == "auto":
        pass

init screen no_priority(x):
    if x:
        pass
