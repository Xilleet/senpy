define INVENTORY_LIST = ["potion", "herb"]
define QUEST_DICT = {"act1": True}

label start:
    $ INVENTORY_LIST.append("sword")
    $ QUEST_DICT["act2"] = True
    $ INVENTORY_LIST.clear()
    return