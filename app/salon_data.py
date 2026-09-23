"""Структурированные данные салона «Стрижка» для записи и кнопок.

Текстовая инструкция / FAQ — в knowledge_base/salon_strijka.txt (RAG).
Здесь — то, что нужно коду: услуги с длительностью, часы, контакты.
"""

SALON_NAME = "Стрижка"
SALON_ADDRESS = "м. Київ, вул. Прикладна, буд. 1"
SALON_PHONE = "+38 (044) 123-45-67"

OPEN_HOUR = 10
CLOSE_HOUR = 20
LUNCH_START_HOUR = 13
LUNCH_END_HOUR = 14
SLOT_STEP_MINUTES = 30

# ключ -> (название, ціна грн, тривалість хв)
SERVICES = {
    "male_haircut": ("Чоловіча стрижка", 500, 60),
    "female_haircut": ("Жіноча стрижка", 800, 90),
    "child_haircut": ("Дитяча стрижка", 400, 45),
    "beard": ("Моделювання бороди", 350, 30),
    "coloring": ("Фарбування", 1500, 120),
    "styling": ("Укладання", 600, 60),
}


def services_text() -> str:
    lines = []
    for _, (name, price, minutes) in SERVICES.items():
        lines.append(f"- {name}: {price} грн, ~{minutes} хв")
    return "\n".join(lines)


def hours_text() -> str:
    return (
        f"Ми працюємо щодня з {OPEN_HOUR:02d}:00 до {CLOSE_HOUR:02d}:00.\n"
        f"Перерва: з {LUNCH_START_HOUR:02d}:00 до {LUNCH_END_HOUR:02d}:00."
    )


def contacts_text() -> str:
    return (
        f"Салон «{SALON_NAME}»\n"
        f"Адреса: {SALON_ADDRESS}\n"
        f"Телефон: {SALON_PHONE}"
    )


def find_service(query: str):
    """Ищет услугу по названию. Возвращает (name, price, minutes) или None."""
    q = query.strip().lower()
    for _, (name, price, minutes) in SERVICES.items():
        if q == name.lower() or q in name.lower() or name.lower() in q:
            return name, price, minutes
    return None
