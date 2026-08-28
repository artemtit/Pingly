# Pingly — CLAUDE.md

## Рабочий процесс
- **Контекст / compact (договорённость).** Claude сам `/compact` запустить НЕ может — команду жмёт Артём. Поэтому Claude обязан **сам, заранее** написать «⚠️ Контекст большой — запусти `/compact`», как только контекст подходит к **~150k**, и повторять напоминание каждые ~20k сверх того. Не молчать и не доводить до слитых лимитов.
- Перед длинными автономными прогонами (пул из многих задач): если контекст уже большой — сначала предупредить про `/compact`, потом начинать.
- **Второй мозг (Obsidian).** Всю значимую информацию — решения, факты, контекст, итоги задач, найденные проблемы и их разбор — Claude обязан выгружать во «второй мозг»: Obsidian-vault по пути `C:\Users\titiv\OneDrive\Dokumenter\Claude-Second-Brain\Claude-Second-Brain` (плагин claude-obsidian). Создавать/дополнять там связанные Markdown-заметки с `[[вики-ссылками]]`, а не держать знания только в чате. Мелочь и одноразовое — не засорять; в мозг идёт то, что пригодится позже.
  - **Авто-подгрузка на старте:** `SessionStart`-хук вставляет `wiki/hot.md` (горячий кэш) в контекст каждой сессии — так Claude сразу понимает «кто + проекты + свежак» без разведки. За деталями идти по `hot.md` → `wiki/index.md` → конкретная страница (не тянуть всю базу).
  - **Поддержание кэша:** после значимых изменений/в конце сессии обновлять `wiki/hot.md` (≤500 слов, перезаписывать целиком): стабильная шапка «Кто/Проекты» + свежий контекст + активные нити. Иначе авто-контекст устареет.
  - **Автосохранение:** vault под git; `Stop`-хук `~/.claude/hooks/vault-autosave.py` коммитит базу в конце каждой сессии из любого проекта.

## Что это
Сервис автоматических напоминаний для репетиторов. Репетитор вбивает расписание и TG учеников один раз — бот сам шлёт напоминание за 2 часа до занятия. Ученик нажимает "Буду" / "Отменяю", репетитор видит статус.

## Основатель
Артём, 15 лет. Python, Telegram-боты, API, базовый fullstack. Бюджет ~10000 ₽. Цель — первый доход до конца лета 2026.

## Статус
Валидация завершена (3/3 репетиторов подтвердили боль, WTP 500–1000 ₽/мес).
Сейчас: пишем MVP.

## Стек
- Python + aiogram 3
- Supabase (PostgreSQL)
- APScheduler — напоминания по расписанию
- VPS **vdska, Варшава (Польша)** — Ubuntu 22.04, IP 81.85.73.173, hostname `vdska`,
  AS49791 Newserverlife LLC. **Не Timeweb и не Россия** — проверено 28.08.2026 по IP.
  Машина общая: рядом живут Nota (3 юнита), flowly, lmh-bank, личный VPN `sing-box`,
  nginx, redis и **postgresql@14** (порт 5432 занят — учитывать при установке БД).
  Заграничное расположение = нерешённая локализация ПДн по ч. 5 ст. 18 152-ФЗ,
  см. `scripts/migrate_to_ru/README.md`.

## Деплой — обязательно после каждого изменения
После любого изменения кода нужно:
1. Закоммитить и запушить на GitHub: `git add . && git commit -m "..." && git push`
2. Задеплоить на сервер: `python deploy.py`

Или вручную через SSH:
```
scp -r . root@81.85.73.173:/opt/pingly/
ssh root@81.85.73.173 "systemctl restart pingly"
```

Бот работает как systemd-сервис `pingly`. Логи: `journalctl -u pingly -f`

## Ключевые решения
- V1 — только Telegram. VK API — в V2 (все 3 репетитора используют TG + VK + Max, но TG самый частый)
- Цена: 500–1000 ₽/мес
- **Весь функционал — на сайте, бот — чисто служебный (для обеих ролей).** Бот умеет ровно три вещи: (1) вход/регистрация через Telegram + выдача ссылки в кабинет (`/start`, `/web`); (2) доставка напоминаний ученикам (одно напоминание, по умолчанию **за 2 часа** до занятия — репетитор может поменять на 1–24ч в настройках, `users.reminder_hours`); (3) кнопки «Буду/Отменяю/Прошу перенести» под напоминанием (`lesson_confirm`/`lesson_cancel`/`lesson_reschedule`, все пишут статус в БД — репетитор видит на сайте; «Буду» шлёт репетитору пуш «X подтвердил», «Отменяю» — пуш «X отменил», «Прошу перенести» — пуш «X просит перенести», статус `reschedule_requested`). В боте НЕТ управляющих меню/FSM (ни у репетитора, ни у ученика) — всё это убрано осознанно (handlers/keyboards.py удалён). **Одно осознанное исключение:** после «Отменяю» или «Прошу перенести» бот ждёт одно текстовое сообщение (причина отмены / удобное время) и пересылает его репетитору (лёгкое ожидание в памяти `_awaiting_reason`, не полноценный FSM, TTL 10 мин). Управление учениками/расписанием/ДЗ — только в веб-кабинете.
- Регистрация репетитора: email+пароль ИЛИ Telegram Login Widget (кнопка «Войти через Telegram»). Для виджета нужен `/setdomain` в BotFather (домен pingly-app.ru).
- Маркетинговый лендинг — на `/` для незалогиненных (`web/templates/landing.html` + `web/static/landing.css`), в стиле дизайн-системы.

## Не делать пока
- Конструктор ботов (исходная идея отброшена после валидации)


## Каналы запуска
TG-сообщества репетиторов, VK-группы, Авито, сарафан от 3 валидационных репетиторов.

## Файлы проекта
- `CONTEXT_NEW_IDEA.md` — полный контекст: валидация, диалоги с репетиторами, план до 100к ₽/мес

## Карта кода (чтобы не искать заново)
Архитектура слоёная: **domain → application → infrastructure → (handlers | web)**. Зависимости идут только внутрь; сервисы не знают про aiogram/FastAPI, инфраструктура прячет Supabase/HTTP.

### Точка входа и запуск
- `bot.py` — **единый процесс**: поднимает веб-кабинет (uvicorn+`create_app()`) → резолвит имя бота → регистрирует команды (`/start`,`/web`,`/help`) → роутеры TG → (опц.) VK Long Poll → APScheduler → `dp.start_polling`. Веб стартует ПЕРВЫМ, чтобы медленный TG-хендшейк не давал 502.
- `config.py` — все env/настройки (BOT_TOKEN, SUPABASE_*, WEB_*, флаги `WEB_ENABLED`/`VK_ENABLED`/`PLANS_ENABLED`/платежи/CAPTCHA/EMAIL, SUPPORT_TG_ID). Читает `.env`.
- `db.py` — глобальный async-клиент Supabase (`init_db()`, `client()`). 18 строк.
- `deploy.py` — деплой на VPS (см. раздел «Деплой»). `scheduler.py` — планировщик напоминаний.

### Слои
- **`domain/models.py`** — чистые модели и енумы (frozen dataclass): `User`,`Student`,`Tutor`,`Subject`,`ScheduleRule`,`Lesson`,`Homework`,`Notification` + `UserRole`/`LessonStatus`/`HomeworkStatus`/`NotificationType`/`NotificationStatus`. Бизнес-правил тут нет, только структуры.
- **`application/`** — бизнес-логика (не знает про фреймворки):
  - `repositories.py` — `PinglyRepository` (Protocol): контракт доступа к данным.
  - `factory.py` — `Services`/`create_services()`: собирает репозиторий + все сервисы (DI-корень).
  - `services/` — по одному сервису на домен: `lessons.py` (647, ядро — расписание/статусы/генерация серий), `billing.py` (подписки/Platega), `web_auth.py` (сессии, TG Login Widget, CSRF), `students.py`, `homework.py`, `accounts.py`, `admin.py`, `public.py`, `notifications.py`, `analytics.py`, `timezones.py` (per-tutor пояса, `current_tz()`).
- **`infrastructure/`** — адаптеры к внешнему миру:
  - `supabase_repository.py` (1040) — реализация `PinglyRepository` поверх Supabase (все SQL-запросы тут).
  - `openmodel.py` — ИИ-клиент (Anthropic Messages формат, `/v1/messages`, x-api-key) для веб-ассистента.
  - `platega.py` — платежи (СБП), `email.py` — Resend, `captcha.py` — Cloudflare Turnstile, `vk.py` — stateless-отправка в VK.
- **`handlers/`** — Telegram-роутеры (тонкие, служебный бот): `tutor.py` (`/start`,`/web`,`/help`, вход/линковка), `student.py` (кнопки Буду/Отменяю/Прошу перенести + `_awaiting_reason` — приём причины/времени одним сообщением, `/next`, «📅 Моё занятие»).
- **`vk_bot.py`** — VK-бот (Long Poll напрямую через aiohttp, без vkbottle). Зеркалит студенческую часть TG. Спит пока `VK_ENABLED=0`.

### Веб-кабинет (`web/`)
- `web/app.py` (1891) — **вся FastAPI-аппа и роуты**, собирается в `create_app()`. Группы:
  - Публичное: `/`, `/login`,`/register`,`/verify`,`/auth/telegram*`, `/u/{slug}` (публичный профиль+запись), `/privacy`,`/terms`,`/contacts`, `/health`, `/robots.txt`,`/sitemap.xml`, `/payments/platega/webhook`.
  - Репетитор: `/tutor`, `/tutor/students*`, `/tutor/schedule`, `/tutor/calendar[.ics]`, `/tutor/homework*`, `/tutor/lessons/{id}/*` (complete/cancel/paid/comment/reschedule), `/tutor/finance[.csv]`, `/tutor/requests*`, `/tutor/settings*` (в т.ч. `/vk/connect`), `/tutor/billing/subscribe`.
  - Ученик: `/student`, `/student/calendar`,`/student/homework*`, `/student/lessons/{id}/*` (confirm/cancel/reschedule-request), `/student/history`, `/student/settings`.
  - Общее/прочее: `/settings/*`, `/account/delete`, `/support`, `/api/ai/chat` (ИИ-ассистент), `/api/public/stats`.
  - Админка: `/admin`, `/admin/tutors*`, `/admin/broadcast` (по `is_admin`).
  - `web/calendar_view.py` — построение день/неделя/месяц из списка занятий.
  - `web/templates/` — Jinja (`base.html`/`layout.html`/`macros.html`, страницы ролей, `landing.html`, `admin/*`, `partials/*`). `web/static/` — css/js (`app`,`landing`,`assistant`,`tour`), логотипы, PWA-манифест.
- Дизайн-система: `design-tokens.css` (+ отдаётся на `/design-tokens.css`), `design-decisions.md`, `_design/`, `LANDING_REDESIGN_SPEC.md`.

### Данные/прочее
- `supabase_schema.sql` — УСТАРЕЛ, не запускать (см. комментарий в файле). Реальная схема — только `migrations/001..019_*.sql` по порядку (применять через Supabase MCP). `tests/` — pytest (`test_lessons`,`test_billing`,`test_series_view`), запуск `python3 -m pytest -q`. `prompts/` — промпты ИИ. `scripts/` — вспомогательное.
