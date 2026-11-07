# RPY110 must NOT fire on valid multi-line triple-quoted strings.
#
# Originally found as a false positive in:
#   corpus/learntocode/game/scripts/splashscreen.rpy:61
#   (and 5 other projects, 1 case each)
#
# The `$` statement opens a triple-quoted string on one physical line
# and closes it on a later line. The string is valid Python — Senpy's
# parser was only feeding the first physical line to `ast.parse`,
# leaving the triple-quoted string unclosed → false RPY110.

label start:
    $ my_var = _p("""
        First line of multi-line string.
        Second line with {b}{u}Ren'Py text tags{/u}{/b}.
        Third line.
    """)
    "Done."
    return
