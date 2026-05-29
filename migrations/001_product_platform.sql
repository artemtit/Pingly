-- Pingly v2 product platform migration.
-- Run in Supabase SQL editor after the original MVP schema exists.

create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  role text not null check (role in ('student', 'tutor')),
  tg_id bigint unique,
  tg_username text,
  full_name text not null,
  notification_settings jsonb not null default '{"telegram": true}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tutor_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references users(id) on delete cascade,
  display_name text not null,
  bio text,
  created_at timestamptz not null default now()
);

create table if not exists subjects (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists student_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references users(id) on delete set null,
  name text not null,
  tg_username text,
  invite_token text unique,
  level text,
  subject_summary text,
  progress_note text,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table if not exists tutor_students (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  student_id uuid not null references student_profiles(id) on delete cascade,
  status text not null default 'active',
  private_tutor_note text,
  created_at timestamptz not null default now(),
  unique (tutor_user_id, student_id)
);

create table if not exists schedule_rules (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  student_id uuid not null references student_profiles(id) on delete cascade,
  subject_id uuid references subjects(id) on delete set null,
  day_of_week int not null check (day_of_week between 0 and 6),
  lesson_time time not null,
  duration_minutes int not null default 60,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists lessons_v2 (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  student_id uuid not null references student_profiles(id) on delete cascade,
  student_user_id uuid references users(id) on delete set null,
  subject_id uuid references subjects(id) on delete set null,
  schedule_rule_id uuid references schedule_rules(id) on delete set null,
  starts_at timestamptz not null,
  duration_minutes int not null default 60,
  status text not null default 'scheduled' check (status in ('scheduled', 'completed', 'rescheduled', 'cancelled')),
  public_comment text,
  private_tutor_note text,
  rescheduled_from timestamptz,
  cancel_reason text,
  created_at timestamptz not null default now()
);

create table if not exists lesson_participants (
  id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null references lessons_v2(id) on delete cascade,
  student_id uuid not null references student_profiles(id) on delete cascade,
  status text not null default 'invited',
  unique (lesson_id, student_id)
);

create table if not exists homeworks (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  student_id uuid not null references student_profiles(id) on delete cascade,
  student_user_id uuid references users(id) on delete set null,
  lesson_id uuid references lessons_v2(id) on delete set null,
  title text not null,
  description text,
  due_at timestamptz,
  status text not null default 'new' check (status in ('new', 'in_progress', 'submitted', 'reviewed')),
  tutor_comment text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists attachments (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid references users(id) on delete set null,
  lesson_id uuid references lessons_v2(id) on delete cascade,
  homework_id uuid references homeworks(id) on delete cascade,
  file_url text not null,
  file_name text,
  mime_type text,
  created_at timestamptz not null default now()
);

create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  type text not null,
  title text not null,
  body text not null,
  payload jsonb not null default '{}',
  channel text not null default 'telegram',
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed', 'read')),
  scheduled_for timestamptz not null default now(),
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists progress_snapshots (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references student_profiles(id) on delete cascade,
  attendance_percent int not null default 100,
  homework_completion_percent int not null default 0,
  subject_dynamic text,
  created_at timestamptz not null default now()
);

create table if not exists plans (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  title text not null,
  price_rub int not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  tutor_user_id uuid not null references users(id) on delete cascade,
  plan_id uuid references plans(id) on delete set null,
  status text not null default 'trial',
  current_period_end timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  subscription_id uuid references subscriptions(id) on delete set null,
  amount_rub int not null,
  provider text,
  provider_payment_id text,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);

create table if not exists web_login_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

-- Compatibility migration from MVP tables. Safe to run multiple times.
-- The earliest MVP schema did not include students.invite_token, so the
-- migration uses dynamic SQL and creates stable fallback tokens from ids.
do $$
declare
  has_tutors boolean;
  has_students boolean;
  has_lessons boolean;
  has_student_invite_token boolean;
  has_student_tg_id boolean;
begin
  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'tutors'
  ) into has_tutors;

  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'students'
  ) into has_students;

  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'lessons'
  ) into has_lessons;

  if has_tutors then
    execute $sql$
      insert into users (role, tg_id, full_name)
      select 'tutor', t.tg_id, t.name
      from tutors t
      on conflict (tg_id) do nothing
    $sql$;

    insert into tutor_profiles (user_id, display_name)
    select u.id, u.full_name
    from users u
    where u.role = 'tutor'
    on conflict (user_id) do nothing;
  end if;

  if has_students then
    select exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'students' and column_name = 'invite_token'
    ) into has_student_invite_token;

    select exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'students' and column_name = 'tg_id'
    ) into has_student_tg_id;

    if has_student_tg_id then
      execute $sql$
        insert into users (role, tg_id, tg_username, full_name)
        select 'student', s.tg_id, s.tg_username, s.name
        from students s
        where s.tg_id is not null
        on conflict (tg_id) do nothing
      $sql$;
    end if;

    if has_student_invite_token and has_student_tg_id then
      execute $sql$
        insert into student_profiles (name, tg_username, invite_token, user_id)
        select s.name, s.tg_username, s.invite_token, su.id
        from students s
        left join users su on su.tg_id = s.tg_id
        on conflict (invite_token) do nothing
      $sql$;
    elsif has_student_invite_token then
      execute $sql$
        insert into student_profiles (name, tg_username, invite_token)
        select s.name, s.tg_username, s.invite_token
        from students s
        on conflict (invite_token) do nothing
      $sql$;
    elsif has_student_tg_id then
      execute $sql$
        insert into student_profiles (name, tg_username, invite_token, user_id)
        select s.name, s.tg_username, 'legacy_' || s.id::text, su.id
        from students s
        left join users su on su.tg_id = s.tg_id
        on conflict (invite_token) do nothing
      $sql$;
    else
      execute $sql$
        insert into student_profiles (name, tg_username, invite_token)
        select s.name, s.tg_username, 'legacy_' || s.id::text
        from students s
        on conflict (invite_token) do nothing
      $sql$;
    end if;

    if has_student_invite_token then
      execute $sql$
        insert into tutor_students (tutor_user_id, student_id)
        select tu.id, sp.id
        from students s
        join users tu on tu.tg_id = s.tutor_id
        join student_profiles sp on sp.invite_token = s.invite_token
        on conflict (tutor_user_id, student_id) do nothing
      $sql$;
    else
      execute $sql$
        insert into tutor_students (tutor_user_id, student_id)
        select tu.id, sp.id
        from students s
        join users tu on tu.tg_id = s.tutor_id
        join student_profiles sp on sp.invite_token = 'legacy_' || s.id::text
        on conflict (tutor_user_id, student_id) do nothing
      $sql$;
    end if;
  end if;

  if has_lessons and has_students then
    if has_student_invite_token then
      execute $sql$
        insert into schedule_rules (tutor_user_id, student_id, day_of_week, lesson_time)
        select tu.id, sp.id, l.day_of_week, l.lesson_time
        from lessons l
        join students s on s.id = l.student_id
        join users tu on tu.tg_id = s.tutor_id
        join student_profiles sp on sp.invite_token = s.invite_token
        where l.is_active = true
          and not exists (
            select 1 from schedule_rules sr
            where sr.tutor_user_id = tu.id
              and sr.student_id = sp.id
              and sr.day_of_week = l.day_of_week
              and sr.lesson_time = l.lesson_time
          )
      $sql$;
    else
      execute $sql$
        insert into schedule_rules (tutor_user_id, student_id, day_of_week, lesson_time)
        select tu.id, sp.id, l.day_of_week, l.lesson_time
        from lessons l
        join students s on s.id = l.student_id
        join users tu on tu.tg_id = s.tutor_id
        join student_profiles sp on sp.invite_token = 'legacy_' || s.id::text
        where l.is_active = true
          and not exists (
            select 1 from schedule_rules sr
            where sr.tutor_user_id = tu.id
              and sr.student_id = sp.id
              and sr.day_of_week = l.day_of_week
              and sr.lesson_time = l.lesson_time
          )
      $sql$;
    end if;
  end if;
end $$;
