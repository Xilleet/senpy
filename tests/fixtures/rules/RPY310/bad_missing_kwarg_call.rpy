label quest(item, count=1):
    return

label start:
    # Ошибка: передан count=5, но обязательный аргумент 'item' отсутствует!
    call quest(count=5)
    return