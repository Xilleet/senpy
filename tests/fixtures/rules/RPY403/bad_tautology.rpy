default x = True

label start:
    if x or not x:
        "This always executes — tautology."
    if "non-empty":
        "This always executes — non-empty string is truthy."
    return
