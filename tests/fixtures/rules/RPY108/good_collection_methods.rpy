default inventory = ["potion"]
default quest_flags = {"started": True}
default player_name = "Eileen"

label start:
    $ inventory.append("shield")
    $ inventory.extend(["herb"])
    $ quest_flags.update({"act1": True})
    $ quest_flags.get("started")
    $ clean_name = player_name.upper()
    return