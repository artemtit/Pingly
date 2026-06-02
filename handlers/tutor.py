from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardRemove,
)

import config
from application.factory import create_services

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
WEB_URL = "https://pingly-app.ru"


def _legal_keyboard() -> InlineKeyboardMarkup:
    """Permanent-access buttons to the legal docs and support (payment review needs these)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Политика конфиденциальности", url=f"{WEB_URL}/privacy")],
        [InlineKeyboardButton(text="📑 Пользовательское соглашение", url=f"{WEB_URL}/terms")],
        [InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{config.SUPPORT_USERNAME}")],
    ])

router = Router()
services = create_services()


def _username(message: Message) -> str | None:
    return message.from_user.username if message.from_user else None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    uid = message.from_user.id

    # Student joins via invite link: t.me/<bot>?start=inv_<token>
    if command.args and command.args.startswith("inv_"):
        existing = await services.accounts.get_by_tg_id(uid)
        if existing:
            await message.answer(
                "С возвращением! 👋 Напоминания о занятиях я пришлю сюда.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        student = await services.students.link_student_from_invite(
            command.args[4:], uid, message.from_user.full_name, _username(message),
        )
        if student:
            await message.answer(
                "Привет! 👋\n\n"
                "Перед каждым занятием я пришлю напоминание — нажми «✅ Буду» или «❌ Отменяю».\n\n"
                "Больше ничего делать не нужно. 🙂",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await message.answer("Ссылка недействительна. Попроси репетитора прислать новую.")
        return

    user = await services.accounts.get_by_tg_id(uid)

    if user and user["role"] == "student":
        await message.answer(
            "С возвращением! 👋 Напоминания о занятиях придут сюда.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if user and user["role"] == "tutor":
        link = await services.web_auth.create_login_link_for_tg(uid)
        await message.answer(
            "С возвращением! 👨‍🏫\n\n"
            "Вся работа — в веб-кабинете:\n"
            f"{link or WEB_URL}\n\n"
            "Сюда я буду присылать ответы учеников на напоминания.",
            reply_markup=ReplyKeyboardRemove(),
            link_preview_options=NO_PREVIEW,
        )
        return

    # Brand-new user, no account yet
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Pingly сам напоминает ученикам о занятиях, а ты видишь, кто придёт.\n\n"
        f"👨‍🏫 Репетитор? Зарегистрируйся на сайте: {WEB_URL}\n"
        "🎓 Ученик? Попроси репетитора прислать ссылку-приглашение — она придёт прямо сюда.\n\n"
        "📄 Документы и поддержка — команда /help.",
        reply_markup=ReplyKeyboardRemove(),
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ Pingly — сервис напоминаний о занятиях для репетиторов.\n\n"
        f"Поддержка: Telegram @{config.SUPPORT_USERNAME}, e-mail {config.SUPPORT_EMAIL}\n\n"
        "Документы и контакты — по кнопкам ниже:",
        reply_markup=_legal_keyboard(),
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("web"))
async def cmd_web(message: Message) -> None:
    link = await services.web_auth.create_login_link_for_tg(message.from_user.id)
    if not link:
        await message.answer(
            f"Сначала зарегистрируйся на сайте: {WEB_URL}",
            link_preview_options=NO_PREVIEW,
        )
        return
    await message.answer(
        f"🌐 Твой вход в кабинет:\n{link}\n\nСсылка действует 10 минут.",
        link_preview_options=NO_PREVIEW,
    )
