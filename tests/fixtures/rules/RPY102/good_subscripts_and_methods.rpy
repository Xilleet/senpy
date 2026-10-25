default valid_dict = {}
default valid_list = []
default valid_stats = {"hp": 100}

label start:
    $ valid_dict["key"] = 1
    $ valid_list.append("sword")
    $ valid_stats["hp"] += 10
    return