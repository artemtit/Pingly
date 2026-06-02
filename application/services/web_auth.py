from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from application.repositories import PinglyRepository
from infrastructure import email as email_client

_PBKDF2_ITERATIONS = 200_000
_TG_AUTH_MAX_AGE = 86400  # accept Telegram login payloads up to 24h old
_CODE_TTL_MINUTES = 15


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


class WebAuthService:
    def __init__(self, repo: PinglyRepository, base_url: str, bot_token: str = "") -> None:
        self.repo = repo
        self.base_url = base_url.rstrip("/")
        self.bot_token = bot_token

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    # ---------------- Telegram bot deep-link (existing /web flow) ----------------
    async def create_login_link_for_tg(self, tg_id: int) -> str | None:
        user = await self.repo.get_user_by_tg_id(tg_id)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        await self.repo.create_web_token(user["id"], self._hash(token), expires_at)
        return f"{self.base_url}/auth/telegram?token={token}"

    async def consume_login_token(self, token: str) -> dict | None:
        return await self.repo.consume_web_token(self._hash(token), datetime.now(timezone.utc))

    # ---------------- Email + password ----------------
    async def register_tutor_email(
        self, full_name: str, email: str, password: str, require_verification: bool = False,
    ) -> tuple[dict | None, str | None]:
        full_name = (full_name or "").strip()
        email = (email or "").strip().lower()
        if not full_name:
            return None, "Укажи имя"
        if "@" not in email or "." not in email.split("@")[-1]:
            return None, "Похоже, email введён неверно"
        if len(password) < 6:
            return None, "Пароль должен быть не короче 6 символов"
        existing = await self.repo.get_user_by_email(email)
        if existing:
            return None, "Аккаунт с таким email уже есть — войди"
        user = await self.repo.create_email_tutor(
            email, hash_password(password), full_name, email_verified=not require_verification,
        )
        return user, None

    async def login_email(self, email: str, password: str) -> dict | None:
        email = (email or "").strip().lower()
        user = await self.repo.get_user_by_email(email)
        if not user or not verify_password(password, user.get("password_hash")):
            return None
        return user

    # ---------------- Email verification codes ----------------
    async def send_verification_code(self, user: dict) -> tuple[bool, str | None]:
        """Generate, store and email a fresh 6-digit code. Returns (ok, error)."""
        email = (user or {}).get("email")
        if not email:
            return False, "У аккаунта нет email"
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)).isoformat()
        await self.repo.set_verification_code(user["id"], code, expires_at)
        try:
            await email_client.send_email(
                email, "Код подтверждения Pingly", email_client.verification_html(code),
            )
        except email_client.EmailError as exc:
            return False, str(exc)
        return True, None

    async def verify_email_code(self, email: str, code: str) -> tuple[dict | None, str | None]:
        """Check the code for an account and mark it verified. Returns (user, error)."""
        email = (email or "").strip().lower()
        code = (code or "").strip()
        user = await self.repo.get_user_by_email(email)
        if not user:
            return None, "Аккаунт не найден"
        if user.get("email_verified"):
            return user, None
        stored = user.get("verification_code")
        expires = user.get("verification_expires_at")
        if not stored or not code or not hmac.compare_digest(str(stored), code):
            return None, "Неверный код"
        if expires:
            try:
                if datetime.fromisoformat(str(expires).replace("Z", "+00:00")) < datetime.now(timezone.utc):
                    return None, "Код устарел — запроси новый"
            except ValueError:
                pass
        verified = await self.repo.mark_email_verified(user["id"])
        return verified or user, None

    async def resend_code(self, email: str) -> bool:
        """Re-send a code for an unverified account. No-op if already verified."""
        email = (email or "").strip().lower()
        user = await self.repo.get_user_by_email(email)
        if not user or user.get("email_verified"):
            return False
        ok, _ = await self.send_verification_code(user)
        return ok

    # ---------------- Telegram Login Widget ----------------
    def verify_telegram_widget(self, data: dict[str, str]) -> bool:
        received_hash = data.get("hash")
        if not received_hash or not self.bot_token:
            return False
        auth_date = data.get("auth_date")
        if auth_date and auth_date.isdigit():
            age = datetime.now(timezone.utc).timestamp() - int(auth_date)
            if age > _TG_AUTH_MAX_AGE:
                return False
        pairs = sorted(f"{k}={v}" for k, v in data.items() if k != "hash" and v is not None)
        data_check_string = "\n".join(pairs)
        secret_key = hashlib.sha256(self.bot_token.encode("utf-8")).digest()
        expected = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received_hash)

    async def link_telegram(self, user_id: str, data: dict[str, str]) -> tuple[bool, str | None]:
        """Attach a Telegram identity to an existing (e.g. email) account."""
        if not self.verify_telegram_widget(data):
            return False, "Не удалось проверить вход через Telegram"
        tg_id = data.get("id")
        if not tg_id or not str(tg_id).isdigit():
            return False, "Некорректные данные Telegram"
        tg_id = int(tg_id)
        existing = await self.repo.get_user_by_tg_id(tg_id)
        if existing and existing["id"] != user_id:
            return False, "Этот Telegram уже привязан к другому аккаунту Pingly"
        await self.repo.set_user_telegram(user_id, tg_id, data.get("username"))
        return True, None

    async def login_telegram_widget(self, data: dict[str, str]) -> dict | None:
        if not self.verify_telegram_widget(data):
            return None
        tg_id = data.get("id")
        if not tg_id or not str(tg_id).isdigit():
            return None
        full_name = " ".join(filter(None, [data.get("first_name"), data.get("last_name")])).strip() or "Репетитор"
        username = data.get("username")
        existing = await self.repo.get_user_by_tg_id(int(tg_id))
        if existing:
            return existing
        return await self.repo.upsert_tutor_user(int(tg_id), full_name, username)
