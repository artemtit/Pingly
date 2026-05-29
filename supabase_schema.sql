-- Запусти этот SQL в Supabase: Dashboard → SQL Editor → New query
-- Для нового веб-кабинета и единой бизнес-логики также запусти:
-- migrations/001_product_platform.sql
-- migrations/002_server_runtime_policies.sql

create table tutors (
  tg_id bigint primary key,
  name  text not null,
  created_at timestamptz default now()
);

create table students (
  id           uuid primary key default gen_random_uuid(),
  tutor_id     bigint not null references tutors(tg_id) on delete cascade,
  name         text not null,
  tg_username  text not null,
  tg_id        bigint
);

create table lessons (
  id           uuid primary key default gen_random_uuid(),
  student_id   uuid not null references students(id) on delete cascade,
  day_of_week  int  not null check (day_of_week between 0 and 6),
  lesson_time  time not null,
  is_active    boolean default true
);

create table reminders (
  id             uuid primary key default gen_random_uuid(),
  lesson_id      uuid not null references lessons(id) on delete cascade,
  scheduled_for  timestamptz not null,
  status         text not null default 'sent'
);
