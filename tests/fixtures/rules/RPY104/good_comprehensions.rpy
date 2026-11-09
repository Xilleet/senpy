default my_list = []
default my_dict = {}
default a = 0
default b = 0

label start:
    python:
        # Переменные 'x', 'k', 'v' существуют только локально внутри генераторов
        my_list = [x * 2 for x in range(10) if x % 2 == 0]
        my_dict = {k: v for k, v in enumerate(my_list)}
        
        # Кортежное присваивание
        a, b = (1, 2)
    return