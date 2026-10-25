default raw_data = [1, 2, 3, 4, 5]
default filtered = []
default grid = {}

label start:
    python:
        # x и y живут только внутри генератора и не должны вызывать RPY104
        filtered = [y for x in raw_data if (y := x * 2) > 4]
        grid = {x: {y: x * y for y in range(3)} for x in range(3)}

    if len(filtered) > 0:
        "Processed [filtered]"
    return