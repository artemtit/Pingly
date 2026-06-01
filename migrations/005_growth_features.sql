-- 005_growth_features.sql
-- Pingly growth features: payments, homework templates, public booking page,
-- 14-day trial, and referrals. Safe to run multiple times.

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Payments / finances
--    Price is stored per lesson (in whole roubles). `paid` is a simple flag
--    the tutor toggles. `default_price` on the student fills new lessons.
alter table lessons_v2 add column if not exists price integer;
alter table lessons_v2 add column if not exists paid boolean not null default false;
alter table lessons_v2 add column if not exists paid_at timestamptz;
alter table student_profiles add column if not exists default_price integer;

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Homework templates — reusable assignments the tutor saves once.
create table if not exists homework_templates (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  title text not null,
  description text,
  created_at timestamptz not null default now()
);
create index if not exists homework_templates_tutor on homework_templates(tutor_user_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Public profile + booking requests
--    Tutor gets a public page at /u/<slug>. Visitors leave booking requests
--    (leads) that show up in the tutor's cabinet.
alter table tutor_profiles add column if not exists slug text;
alter table tutor_profiles add column if not exists bio text;
alter table tutor_profiles add column if not exists subjects text;
alter table tutor_profiles add column if not exists public_enabled boolean not null default false;

-- Auto-generate a slug for tutors that don't have one yet.
update tutor_profiles
   set slug = 't' || substr(md5(random()::text), 1, 8)
 where slug is null;

create unique index if not exists tutor_profiles_slug_unique
  on tutor_profiles (lower(slug)) where slug is not null;

create table if not exists booking_requests (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  name text not null,
  contact text not null,
  preferred_time text,
  comment text,
  status text not null default 'new',
  created_at timestamptz not null default now()
);
create index if not exists booking_requests_tutor on booking_requests(tutor_user_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Trial + subscription + referrals on users
alter table users add column if not exists trial_ends_at timestamptz;
alter table users add column if not exists subscription_status text not null default 'trial';
alter table users add column if not exists referral_code text;
alter table users add column if not exists referred_by uuid references users(id);

-- Backfill: give existing tutors a 14-day trial from now and a referral code.
update users
   set trial_ends_at = now() + interval '14 days'
 where role = 'tutor' and trial_ends_at is null;

update users
   set referral_code = substr(md5(random()::text), 1, 8)
 where role = 'tutor' and referral_code is null;

create unique index if not exists users_referral_code_unique
  on users (referral_code) where referral_code is not null;
