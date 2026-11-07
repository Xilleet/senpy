# RPY309 must NOT fire on labels reachable from `start` via fall-through.
#
# Originally found as a false positive in:
#   corpus/cross_channel/AllPlatforms/script.rpy:48 (gm_roop, 515 cases)
#
# Pattern: `start` falls through to `inner_label` (no `return` between
# them). `inner_label` jumps to other labels. All these labels ARE
# reachable from `start` via the implicit fall-through edge, but Senpy's
# StoryFlowAnalyzer previously modeled only explicit `jump`/`call`
# edges — missing the fall-through. RPY309 fired on every label reached
# only through the fall-through chain.

label start:
    $ roop = 0
    scene expression Solid("000")

label inner_label:
    if roop == 0:
        jump inner_label_2
    jump inner_label_end

label inner_label_2:
    $ roop = 1
    jump inner_label

label inner_label_end:
    return
