label start:
    $ target_label = "ending"
    jump expression target_label
    call expression target_label

    $ renpy.jump(target_label)
    $ renpy.call(target_label)
    $ renpy.jump("start")
    $ renpy.call("start")
    return

screen dynamic_nav(target):
    textbutton "Go" action Jump(target)
    textbutton "Do" action Call(target)