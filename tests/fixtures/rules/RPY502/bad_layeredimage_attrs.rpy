layeredimage august:
    always "august_base"
    group outfit:
        attribute casual default
        attribute coat
    group face:
        attribute happy

label start:
    # Ошибка: атрибута 'shocked' нет у august
    show august happy shocked
    return