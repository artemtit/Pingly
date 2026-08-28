#!/usr/bin/env bash
# Перенос данных Supabase -> локальный Postgres. Выполняется В ОКНО ДАУНТАЙМА,
# когда `systemctl stop pingly` уже сделан: иначе часть записей уедет в старую
# базу уже после снятия дампа и потеряется.
#
# Пароль Supabase скрипт не хранит и не логирует — спрашивает при запуске.
set -euo pipefail

DBNAME=pingly
SUPA_HOST="db.evynbutpmarbotvfcqru.supabase.co"
DUMP=/root/pingly-supabase-$(date +%Y%m%d-%H%M).sql

if systemctl is-active --quiet pingly; then
  echo "ОСТАНОВИСЬ: сервис pingly ещё работает."
  echo "Сначала: systemctl stop pingly — иначе новые записи уедут в старую базу."
  exit 1
fi

read -rsp "Пароль базы Supabase (Dashboard -> Settings -> Database): " SUPA_PASS
echo

echo "==> снимаю дамп (схема public)"
PGPASSWORD="$SUPA_PASS" pg_dump \
  --host="$SUPA_HOST" --port=5432 --username=postgres --dbname=postgres \
  --schema=public --no-owner --no-privileges --no-comments \
  --file="$DUMP"
echo "дамп: $DUMP ($(du -h "$DUMP" | cut -f1))"

echo "==> заливаю в локальную базу"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DBNAME" -f "$DUMP"

echo "==> права на перенесённые объекты"
# default privileges действуют только на объекты, созданные ПОСЛЕ их установки,
# а эти приехали дампом — поэтому права выдаются отдельно.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DBNAME" <<'SQL'
grant all on all tables in schema public to anon, authenticated;
grant all on all sequences in schema public to anon, authenticated;
grant execute on all functions in schema public to anon, authenticated;
SQL

echo "==> сверка: количество строк в ключевых таблицах"
for t in users student_profiles tutor_students schedule_rules lessons_v2 web_events; do
  n=$(sudo -u postgres psql -tAq -d "$DBNAME" -c "select count(*) from ${t};" 2>/dev/null || echo "нет таблицы")
  printf "  %-20s %s\n" "$t" "$n"
done

echo
echo "Сверь числа с Supabase ПЕРЕД тем, как менять .env."
echo "Дальше: правка .env по /root/pingly-db-credentials.txt, затем systemctl start pingly."
