-- 007_subscription_payments.sql
-- Ledger of Platega subscription payments (audit + idempotency for webhooks).
-- Safe to run multiple times.

create table if not exists subscription_payments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  provider text not null default 'platega',
  transaction_id text unique,
  amount_rub int not null,
  status text not null default 'pending',   -- pending | confirmed | canceled
  created_at timestamptz not null default now(),
  confirmed_at timestamptz
);
create index if not exists subscription_payments_user on subscription_payments(user_id);

-- Permissive server-side RLS policies (same pattern as 002 / 006).
do $$
declare
  t text := 'subscription_payments';
begin
  execute format('alter table public.%I enable row level security', t);
  execute format('drop policy if exists pingly_server_select on public.%I', t);
  execute format('drop policy if exists pingly_server_insert on public.%I', t);
  execute format('drop policy if exists pingly_server_update on public.%I', t);
  execute format('drop policy if exists pingly_server_delete on public.%I', t);
  execute format('create policy pingly_server_select on public.%I for select to anon, authenticated using (true)', t);
  execute format('create policy pingly_server_insert on public.%I for insert to anon, authenticated with check (true)', t);
  execute format('create policy pingly_server_update on public.%I for update to anon, authenticated using (true) with check (true)', t);
  execute format('create policy pingly_server_delete on public.%I for delete to anon, authenticated using (true)', t);
end $$;
