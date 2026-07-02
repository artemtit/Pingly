# Бэклог (сохранено перед /compact)

## В работе / далее по порядку
1. **404 page** — проверить/отполировать (скорее всего уже ок, но не перепроверено после последних правок)
2. **PWA manifest.json** + `<link rel="manifest">` + иконки 192/512
3. **a11y: aria-label** на кнопках-иконках без текста (kebab-меню, icon-btn и т.д.)
4. **a11y: alt-атрибуты** — аудит картинок без alt
5. **noindex** на служебных/превью страницах (например `/tutor/requests/preview`)
6. ~~Sitemap: публичные `/u/` профили~~ — **сделано и задеплоено**
7. ~~Cookie hardening~~ — **проверено, уже норм** (HttpOnly/SameSite=lax/Secure на https)
8. ~~Booking length caps~~ — **проверено, уже норм** (name/contact/comment обрезаются)
9. **Заменить тихие `except: pass`** на логирование в платёжных/напоминательных путях
10. **Юнит-тесты**: billing (цена/период/дни), reconcile_on_return, _series_view
11. **Rate-limit** на `/auth/telegram/callback` (сейчас не ограничен)
12. **Аудит `rel="noopener"`** на внешних ссылках (target="_blank")
13. ~~Branded 500 handler~~ — **сделано и задеплоено** (логирует трейсбек + красивая страница)

## Что нужно от Артёма (не блокирует бэклог, но важно)
- Указать в Platega вебхук-URL: `https://pingly-app.ru/payments/platega/webhook`
- Провести один тестовый платёж 990 ₽, проверить активацию подписки
- Проверить новую оранжевую кнопку «Войти через Telegram»
- (опционально) `POSTHOG_KEY=phc_zqBi6vakUdqNHkuD4CxhUjw4QFMEQPp3xPDpEjcryriJ` в `.env` сервера + рестарт — включит воронку в PostHog (сейчас аналитика выключена)

## Контекст по деплою
- Деплой: paramiko (SFTP по файлам) на `81.85.73.173`, сервис `pingly` (systemd)
- `.html/.css/.js` — можно грузить БЕЗ рестарта (Jinja auto_reload + StaticFiles с диска)
- `.py` — грузить + `systemctl restart pingly`, затем проверить `systemctl is-active` и `curl /health`
- После рестарта — заменить рестартовое окно проверкой логов: `journalctl -u pingly -n 5 --no-pager -o cat`
