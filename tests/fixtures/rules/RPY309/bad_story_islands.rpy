label start:
    "Основной сюжет"
    return

# Изолированный мёртвый остров:
label abandoned_island_a:
    "Черновик А"
    jump abandoned_island_b

label abandoned_island_b:
    "Черновик Б"
    jump abandoned_island_a