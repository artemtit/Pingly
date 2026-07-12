-- Админка: блокировка аккаунта. Заблокированный пользователь не может войти в
-- кабинет (current_user отдаёт 401), а bump token_version гасит активные сессии.
alter table users add column if not exists is_blocked boolean not null default false;
