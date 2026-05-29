# Pingly

Единая система для репетиторов и учеников: Telegram-бот + веб-кабинет на одном backend.

## Что есть

- Telegram-бот как быстрый интерфейс.
- Веб-кабинет FastAPI/Jinja.
- Общий application layer для бота и сайта.
- CRM учеников, расписание, домашние задания, уведомления и аналитика.
- Подготовка схемы под групповые занятия, подписки, оплату и мобильное приложение.

## Архитектура

```text
Presentation Layer
├── handlers/          Telegram Bot
└── web/               Web Dashboard

Application Layer
├── application/services
└── application/use cases через сервисы

Domain Layer
└── domain/

Infrastructure Layer
├── infrastructure/supabase_repository.py
├── scheduler.py
└── db.py              Supabase bootstrap only
```

UI-слои не должны обращаться к Supabase напрямую. Все операции идут через `application/services`.

## Запуск

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Заполнить `.env`:

```env
BOT_TOKEN=...
SUPABASE_URL=...
SUPABASE_KEY=...
WEB_BASE_URL=http://localhost:8000
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_SECRET=change-me
WEB_ENABLED=1
```

3. Применить SQL:

```text
supabase_schema.sql
migrations/001_product_platform.sql
```

4. Запустить:

```bash
python bot.py
```

Один процесс запускает Telegram-бота, scheduler и веб-кабинет.

## Telegram

Команды сохранены, но основной интерфейс теперь кнопочный.

Репетитор:

- `👥 Мои ученики`
- `➕ Добавить ученика`
- `📅 Календарь`
- `➕ Добавить занятие`
- `📝 Добавить задание`
- `📊 Аналитика`
- `🌐 Веб-кабинет`

Ученик:

- `📚 Следующее занятие`
- `📝 Мои задания`
- `📈 Мой прогресс`
- `🌐 Веб-кабинет`
