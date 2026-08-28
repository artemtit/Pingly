#!/usr/bin/env bash
# Postgres 17 + PostgREST на боевом VPS. Ничего не переключает: после этого
# скрипта новая база стоит пустая, а Pingly продолжает работать на Supabase.
# Откат = просто не менять .env.
#
# Память на этом VPS в обрез (всего 2 ГБ, доступно ~940 МБ), поэтому Postgres
# настраивается скромно, а swap добавляется заранее: без него всплеск памяти
# убьёт бота, а не базу.
set -euo pipefail

PGVER=17
PGREST_VER=12.2.3
DBNAME=pingly
DBUSER=pingly
OUT=/root/pingly-db-credentials.txt

echo "==> swap (если ещё нет)"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap 2G добавлен"
else
  echo "swap уже есть, пропускаю"
fi

echo "==> Postgres ${PGVER}"
install -d /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
apt-get update -qq
apt-get install -y -qq "postgresql-${PGVER}" jq

echo "==> экономные настройки под 2 ГБ RAM"
PGCONF="/etc/postgresql/${PGVER}/main/conf.d/pingly.conf"
mkdir -p "$(dirname "$PGCONF")"
cat > "$PGCONF" <<CONF
# Затянуто под VPS с 2 ГБ: рядом живёт бот, и ему память нужнее.
shared_buffers = 128MB
effective_cache_size = 512MB
work_mem = 4MB
maintenance_work_mem = 64MB
max_connections = 20
listen_addresses = 'localhost'
CONF
systemctl restart postgresql

echo "==> база, роли, секреты"
DBPASS=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
create role ${DBUSER} login password '${DBPASS}';
create database ${DBNAME} owner ${DBUSER};
SQL

# Роли, которые ждёт PostgREST и под которые написаны RLS-политики
# (миграции 002/006/022 рассчитывают на anon).
sudo -u postgres psql -v ON_ERROR_STOP=1 -d ${DBNAME} <<SQL
create role anon nologin;
create role authenticated nologin;
grant anon, authenticated to ${DBUSER};
grant usage on schema public to anon, authenticated;
alter default privileges in schema public
  grant all on tables to anon, authenticated;
alter default privileges in schema public
  grant all on sequences to anon, authenticated;
alter default privileges in schema public
  grant execute on functions to anon, authenticated;
SQL

echo "==> PostgREST ${PGREST_VER}"
cd /tmp
curl -fsSL -o pgrst.tar.xz \
  "https://github.com/PostgREST/postgrest/releases/download/v${PGREST_VER}/postgrest-v${PGREST_VER}-linux-static-x86-64.tar.xz"
tar -xJf pgrst.tar.xz
install -m 755 postgrest /usr/local/bin/postgrest
rm -f pgrst.tar.xz postgrest

cat > /etc/postgrest.conf <<CONF
db-uri = "postgres://${DBUSER}:${DBPASS}@127.0.0.1:5432/${DBNAME}"
db-schemas = "public"
db-anon-role = "anon"
jwt-secret = "${JWT_SECRET}"
server-host = "127.0.0.1"
server-port = 3000
db-pool = 8
CONF
chmod 600 /etc/postgrest.conf

cat > /etc/systemd/system/postgrest.service <<UNIT
[Unit]
Description=PostgREST for Pingly
After=postgresql.service
Requires=postgresql.service

[Service]
ExecStart=/usr/local/bin/postgrest /etc/postgrest.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now postgrest

echo "==> anon-ключ (JWT с role=anon, как у Supabase)"
# Заголовок и payload в base64url, подпись HMAC-SHA256 — тот же формат,
# который supabase-py уже умеет отправлять.
b64() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
HDR=$(printf '{"alg":"HS256","typ":"JWT"}' | b64)
PLD=$(printf '{"role":"anon","iss":"pingly"}' | b64)
SIG=$(printf '%s.%s' "$HDR" "$PLD" \
      | openssl dgst -binary -sha256 -mac HMAC -macopt "hexkey:$(printf '%s' "$JWT_SECRET" | xxd -p -c256)" \
      | b64)
ANON_KEY="${HDR}.${PLD}.${SIG}"

cat > "$OUT" <<TXT
Создано: $(date -Iseconds)

DB_PASSWORD  = ${DBPASS}
JWT_SECRET   = ${JWT_SECRET}

Для .env (менять ТОЛЬКО в окно даунтайма, шаг 3 из README):
SUPABASE_URL=http://127.0.0.1:3000
SUPABASE_KEY=${ANON_KEY}
TXT
chmod 600 "$OUT"

echo
echo "Готово. Ничего ещё не переключено — прод по-прежнему на Supabase."
echo "Секреты и будущие значения .env: ${OUT}"
systemctl --no-pager -l status postgrest | head -5
