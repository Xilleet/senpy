default quick_time_active = True
default qte_score = 0

screen qte_event():
    timer 3.0:
        action [SetVariable("quick_time_active", False), Return()]

    textbutton "SMASH!":
        sensitive quick_time_active
        action [SetVariable("qte_score", qte_score + 1), Return()]

label start:
    call screen qte_event
    return