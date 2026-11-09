label start:
    python:
        # Локальные переменные внутри def НЕ должны триггерить RPY104
        def compute_sum(items):
            total = 0
            for item in items:
                total += item
            return total
    return