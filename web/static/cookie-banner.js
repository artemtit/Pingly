/* Баннер согласия на аналитические куки.
 *
 * Зачем: Яндекс.Метрика ставит _ym_uid и другие идентификаторы, а РКН
 * квалифицирует cookie-идентификаторы как персональные данные. С 01.09.2025
 * (ФЗ-156) согласие на них должно быть отдельным осознанным действием,
 * поэтому Метрика не грузится, пока человек не нажал «Принять».
 *
 * Собственная аналитика (/api/track) работает без согласия сознательно:
 * она не ставит кук, не хранит IP, идентификатор в ней — случайное число,
 * а не отпечаток браузера, и она уважает Do Not Track. Это первая сторона
 * и минимальный из возможных объёмов — гасить её вместе с Метрикой значило бы
 * остаться вообще без честных цифр ради формальности.
 */
(function () {
  'use strict';

  var KEY = 'pl_cookie_consent';   // 'all' | 'necessary'
  var CLS = 'pl-cookie';

  function read() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function write(v) {
    try { localStorage.setItem(KEY, v); } catch (e) { /* приватный режим — переживём */ }
  }

  // Метрику поднимает уже загруженный обработчик из partials/analytics.html.
  function accept() {
    write('all');
    if (typeof window.plStartMetrika === 'function') window.plStartMetrika();
    hide();
  }
  function decline() { write('necessary'); hide(); }

  function hide() {
    var el = document.querySelector('.' + CLS);
    if (!el) return;
    el.classList.add(CLS + '--out');
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 250);
  }

  function show() {
    var wrap = document.createElement('div');
    wrap.className = CLS;
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-label', 'Согласие на аналитические файлы cookie');
    wrap.innerHTML =
      '<div class="' + CLS + '__text">' +
        'Мы используем файлы cookie для статистики посещений. Без вашего согласия ' +
        'аналитические cookie не устанавливаются. Подробнее — в ' +
        '<a href="/privacy">Политике конфиденциальности</a>.' +
      '</div>' +
      '<div class="' + CLS + '__btns">' +
        '<button type="button" class="' + CLS + '__no">Только необходимые</button>' +
        '<button type="button" class="' + CLS + '__yes">Принять</button>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.querySelector('.' + CLS + '__yes').addEventListener('click', accept);
    wrap.querySelector('.' + CLS + '__no').addEventListener('click', decline);
    requestAnimationFrame(function () { wrap.classList.add(CLS + '--in'); });
  }

  var choice = read();
  if (choice === 'all') {
    if (typeof window.plStartMetrika === 'function') window.plStartMetrika();
    return;
  }
  if (choice === 'necessary') return;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', show);
  } else {
    show();
  }
}());
