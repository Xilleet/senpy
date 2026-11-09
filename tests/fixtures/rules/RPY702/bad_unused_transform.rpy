transform slide_in:
    easein 0.5 xoffset 0

transform unused_transform:
    easeout 0.3 alpha 0.0

label start:
    show bg room at slide_in
    return
