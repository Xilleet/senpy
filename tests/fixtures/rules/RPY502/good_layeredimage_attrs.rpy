layeredimage august:
    always "august_base"
    group outfit:
        attribute casual default
        attribute coat
    group face:
        attribute happy
        attribute angry

label start:
    show august happy coat
    show august coat happy
    show august -coat casual
    return