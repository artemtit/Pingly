-- Pingly v3: full platform.
-- Extends the student profile (CRM) and scheduling engine (recurrence).
-- Gamification (XP / levels / streaks / achievements) is computed at runtime
-- from real lessons + homework, so it needs no tables here.
-- Safe to run multiple times.

-- 1. Extended student profile (CRM fields)
alter table student_profiles add column if not exists grade text;
alter table student_profiles add column if not exists goal text;
alter table student_profiles add column if not exists started_at date;

-- 2. Full scheduling engine on schedule_rules.
-- recurrence: weekly | daily | multiple_weekly | every_n_days | every_n_weeks
-- weekdays:   jsonb array of weekday ints (0=Mon .. 6=Sun), used by weekly/multiple_weekly
-- interval_n: N for every_n_days / every_n_weeks
alter table schedule_rules add column if not exists recurrence text not null default 'weekly';
alter table schedule_rules add column if not exists interval_n int not null default 1;
alter table schedule_rules add column if not exists weekdays jsonb not null default '[]';
alter table schedule_rules add column if not exists start_date date;

-- Backfill weekdays for legacy single-day rules.
update schedule_rules
   set weekdays = to_jsonb(array[day_of_week])
 where (weekdays is null or weekdays = '[]'::jsonb);
