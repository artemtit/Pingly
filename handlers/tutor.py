from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import db

router = Router()

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class AddStudent(StatesGroup):
    waiting_name = State()
    waiting_username = State()


class AddLesson(StatesGroup):
    waiting_student = State()
    waiting_day = State()
    waiting_time = State()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    tutor = await db.get_tutor(message.from_user.id)
    if not tutor:
        await db.create_tutor(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я помогаю автоматически напоминать ученикам о занятиях.\n\n"
        "Команды:\n"
        "/add_student — добавить ученика\n"
        "/schedule — добавить расписание\n"
        "/my_students — мои ученики"
    )


@router.message(Command("add_student"))
async def cmd_add_student(message: Message, state: FSMContext) -> None:
    await state.set_state(AddStudent.waiting_name)
    await message.answer("Как зовут ученика?")


@router.message(AddStudent.waiting_name)
async def add_student_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddStudent.waiting_username)
    await message.answer(
        "Отлично! Теперь введи его Telegram-юзернейм (без @).\n\n"
        "Попроси ученика написать боту /start — тогда напоминания дойдут."
    )


@router.message(AddStudent.waiting_username)
async def add_student_username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = message.text.strip().lstrip("@")
    await db.create_student(message.from_user.id, data["name"], username)
    await state.clear()
    await message.answer(
        f"✅ Ученик {data['name']} (@{username}) добавлен!\n\n"
        "Теперь добавь расписание: /schedule"
    )


@router.message(Command("my_students"))
async def cmd_my_students(message: Message) -> None:
    students = await db.get_students(message.from_user.id)
    if not students:
        await message.answer("У тебя пока нет учеников. Добавь первого: /add_student")
        return

    lines = []
    for s in students:
        lessons = await db.get_lessons(s["id"])
        schedule = ", ".join(
            f"{DAYS[l['day_of_week']]} {l['lesson_time'][:5]}" for l in lessons
        ) or "расписание не добавлено"
        lines.append(f"• {s['name']} (@{s['tg_username']}) — {schedule}")

    await message.answer("Твои ученики:\n\n" + "\n".join(lines))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, state: FSMContext) -> None:
    students = await db.get_students(message.from_user.id)
    if not students:
        await message.answer("Сначала добавь ученика: /add_student")
        return

    buttons = [
        [InlineKeyboardButton(text=s["name"], callback_data=f"sel_student:{s['id']}")]
        for s in students
    ]
    await state.set_state(AddLesson.waiting_student)
    await message.answer("Выбери ученика:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(AddLesson.waiting_student, F.data.startswith("sel_student:"))
async def lesson_select_student(callback: CallbackQuery, state: FSMContext) -> None:
    student_id = callback.data.split(":")[1]
    await state.update_data(student_id=student_id)
    await state.set_state(AddLesson.waiting_day)

    buttons = [
        [InlineKeyboardButton(text=day, callback_data=f"sel_day:{i}")]
        for i, day in enumerate(DAYS)
    ]
    await callback.message.edit_text("Выбери день занятия:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(AddLesson.waiting_day, F.data.startswith("sel_day:"))
async def lesson_select_day(callback: CallbackQuery, state: FSMContext) -> None:
    day = int(callback.data.split(":")[1])
    await state.update_data(day=day)
    await state.set_state(AddLesson.waiting_time)
    await callback.message.edit_text("Введи время занятия в формате ЧЧ:ММ (например, 15:00):")


@router.message(AddLesson.waiting_time)
async def lesson_set_time(message: Message, state: FSMContext) -> None:
    time_str = message.text.strip()
    try:
        hours, minutes = map(int, time_str.split(":"))
        assert 0 <= hours <= 23 and 0 <= minutes <= 59
    except Exception:
        await message.answer("Неверный формат. Введи время в виде ЧЧ:ММ, например 15:00")
        return

    data = await state.get_data()
    await db.create_lesson(data["student_id"], data["day"], f"{hours:02d}:{minutes:02d}:00")
    await state.clear()

    student = await db.get_student(data["student_id"])
    await message.answer(
        f"✅ Занятие добавлено: {student['name']} — {DAYS[data['day']]} в {hours:02d}:{minutes:02d}\n\n"
        "Бот будет напоминать ученику за 2 часа до занятия."
    )
