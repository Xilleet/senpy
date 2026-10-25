default target_enemy = "Slime"

label battle(target_enemy, power=10):
    if target_enemy:
        "Атака!"
    return

label explore:
    # Корректно: есть глобальный default
    if target_enemy:
        "Враг найден!"
    return