# RPY102 must NOT fire on a variable assigned earlier in the SAME branch,
# even if that branch is conditional (inside `if`/`for`/`while`/`try`).
#
# Originally found as a false positive in:
#   corpus/renpy_template/game/scripts/definitions.rpy:55, 85
#
# Pattern: `args = []` is declared inside an `if` body. Then `args.extend(...)`
# is called inside a `for` loop that is ALSO inside the same `if` body. Both
# statements execute in the same branch — if the `if` runs, `args = []` runs
# BEFORE `args.extend()`. The state checker previously treated `args` as
# MAYBE_SET globally and fired RPY102 on the method call, missing that
# within a single branch, sequencing is deterministic.

init python:
    for file in []:
        if file.startswith('images/'):
            args = []
            for time in ['DAY', 'NIGHT']:
                args.extend(['time_of_day == ' + time, 'image ' + time])

init python:
    if True:
        data = {}
        for k in ['a', 'b']:
            data[k] = k.upper()
            data.update({'extra': 1})

init python:
    while False:
        buf = []
        buf.append(1)
