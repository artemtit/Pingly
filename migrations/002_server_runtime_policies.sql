-- Server runtime policies for Pingly.
-- The bot/web backend uses SUPABASE_KEY from server-side Python code.
-- If your project has RLS enabled for these tables, these policies allow the
-- backend to operate. For production, replace anon usage with a service-role
-- key and tighten these policies.

do $$
declare
  table_name text;
  table_names text[] := array[
    'users',
    'tutor_profiles',
    'subjects',
    'student_profiles',
    'tutor_students',
    'schedule_rules',
    'lessons_v2',
    'lesson_participants',
    'homeworks',
    'attachments',
    'notifications',
    'progress_snapshots',
    'plans',
    'subscriptions',
    'payments',
    'web_login_tokens'
  ];
begin
  foreach table_name in array table_names loop
    execute format('alter table public.%I enable row level security', table_name);

    execute format('drop policy if exists pingly_server_select on public.%I', table_name);
    execute format('drop policy if exists pingly_server_insert on public.%I', table_name);
    execute format('drop policy if exists pingly_server_update on public.%I', table_name);
    execute format('drop policy if exists pingly_server_delete on public.%I', table_name);

    execute format(
      'create policy pingly_server_select on public.%I for select to anon, authenticated using (true)',
      table_name
    );
    execute format(
      'create policy pingly_server_insert on public.%I for insert to anon, authenticated with check (true)',
      table_name
    );
    execute format(
      'create policy pingly_server_update on public.%I for update to anon, authenticated using (true) with check (true)',
      table_name
    );
    execute format(
      'create policy pingly_server_delete on public.%I for delete to anon, authenticated using (true)',
      table_name
    );
  end loop;
end $$;
