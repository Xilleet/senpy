default player_name = "Eileen"
default score = 100

label start:
    # Ошибка 1: str += int -> фатальный TypeError во время игры
    $ player_name += 1
    
    # Ошибка 2: перезапись int строкой -> Type Taint (ломает откат назад)
    $ score = "MAX"
    return