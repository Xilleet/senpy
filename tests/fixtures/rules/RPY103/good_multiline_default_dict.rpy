default quest_tree = {
    "act1": [
        "meet_monika",
        "find_key",
    ],
    "completed": False,
}

label start:
    if quest_tree["completed"]:
        "Done!"
    return