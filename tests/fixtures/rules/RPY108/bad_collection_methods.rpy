default inventory = ["potion"]
default quest_flags = {"started": True}
default player_name = "Eileen"

label start:
    $ inventory.add("sword")          # Ошибка: у list нет .add(), нужен .append()
    $ quest_flags.append("finished")  # Ошибка: у dict нет .append(), нужен .update()
    $ player_name.pop()               # Ошибка: у str нет .pop()
    return