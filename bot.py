import asyncio
import config
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from handlers import tutor, student
from scheduler import create_scheduler
import db
from web.app import create_app


async def start_web() -> None:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_level="info",
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
