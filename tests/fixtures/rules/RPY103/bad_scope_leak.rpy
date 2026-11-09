label battle(target_enemy, power=10):
    if target_enemy:
        "Атака!"
    return

label explore:
    # Ошибка: target_enemy объявлен локально только в battle, здесь будет NameError
    if target_enemy:
        "Враг найден!"
    return