label target_with_params(a, b, c=1):
    return

label start:
    call target_with_params(1, 2)
    call target_with_params(1, 2, 3)
    call target_with_params(1, 2, c=10)
    return