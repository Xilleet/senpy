label start:
    return

screen nav():
    textbutton "1" action Jump("strt")       # Опечатка в метке 'start'
    textbutton "2" action Call("btle")       # Несуществующая метка

label test_py:
    $ renpy.jump("edning")                   # Несуществующая метка
    $ renpy.call("chpter2")                  # Несуществующая метка
    return