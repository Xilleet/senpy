init python:
    class Hero:
        def get_title(self, bold=False):
            return "Champion"

default hero = Hero()

label start:
    # Базовый объект hero объявлен, вызов метода легален
    "Welcome, [hero.get_title(bold=True)]! Your journey begins."
    return