-- F2: make silent Telegram delivery failures visible.
-- When a reminder send raises Forbidden (the user blocked the bot / deactivated),
-- we stamp tg_blocked_at on that user; the next successful delivery clears it.
-- The tutor sees a "напоминания не доходят" banner on the student's card.
alter table users add column if not exists tg_blocked_at timestamptz;
