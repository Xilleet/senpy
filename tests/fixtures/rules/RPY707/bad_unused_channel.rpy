init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)
    renpy.music.register_channel("bgm_menu", mixer="music", loop=True)

label start:
    "No audio played on either channel."
    return
