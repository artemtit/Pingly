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
# This is the *delivery* target — stays as the founder so messages still reach Артём.
SUPPORT_TG_ID: int = int(os.getenv("SUPPORT_TG_ID", "2091126912") or 0)
# Public support contacts shown to users (and to the payment provider's review).
# Telegram stays the founder's personal @ligr5; email is the project mailbox
# (Cloudflare Email Routing → forwards to the founder, replies via Resend SMTP).
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "ligr5").lstrip("@")
SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "support@pingly-app.ru")

# Platega payments (subscriptions). Secrets live in .env, never in git.
PLATEGA_API_URL: str = os.getenv("PLATEGA_API_URL", "https://app.platega.io")
PLATEGA_MERCHANT_ID: str = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET: str = os.getenv("PLATEGA_SECRET", "")
# Payment method id: 2=SBP_QR, 10=CARDS_RUB, 11=CARD_ACQUIRING, 12=INTL, 13=CRYPTO
PLATEGA_PAYMENT_METHOD: int = int(os.getenv("PLATEGA_PAYMENT_METHOD", "11") or 11)
SUBSCRIPTION_PRICE_RUB: int = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "990") or 990)
# Yearly plan — paid once for 365 days. Default 9900 ₽ ≈ 10 months' worth, i.e.
# two months free vs paying monthly (990×12 = 11880).
SUBSCRIPTION_PRICE_YEAR_RUB: int = int(os.getenv("SUBSCRIPTION_PRICE_YEAR_RUB", "9900") or 9900)
# Master switch for taking payments. Off until the bank approves the payment
# provider — all billing infrastructure stays in place, only the entry point
# (subscribe button + route) is gated. Flip PAYMENTS_ENABLED=1 in .env to turn on.
PAYMENTS_ENABLED: bool = os.getenv("PAYMENTS_ENABLED", "0") == "1"

# Two subscription tiers: Pro (essentials) and Max (+ Задания, Финансы, Заявки).
# Dormant until PLANS_ENABLED=1: with it off, every account behaves as Max and
# nothing is locked. Turn on together with PAYMENTS_ENABLED when billing is live.
PLANS_ENABLED: bool = os.getenv("PLANS_ENABLED", "0") == "1"
PRICE_PRO_RUB: int = int(os.getenv("PRICE_PRO_RUB", "590") or 590)
PRICE_MAX_RUB: int = int(os.getenv("PRICE_MAX_RUB", "990") or 990)
# Sections available only on the Max tier (route keys / nav `active` ids).
MAX_ONLY_SECTIONS: frozenset = frozenset({"homework", "finance", "requests"})

# Email confirmation on registration (codes sent via Resend). Off until the
# Resend API key + verified sender are configured. Flip to 1 to require codes.
EMAIL_VERIFICATION_ENABLED: bool = os.getenv("EMAIL_VERIFICATION_ENABLED", "0") == "1"
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM: str = os.getenv("RESEND_FROM", "Pingly <onboarding@resend.dev>")

# Cloudflare Turnstile CAPTCHA on registration. Off until site/secret keys are set.
CAPTCHA_ENABLED: bool = os.getenv("CAPTCHA_ENABLED", "0") == "1"
TURNSTILE_SITE_KEY: str = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY: str = os.getenv("TURNSTILE_SECRET_KEY", "")

# VK (VKontakte) — second delivery channel alongside Telegram (per-student).
# Off until the community token is set. VK_GROUP_ID is auto-resolved from the
# token at startup (groups.getById), like BOT_USERNAME for Telegram.
VK_ENABLED: bool = os.getenv("VK_ENABLED", "0") == "1"
VK_TOKEN: str = os.getenv("VK_TOKEN", "")
VK_GROUP_ID: int = int(os.getenv("VK_GROUP_ID", "0") or 0)  # filled at startup if 0
# VK ID login for tutors (Фаза 2 — OAuth app, separate from the community bot).
VK_APP_ID: str = os.getenv("VK_APP_ID", "")
VK_APP_SECRET: str = os.getenv("VK_APP_SECRET", "")
