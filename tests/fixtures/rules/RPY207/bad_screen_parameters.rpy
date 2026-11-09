screen target_screen(item, count=1):
    text "[item]"

label start:
    use target_screen()                        # Ошибка: пропущен обязательный параметр 'item'
    use target_screen("sword", bad_param=True) # Ошибка: неизвестный параметр 'bad_param'
    return