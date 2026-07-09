-- S6: per-user session generation counter. Baked into each session cookie; a
-- logout-all or password change increments it, instantly invalidating every older
-- cookie (which otherwise stays valid for the full 30-day SESSION_MAX_AGE).
alter table users add column if not exists token_version int not null default 0;
