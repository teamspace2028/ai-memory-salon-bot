"""Структурированные данные салона «Стрижка» для записи и кнопок.

Текстовая инструкция / FAQ — в knowledge_base/salon_strijka.txt (RAG).
Здесь — то, что нужно коду: услуги с длительностью, часы, контакты.
"""

SALON_NAME = "Стрижка"
SALON_ADDRESS = "г. Москва, ул. Примерная, д. 1"
SALON_PHONE = "+7 (900) 123-45-67"

OPEN_HOUR = 10
CLOSE_HOUR = 20
LUNCH_START_HOUR = 13
LUNCH_END_HOUR = 14
SLOT_STEP_MINUTES = 30

# ключ -> (название, цена ₽, длительность мин)
SERVICES = {
    "male_haircut": ("Мужская стрижка", 1200, 60),
    "female_haircut": ("Женская стрижка", 2000, 90),
    "child_haircut": ("Детская стрижка", 900, 45),
    "beard": ("Моделирование бороды", 800, 30),
    "coloring": ("Окрашивание", 3500, 120),
    "styling": ("Укладка", 1500, 60),
}


def services_text() -> str:
    lines = []
    for _, (name, price, minutes) in SERVICES.items():
        lines.append(f"- {name}: {price} ₽, ~{minutes} мин")
    return "\n".join(lines)


def hours_text() -> str:
    return (
        f"Мы работаем ежедневно с {OPEN_HOUR:02d}:00 до {CLOSE_HOUR:02d}:00.\n"
        f"Перерыв: с {LUNCH_START_HOUR:02d}:00 до {LUNCH_END_HOUR:02d}:00."
    )


def contacts_text() -> str:
    return (
        f"Салон «{SALON_NAME}»\n"
        f"Адрес: {SALON_ADDRESS}\n"
        f"Телефон: {SALON_PHONE}"
    )


def find_service(query: str):
    """Ищет услугу по названию. Возвращает (name, price, minutes) или None."""
    q = query.strip().lower()
    for _, (name, price, minutes) in SERVICES.items():
        if q == name.lower() or q in name.lower() or name.lower() in q:
            return name, price, minutes
    return None
