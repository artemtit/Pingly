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
# Public support contacts shown to users (and to the payment provider's review).
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "ligr5").lstrip("@")
SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "at147824@gmail.com")

# Platega payments (subscriptions). Secrets live in .env, never in git.
PLATEGA_API_URL: str = os.getenv("PLATEGA_API_URL", "https://app.platega.io")
PLATEGA_MERCHANT_ID: str = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET: str = os.getenv("PLATEGA_SECRET", "")
# Payment method id: 2=SBP_QR, 10=CARDS_RUB, 11=CARD_ACQUIRING, 12=INTL, 13=CRYPTO
PLATEGA_PAYMENT_METHOD: int = int(os.getenv("PLATEGA_PAYMENT_METHOD", "11") or 11)
SUBSCRIPTION_PRICE_RUB: int = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "990") or 990)
# Master switch for taking payments. Off until the bank approves the payment
# provider — all billing infrastructure stays in place, only the entry point
# (subscribe button + route) is gated. Flip PAYMENTS_ENABLED=1 in .env to turn on.
PAYMENTS_ENABLED: bool = os.getenv("PAYMENTS_ENABLED", "0") == "1"
