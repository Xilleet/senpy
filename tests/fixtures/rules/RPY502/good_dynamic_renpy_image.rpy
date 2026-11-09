# RPY502 must NOT fire on images registered via `renpy.image()` in init python.
#
# Originally found as a false positive in:
#   corpus/learntocode/game/scripts/definitions.rpy:44-56 (88 cases)
#
# Pattern: an `init python:` block dynamically registers images via
# `renpy.image(name, ...)` calls. After the block runs, the registered
# image names are valid for `show`/`scene` statements. Senpy's static
# analyzer cannot run the Python code, so it doesn't see the
# registration and fires RPY502 ("image not found") on every reference.
#
# This fixture covers the cases the static evaluator can handle:
#   - Plain string literal: `renpy.image("bg_static", ...)`
#   - Loop variable from literal iterable: `for x in ["a", "b"]: renpy.image(x, ...)`
#   - String concatenation with loop variable: `renpy.image(x + " night", ...)`
#
# Cases that remain a known limitation (not covered):
#   - Loop iterables that are not list literals (e.g. `os.listdir()`)
#   - f-strings with non-literal interpolation
#   - Function call results as the name argument
#
# Users can `# noqa: RPY502` for those cases.

init python:
    # Plain literal — always statically resolvable.
    renpy.image("bg_static", "images/bg_static.png")

    # Loop variable from list literal iterable.
    for fname in ["bg_room", "bg_kitchen"]:
        renpy.image(fname, fname + ".png")
        renpy.image(fname + " night", fname + "_night.png")

label start:
    # All of these are valid — registered dynamically above.
    scene bg_static
    scene bg_room
    scene bg_room night
    scene bg_kitchen
    scene bg_kitchen night
    "Done."
    return
