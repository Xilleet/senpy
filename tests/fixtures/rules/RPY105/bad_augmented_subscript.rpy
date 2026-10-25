define PLAYER_STATS = {"hp": 100, "mana": 50}

label start:
    # Опасная мутация константы через += по ключу словаря
    $ PLAYER_STATS["hp"] += 20
    $ PLAYER_STATS["mana"] -= 10
    return