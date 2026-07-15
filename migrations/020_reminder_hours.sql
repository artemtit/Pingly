-- 020_reminder_hours.sql
-- Настраиваемое время напоминания ученику до занятия (было жёстко "2 часа").
-- Дефолт 2 сохраняет прежнее поведение для всех существующих репетиторов.
alter table users add column if not exists reminder_hours smallint not null default 2;
