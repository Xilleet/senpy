label target_with_params(a, b, c=1):
    return

label start:
    call target_with_params("only_one_arg")       # Ошибка: не хватает обязательного 'b'
    call target_with_params(1, 2, 3, 4, 5)         # Ошибка: слишком много позиционных аргументов
    call target_with_params(1, 2, unknown_arg=9)   # Ошибка: неожиданный именованный аргумент
    return