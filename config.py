import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
WEB_BASE_URL: str = os.getenv("WEB_BASE_URL", "http://localhost:8000")
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))
WEB_SECRET: str = os.getenv("WEB_SECRET", "dev-change-me")
WEB_ENABLED: bool = os.getenv("WEB_ENABLED", "1") == "1"

BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")  # also set at startup in bot.py from get_me()

# Telegram id that receives support messages from the web form (the founder).
SUPPORT_TG_ID: int = int(os.getenv("SUPPORT_TG_ID", "2091126912") or 0)
