init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)

label start:
    play ambient "rain.ogg"
    return
