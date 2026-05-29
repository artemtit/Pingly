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


async def main() -> None:
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    config.BOT_USERNAME = me.username

    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(tutor.router)
    dp.include_router(student.router)

    scheduler = create_scheduler(bot)
    scheduler.start()

    if config.WEB_ENABLED:
        asyncio.create_task(start_web())

    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
