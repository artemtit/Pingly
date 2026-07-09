-- F6: per-tutor timezone. Stored as a fixed UTC offset in minutes (Russia has no
-- DST, so a fixed offset is exact). Default 180 = Москва (UTC+3) — the previous
-- hardcoded behavior, so existing users are unaffected.
alter table users add column if not exists tz_offset_minutes int not null default 180;
