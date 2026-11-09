default inventory_list = ["potion", "herb"]
default quest_dict = {"act1": True}

label start:
    $ inventory_list.append("sword")
    $ quest_dict["act2"] = True
    $ inventory_list.clear()
    return