-- 008_lesson_packages.sql
-- Lesson packages (абонементы). A student can have a prepaid package of N lessons;
-- Pingly counts consumed lessons and alerts the tutor + student when it runs low.
-- Remaining is COMPUTED (package_size - consumed lessons since package_started_at),
-- not stored, so it can't drift or double-decrement.
-- Safe to run multiple times.

alter table student_profiles add column if not exists package_size integer;          -- null = no package (pay per lesson)
alter table student_profiles add column if not exists package_started_at timestamptz; -- start of the current cycle; reset on renew
