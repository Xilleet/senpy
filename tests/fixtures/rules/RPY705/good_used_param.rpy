screen shop(currency, gold):
    text "Currency: [currency], Gold: [gold]"

label start:
    call screen shop(currency="gold", gold=100)
    return
