default player_name = "Eileen"
default score = 100

label start:
    # Корректно: конкатенация строк и сложение чисел
    $ player_name += " Doe"
    $ score += 50
    $ score = 200
    return