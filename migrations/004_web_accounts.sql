-- 004_web_accounts.sql
-- Web-first tutor accounts: allow registration by email/password,
-- in addition to the existing Telegram-based identity (tg_id).
-- Both columns are nullable: a user may have only tg_id, only email, or both.

alter table users add column if not exists email text;
alter table users add column if not exists password_hash text;

-- Case-insensitive uniqueness for email, ignoring NULLs.
create unique index if not exists users_email_unique
  on users (lower(email))
  where email is not null;
