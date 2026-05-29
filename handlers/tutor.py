from __future__ import annotations

import config
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from application.factory import create_services
from handlers.keyboards import student_menu_keyboard, tutor_menu_keyboard

router = Router()
services = create_services()

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class AddStudent(StatesGroup):
    waiting_name = State()
    waiting_username = State()


class AddLesson(StatesGroup):
    waiting_student = State()
    waiting_day = State()
    waiting_time = State()


class AddHomework(StatesGroup):
    waiting_student = State()
    waiting_title = State()
    waiting_description = State()


def _username(message: Message) -> str | None:
    return message.from_user.username if message.from_user else None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    uid = message.from_user.id

    if command.args and command.args.startswith("inv_"):
        token = command.args[4:]
        student = await services.students.link_student_from_invite(
            token,
            uid,
            message.from_user.full_name,
            _username(message),
        )
        if student:
            await message.answer(
                "Привет! 👋\n\n"
                "Я буду напоминать тебе о занятиях, заданиях и изменениях расписания.\n"
                "Выбери действие на кнопках ниже. Команды тоже работают: /menu, /next_lesson, /my_homework, /progress, /web",
                reply_markup=student_menu_keyboard(),
            )
            return
        await message.answer("Ссылка недействительна. Попроси репетитора прислать новую.")
        return

    user = await services.accounts.get_by_tg_id(uid)
    if user and user["role"] == "student":
        await message.answer("Привет! Выбери действие на кнопках ниже.", reply_markup=student_menu_keyboard())
        return

    await services.students.ensure_tutor(uid, message.from_user.full_name, _username(message))
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Pingly теперь объединяет бот и веб-кабинет.\n\n"
        "Команды:\n"
        "/menu — быстрые действия\n"
        "/add_student — добавить ученика\n"
        "/schedule — добавить занятие\n"
        "/add_homework — выдать задание\n"
        "/my_students — мои ученики\n"
        "/calendar — календарь\n"
        "/web — открыть кабинет",
        reply_markup=tutor_menu_keyboard(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if user and user["role"] == "student":
        text = (
            "Меню ученика:\n\n"
            "/next_lesson — следующее занятие\n"
            "/my_homework — мои задания\n"
            "/progress — мой прогресс\n"
            "/web — открыть веб-кабинет"
        )
    else:
        text = (
            "Меню репетитора:\n\n"
            "/my_students — мои ученики\n"
            "/schedule — добавить занятие\n"
            "/add_homework — добавить задание\n"
            "/calendar — календарь\n"
            "/web — открыть веб-кабинет"
        )
    await message.answer(text, reply_markup=student_menu_keyboard() if user and user["role"] == "student" else tutor_menu_keyboard())


@router.message(F.text == "🌐 Веб-кабинет")
async def btn_web(message: Message) -> None:
    await cmd_web(message)


@router.message(F.text == "👥 Мои ученики")
async def btn_my_students(message: Message) -> None:
    await cmd_my_students(message)


@router.message(F.text == "➕ Добавить ученика")
async def btn_add_student(message: Message, state: FSMContext) -> None:
    await cmd_add_student(message, state)


@router.message(F.text == "➕ Добавить занятие")
async def btn_schedule(message: Message, state: FSMContext) -> None:
    await cmd_schedule(message, state)


@router.message(F.text == "📅 Календарь")
async def btn_calendar(message: Message) -> None:
    await cmd_calendar(message)


@router.message(F.text == "📝 Добавить задание")
async def btn_add_homework(message: Message, state: FSMContext) -> None:
    await cmd_add_homework(message, state)


@router.message(F.text == "📊 Аналитика")
async def btn_analytics(message: Message) -> None:
    await cmd_analytics(message)


@router.message(Command("web"))
async def cmd_web(message: Message) -> None:
    link = await services.web_auth.create_login_link_for_tg(message.from_user.id)
    if not link:
        await message.answer("Сначала нажми /start, чтобы я создал аккаунт.")
        return
    await message.answer(f"Веб-кабинет Pingly:\n{link}\n\nСсылка действует 10 минут.")


@router.message(Command("add_student"))
async def cmd_add_student(message: Message, state: FSMContext) -> None:
    await services.students.ensure_tutor(message.from_user.id, message.from_user.full_name, _username(message))
    await state.set_state(AddStudent.waiting_name)
    await message.answer("Как зовут ученика?")


@router.message(AddStudent.waiting_name)
async def add_student_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Введи имя ученика, минимум 2 символа.")
        return
    await state.update_data(name=name)
    await state.set_state(AddStudent.waiting_username)
    await message.answer("Введи Telegram-юзернейм ученика без @. Если юзернейма нет — введи любое слово.")


@router.message(AddStudent.waiting_username)
async def add_student_username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = (message.text or "").strip().lstrip("@")
    if not username:
        await message.answer("Юзернейм не может быть пустым.")
        return
    student = await services.students.create_student_invite(message.from_user.id, data["name"], username)
    await state.clear()

    invite_link = f"https://t.me/{config.BOT_USERNAME}?start=inv_{student['invite_token']}"
    await message.answer(
        f"✅ Ученик {data['name']} добавлен!\n\n"
        f"Отправь ему ссылку:\n{invite_link}\n\n"
        "После входа ученик увидит те же уроки и задания в боте и веб-кабинете."
    )


@router.message(Command("my_students"))
async def cmd_my_students(message: Message) -> None:
    students = await services.students.list_students(message.from_user.id)
    if not students:
        await message.answer("У тебя пока нет учеников. Добавь первого: /add_student")
        return
    lines = [f"• {s['name']} (@{s.get('tg_username') or 'без username'}) — {s.get('status', 'active')}" for s in students]
    await message.answer("Твои ученики:\n\n" + "\n".join(lines))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, state: FSMContext) -> None:
    students = await services.students.list_students(message.from_user.id)
    if not students:
        await message.answer("Сначала добавь ученика: /add_student")
        return
    buttons = [[InlineKeyboardButton(text=s["name"], callback_data=f"sel_student:{s['id']}")] for s in students]
    await state.set_state(AddLesson.waiting_student)
    await message.answer("Выбери ученика:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(AddLesson.waiting_student, F.data.startswith("sel_student:"))
async def lesson_select_student(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(student_id=callback.data.split(":")[1])
    await state.set_state(AddLesson.waiting_day)
    buttons = [[InlineKeyboardButton(text=day, callback_data=f"sel_day:{i}")] for i, day in enumerate(DAYS)]
    await callback.message.edit_text("Выбери день занятия:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(AddLesson.waiting_day, F.data.startswith("sel_day:"))
async def lesson_select_day(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(day=int(callback.data.split(":")[1]))
    await state.set_state(AddLesson.waiting_time)
    await callback.message.edit_text("Введи время занятия в формате ЧЧ:ММ, например 15:00:")


@router.message(AddLesson.waiting_time)
async def lesson_set_time(message: Message, state: FSMContext) -> None:
    time_str = (message.text or "").strip()
    try:
        hours, minutes = map(int, time_str.split(":"))
        assert 0 <= hours <= 23 and 0 <= minutes <= 59
    except Exception:
        await message.answer("Неверный формат. Введи время в виде ЧЧ:ММ, например 15:00")
        return

    data = await state.get_data()
    await services.lessons.create_recurring_lesson(
        message.from_user.id,
        data["student_id"],
        data["day"],
        f"{hours:02d}:{minutes:02d}:00",
    )
    await state.clear()
    await message.answer(
        f"✅ Повторяющееся занятие добавлено: {DAYS[data['day']]} в {hours:02d}:{minutes:02d}\n\n"
        "Я создал ближайшие уроки и буду отправлять уведомления."
    )


@router.message(Command("calendar"))
async def cmd_calendar(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажми /start.")
        return
    lessons = (
        await services.lessons.list_tutor_calendar(user["id"])
        if user["role"] == "tutor"
        else await services.lessons.list_student_calendar(user["id"])
    )
    if not lessons:
        await message.answer("В календаре пока нет занятий.")
        return
    lines = []
    for lesson in lessons[:10]:
        starts = lesson["starts_at"][:16].replace("T", " ")
        student = lesson.get("student_profiles") or {}
        lines.append(f"• {starts} — {student.get('name', 'занятие')} · {lesson['status']}")
    await message.answer("Ближайшие занятия:\n\n" + "\n".join(lines))


@router.message(Command("add_homework"))
async def cmd_add_homework(message: Message, state: FSMContext) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "tutor":
        await message.answer("Задания может выдавать только репетитор.")
        return
    students = await services.students.list_students(message.from_user.id)
    if not students:
        await message.answer("Сначала добавь ученика: /add_student")
        return
    buttons = [[InlineKeyboardButton(text=s["name"], callback_data=f"hw_student:{s['id']}")] for s in students]
    await state.set_state(AddHomework.waiting_student)
    await message.answer("Кому выдать задание?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(AddHomework.waiting_student, F.data.startswith("hw_student:"))
async def homework_select_student(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(student_id=callback.data.split(":")[1])
    await state.set_state(AddHomework.waiting_title)
    await callback.message.edit_text("Название задания:")


@router.message(AddHomework.waiting_title)
async def homework_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if len(title) < 3:
        await message.answer("Название слишком короткое.")
        return
    await state.update_data(title=title)
    await state.set_state(AddHomework.waiting_description)
    await message.answer("Описание задания. Если описания нет, напиши '-'.")


@router.message(AddHomework.waiting_description)
async def homework_description(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    description = (message.text or "").strip()
    await services.homework.create_homework(
        user["id"],
        data["student_id"],
        data["title"],
        None if description == "-" else description,
        None,
    )
    await state.clear()
    await message.answer("✅ Задание выдано. Ученик получит уведомление.")


@router.message(Command("analytics"))
async def cmd_analytics(message: Message) -> None:
    user = await services.accounts.get_by_tg_id(message.from_user.id)
    if not user or user["role"] != "tutor":
        await message.answer("Аналитика доступна репетитору.")
        return
    data = await services.analytics.tutor_dashboard(user["id"])
    await message.answer(
        "Аналитика:\n\n"
        f"Ученики: {data['students_count']}\n"
        f"Проведено занятий: {data['completed_lessons']}\n"
        f"Активные ДЗ: {data['active_homework']}\n"
        f"Выполнение ДЗ: {data['homework_completion_percent']}%\n"
        f"Посещаемость: {data['attendance_percent']}%"
    )
