-- 006_growth_rls_policies.sql
-- The tables added in 005 (booking_requests, homework_templates) have RLS
-- enabled but no policies, so the backend (anon key) can't insert/select.
-- Apply the same permissive server policies used in 002 for the rest. Safe to
-- run multiple times.

do $$
declare
  table_name text;
  table_names text[] := array[
    'booking_requests',
    'homework_templates'
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
