# Бэклог

## Сделано и задеплоено (эта сессия)
1. ~~404 page~~ — добавлен `noindex`, структура ок
2. ~~PWA manifest.json~~ + иконки 192/512 + подключено на base/landing/login/register
3. ~~a11y: aria-label~~ на иконках-кнопках — нашёлся 1 реальный пробел (иконка корзины в calendar.html), исправлено
4. ~~a11y: alt-атрибуты~~ — аудит: везде уже есть alt, правок не потребовалось
5. ~~noindex~~ на всех кабинетных страницах (через base.html) + login/register/verify/404
6. ~~Sitemap: публичные /u/ профили~~ — сделано ранее
7. ~~Cookie hardening~~ — проверено ранее, норм
8. ~~Booking length caps~~ — проверено ранее, норм
9. ~~Тихие except~~ → логирование в billing.py и scheduler.py (все платёжные и напоминательные пути)
10. ~~Юнит-тесты~~ — `tests/` (32 теста): billing (цена/период/дни/reconcile/webhook-идемпотентность), package_status, _series_view
11. ~~Rate-limit~~ на `/auth/telegram/callback` (20/5мин на IP, как остальные auth-эндпоинты)
12. ~~rel="noopener"~~ — аудит внешних ссылок, нашлось 2 пропуска в register.html, исправлено
13. ~~Branded 500 handler~~ — сделано ранее

## Важная находка (решено)
**"Каждую неделю" и "Несколько раз в неделю" рендерились ОДИНАКОВО** (тест `test_multiple_weekly_renders_identically_to_weekly` в `tests/test_series_view.py`). Опции в выпадающем списке уже были объединены в одну (`multiple_weekly`) параллельным агентом ранее — оставалась только мусорная подпись "Каждую неделю (по дням)". Переименовано в "Несколько раз в неделю", мёртвая запись `"weekly"` убрана из `RECURRENCE_LABELS`. Задеплоено (commit `d411808`).

## Что нужно от Артёма (не блокирует, но важно)
- Указать в Platega вебхук-URL: `https://pingly-app.ru/payments/platega/webhook`
- Провести один тестовый платёж 990 ₽, проверить активацию подписки
- Проверить новую оранжевую кнопку «Войти через Telegram»
- Проверить на телефоне «Добавить на экран» (PWA) — иконка/название/сплэш
- (опционально) `POSTHOG_KEY=phc_zqBi6vakUdqNHkuD4CxhUjw4QFMEQPp3xPDpEjcryriJ` в `.env` сервера + рестарт — включит воронку в PostHog

## Дальше (не начато)
- Больше юнит-тестов по мере роста кодовой базы (web_auth, students, admin)

## Тесты — как запускать
```
pip install -r requirements-dev.txt
pytest
```
32 теста, ~0.5 сек. `pytest.ini` уже настроен (`asyncio_mode = auto`, `testpaths = tests`).

## Контекст по деплою
- Деплой: paramiko (SFTP по файлам) на `81.85.73.173`, сервис `pingly` (systemd)
- `.html/.css/.js` — можно грузить БЕЗ рестарта (Jinja auto_reload + StaticFiles с диска)
- `.py` — грузить + `systemctl restart pingly`, затем проверить `systemctl is-active` и `curl /health`
- После рестарта — заменить рестартовое окно проверкой логов: `journalctl -u pingly -n 5 --no-pager -o cat`
- Транзиентный `TelegramConflictError` в логах сразу после рестарта — норма, самоустраняется за ~1 сек (старое long-poll соединение ещё закрывается)
