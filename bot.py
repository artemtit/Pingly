import asyncio
import config
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config import BOT_TOKEN
from handlers import tutor, student
from scheduler import create_scheduler
import db
from web.app import create_app


# Commands shown in the Telegram "menu" button. Kept minimal on purpose — the
# bot is a thin служебный layer (see CLAUDE.md), all real work is on the site.
BOT_COMMANDS = [
    BotCommand(command="start", description="Запустить бота / войти"),
    BotCommand(command="web", description="Ссылка в кабинет (репетитор)"),
    BotCommand(command="help", description="Помощь, документы, поддержка"),
]


async def register_commands(bot: Bot) -> None:
    """Publish the command menu. Non-critical (like get_me): a transient Telegram
    timeout on startup must not crash the process, so swallow and carry on."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 — network hiccup shouldn't take the bot down
        print(f"[startup] set_my_commands failed: {exc}")


async def start_web() -> None:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_level="info",
            # S7: trust the X-Forwarded-* set by our local nginx so request.client
            # reflects the real client, not 127.0.0.1. (Rate-limiting additionally
            # prefers Cloudflare's CF-Connecting-IP — see web.app._client_ip.)
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    )
    await server.serve()


async def resolve_username(bot: Bot, attempts: int = 5) -> None:
    """Fetch the bot username, retrying on transient Telegram timeouts.

    Telegram/Cloudflare occasionally time out the very first request after a
    restart. Previously that exception bubbled out of main() and killed the whole
    process — taking the web server down with it and serving a 502 until systemd
    restarted us. Now we retry with backoff and, if Telegram is still unreachable,
    carry on with an empty username: the web cabinet stays up and polling keeps
    retrying on its own. The username is non-critical (only the TG login widget)."""
    for i in range(attempts):
        try:
            me = await bot.get_me()
            config.BOT_USERNAME = me.username
            return
        except Exception as exc:  # noqa: BLE001 — any network error should retry, not crash
            print(f"[startup] get_me failed ({i + 1}/{attempts}): {exc}")
            if i < attempts - 1:
                await asyncio.sleep(3 * (i + 1))
    print("[startup] proceeding without bot username — web stays up, polling will retry")


async def main() -> None:
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)

    # Bring the web cabinet up first so a slow Telegram handshake can't cause a 502.
    if config.WEB_ENABLED:
        asyncio.create_task(start_web())

    await resolve_username(bot)
    await register_commands(bot)

    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(tutor.router)
    dp.include_router(student.router)

    # VK is a parallel delivery channel (per-student). Off unless VK_ENABLED +
    # token are set; when on, it runs its own Long Poll loop alongside Telegram.
    vk = None
    if config.VK_ENABLED and config.VK_TOKEN:
        from vk_bot import VkBot
        vk = VkBot(config.VK_TOKEN, tg_bot=bot)
        try:
            await vk.resolve_group_id()
            asyncio.create_task(vk.run())
        except Exception as exc:
            print(f"[vk] failed to start: {exc}")
            vk = None

    scheduler = create_scheduler(bot, vk)
    scheduler.start()

    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
