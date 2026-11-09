screen target_screen(item, count=1):
    text "[item]"

label start:
    use target_screen("sword")
    use target_screen("potion", count=5)
    return