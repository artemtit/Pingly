-- F10: opt-in "тихие часы". When on, non-urgent notifications that come due
-- during the night (22:00–08:00 MSK) are deferred to 08:00 MSK instead of
-- pinging the user. Time-critical lesson reminders are never deferred.
alter table users add column if not exists notify_quiet_hours boolean not null default false;
