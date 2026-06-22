-- Referral bonus is now paid out only when the referred tutor first subscribes
-- (kills the "register a fake account through my own link" abuse). This column
-- is the idempotency gate so the +30-day reward is granted exactly once.
alter table users add column if not exists referral_rewarded_at timestamptz;
