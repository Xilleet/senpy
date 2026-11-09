# RPY503 must NOT fire on assets referenced via Ren'Py's `[prefix_]`
# substitution pattern in style/foreground/background properties.
#
# Originally found as a false positive in:
#   corpus/renpy_template/game/gui/button/check_foreground.png
#   corpus/renpy_template/game/gui/button/choice_hover_background.png
#   (74 cases in renpy_template, similar in other projects)
#
# Pattern: a screen style block contains:
#   style check_button:
#       properties gui.button_properties("check_button")
#       foreground "gui/button/check_[prefix_]foreground.png"
#
# At runtime, Ren'Py substitutes `[prefix_]` with each of the standard
# prefixes ("", "idle_", "hover_", "selected_", "selected_hover_",
# "selected_idle_", "insensitive_", "selected_insensitive_") and loads
# the matching file. Senpy's _scan_python_assets detected the literal
# string "gui/button/check_[prefix_]foreground.png" but stored it
# verbatim — without expanding `[prefix_]` to the prefix list, the
# stored key didn't match any of the actual on-disk files
# (check_foreground.png, check_idle_foreground.png, etc.), so RPY503
# fired on every one of them.

style check_button:
    foreground "gui/button/check_[prefix_]foreground.png"

style choice_button:
    background "gui/button/choice_[prefix_]background.png"

label start:
    return
