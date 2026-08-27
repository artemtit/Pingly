-- 021_public_page_selling.sql
-- Публичная страница /u/<slug> как продающая визитка: цена, отзывы, прямой
-- контакт в Telegram. Всё опциональное — блок на странице показывается только
-- если поле заполнено, поэтому существующие профили выглядят как раньше.
--
-- reviews хранится jsonb-массивом прямо в профиле (не отдельной таблицей):
-- страница обязана рендериться ОДНИМ запросом к БД, а отзывов максимум 10.

alter table tutor_profiles add column if not exists price_per_hour integer;
alter table tutor_profiles add column if not exists price_duration_min integer not null default 60;
alter table tutor_profiles add column if not exists price_note text;
alter table tutor_profiles add column if not exists telegram_username text;
alter table tutor_profiles add column if not exists reviews jsonb not null default '[]'::jsonb;

-- Цена: целое, 0 < цена < 100000. Пусто (NULL) = блок цены скрыт.
alter table tutor_profiles drop constraint if exists tutor_profiles_price_range;
alter table tutor_profiles add constraint tutor_profiles_price_range
  check (price_per_hour is null or (price_per_hour > 0 and price_per_hour < 100000));

-- Длительность занятия, к которой относится цена. Дефолт 60 = «за 60 мин».
alter table tutor_profiles drop constraint if exists tutor_profiles_price_duration_range;
alter table tutor_profiles add constraint tutor_profiles_price_duration_range
  check (price_duration_min between 5 and 600);

-- reviews: всегда массив, не более 10 элементов. Форму элементов
-- ({author, text, position}) валидирует приложение — здесь только каркас,
-- чтобы кривой jsonb не мог попасть в таблицу вообще.
alter table tutor_profiles drop constraint if exists tutor_profiles_reviews_shape;
alter table tutor_profiles add constraint tutor_profiles_reviews_shape
  check (jsonb_typeof(reviews) = 'array' and jsonb_array_length(reviews) <= 10);

-- Адрес страницы: латиница/цифры/дефис, 3–30 символов. Уникальность уже
-- обеспечена индексом tutor_profiles_slug_unique из миграции 005.
-- Существующие 14 профилей проверены — все проходят.
alter table tutor_profiles drop constraint if exists tutor_profiles_slug_format;
alter table tutor_profiles add constraint tutor_profiles_slug_format
  check (slug is null or slug ~ '^[a-z0-9-]{3,30}$');
