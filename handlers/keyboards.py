from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def tutor_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Мои ученики"), KeyboardButton(text="➕ Добавить ученика")],
            [KeyboardButton(text="📅 Календарь"), KeyboardButton(text="➕ Добавить занятие")],
            [KeyboardButton(text="📝 Добавить задание"), KeyboardButton(text="📊 Аналитика")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🌐 Веб-кабинет")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def student_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Следующее занятие"), KeyboardButton(text="📝 Мои задания")],
            [KeyboardButton(text="📈 Мой прогресс"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🌐 Веб-кабинет")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )
