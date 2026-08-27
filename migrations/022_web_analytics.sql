-- 022_web_analytics.sql
-- Собственная веб-аналитика: просмотры и цели пишутся в свою базу, а не
-- уходят в сторонний сервис. Нужна по двум причинам: (1) честные цифры без
-- ботов, которых Cloudflare считает как посетителей; (2) 152-ФЗ — чем меньше
-- данных уходит третьим лицам, тем меньше обязательств.
--
-- ПРИНЦИП МИНИМИЗАЦИИ. Здесь сознательно НЕТ:
--   * IP-адреса — ни в каком виде, даже хэшем;
--   * User-Agent целиком — только выведенный из него тип устройства;
--   * referrer с query-строкой — только хост (в query внешних сайтов
--     регулярно едут почты и токены).
-- visitor_id — случайное число из браузера, не выводится из свойств
-- устройства и ни с чем не связано. Это счётчик, а не идентификация человека.
--
-- РЕТЕНШН: чистить событиями старше 400 дней (см. delete_old_web_events ниже).

create table if not exists web_events (
  id           bigserial primary key,
  created_at   timestamptz not null default now(),
  -- Анонимные идентификаторы из браузера. visitor_id живёт в localStorage,
  -- session_id — в sessionStorage (новая вкладка = новый визит).
  visitor_id   text not null,
  session_id   text not null,
  -- 'pageview' или имя цели ('signup', 'student_added', ...).
  event        text not null,
  path         text not null,
  -- Только хост источника: 'yandex.ru', 't.me'. Пусто = прямой заход.
  referrer_host text,
  utm_source   text,
  utm_medium   text,
  utm_campaign text,
  -- 'mobile' | 'tablet' | 'desktop'. Выводится на сервере, UA не хранится.
  device       text,
  -- Заполняется только когда посетитель залогинен: связывает визит с
  -- аккаунтом, чтобы видеть путь «лендинг → регистрация → первый ученик».
  user_id      uuid references users(id) on delete set null,
  props        jsonb not null default '{}'::jsonb
);

-- Ограничения размера: эндпоинт публичный, без них любой зальёт мусор.
alter table web_events drop constraint if exists web_events_sane_sizes;
alter table web_events add constraint web_events_sane_sizes check (
  length(visitor_id) <= 64
  and length(session_id) <= 64
  and length(event) <= 64
  and length(path) <= 300
  and (referrer_host is null or length(referrer_host) <= 160)
  and (utm_source is null or length(utm_source) <= 120)
  and (utm_medium is null or length(utm_medium) <= 120)
  and (utm_campaign is null or length(utm_campaign) <= 120)
  and (device is null or device in ('mobile', 'tablet', 'desktop'))
);

-- Все выборки идут по «за последние N дней», поэтому ведущая колонка — время.
create index if not exists web_events_created_idx on web_events (created_at desc);
create index if not exists web_events_event_created_idx on web_events (event, created_at desc);
create index if not exists web_events_visitor_idx on web_events (visitor_id, created_at desc);

-- RLS: та же серверная политика, что у остальных таблиц (см. 002/006) —
-- сервер ходит под anon-ключом и является единственным клиентом базы.
do $$
declare
  table_name text;
  table_names text[] := array['web_events'];
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

-- ---------------------------------------------------------------------------
-- Агрегаты считает Postgres, а не Python. Остальная админка тянет строки и
-- складывает их в приложении, но событий на порядки больше репетиторов —
-- вытаскивать десятки тысяч строк на каждый заход в админку нельзя.
-- ---------------------------------------------------------------------------

create or replace function web_stats_summary(p_days int)
returns table (visitors bigint, sessions bigint, pageviews bigint)
language sql stable as $$
  select
    count(distinct e.visitor_id),
    count(distinct e.session_id),
    count(*) filter (where e.event = 'pageview')
  from web_events e
  where e.created_at >= now() - make_interval(days => p_days);
$$;

create or replace function web_stats_daily(p_days int)
returns table (day date, visitors bigint, pageviews bigint)
language sql stable as $$
  select
    (e.created_at at time zone 'UTC')::date,
    count(distinct e.visitor_id),
    count(*) filter (where e.event = 'pageview')
  from web_events e
  where e.created_at >= now() - make_interval(days => p_days)
  group by 1
  order by 1;
$$;

create or replace function web_stats_paths(p_days int, p_lim int default 15)
returns table (path text, pageviews bigint, visitors bigint)
language sql stable as $$
  select e.path, count(*), count(distinct e.visitor_id)
  from web_events e
  where e.event = 'pageview'
    and e.created_at >= now() - make_interval(days => p_days)
  group by 1
  order by 2 desc
  limit p_lim;
$$;

-- Источник = utm_source, иначе хост реферера, иначе «прямой заход».
create or replace function web_stats_sources(p_days int, p_lim int default 15)
returns table (source text, visitors bigint, sessions bigint)
language sql stable as $$
  select
    coalesce(nullif(e.utm_source, ''), nullif(e.referrer_host, ''), '(прямой заход)'),
    count(distinct e.visitor_id),
    count(distinct e.session_id)
  from web_events e
  where e.created_at >= now() - make_interval(days => p_days)
  group by 1
  order by 2 desc
  limit p_lim;
$$;

create or replace function web_stats_goals(p_days int)
returns table (event text, hits bigint, visitors bigint)
language sql stable as $$
  select e.event, count(*), count(distinct e.visitor_id)
  from web_events e
  where e.event <> 'pageview'
    and e.created_at >= now() - make_interval(days => p_days)
  group by 1
  order by 2 desc;
$$;

-- Устройства — чтобы понимать, чинить мобилку или десктоп.
create or replace function web_stats_devices(p_days int)
returns table (device text, visitors bigint)
language sql stable as $$
  select coalesce(e.device, 'unknown'), count(distinct e.visitor_id)
  from web_events e
  where e.created_at >= now() - make_interval(days => p_days)
  group by 1
  order by 2 desc;
$$;

-- Ретеншн. Вызывать вручную или из планировщика; хранить вечно незачем.
create or replace function delete_old_web_events(p_keep_days int default 400)
returns bigint
language plpgsql as $$
declare
  removed bigint;
begin
  delete from web_events e where e.created_at < now() - make_interval(days => p_keep_days);
  get diagnostics removed = row_count;
  return removed;
end $$;
