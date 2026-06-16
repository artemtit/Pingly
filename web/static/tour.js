/* Pingly — guided product tour. Vanilla JS, no deps. */
(function () {
  "use strict";

  var STORAGE_KEY = "pingly_tour_v2";

  var STEPS = {
    tutor: [
      { center: true, emoji: "👋", title: "Добро пожаловать в Pingly!",
        text: "Покажу за полминуты, что где в кабинете. Можно пропустить в любой момент." },
      { sel: 'a[href="/tutor"]', emoji: "📊", title: "Обзор",
        text: "Главный экран: статистика, ближайшие занятия и задания, которые ученики сдали на проверку." },
      { sel: 'a[href="/tutor/students"]', emoji: "👥", title: "Ученики",
        text: "Здесь добавляешь учеников прямо на сайте и ведёшь их карточки — предмет, цель, заметки, история." },
      { sel: 'a[href="/tutor/calendar"]', emoji: "📅", title: "Календарь",
        text: "Все занятия наглядно. Переключай день, неделю и месяц, переноси и отменяй уроки." },
      { sel: 'a[href="/tutor/schedule"]', emoji: "⏰", title: "Расписание",
        text: "Настрой повторяющиеся занятия один раз — бот сам напомнит ученикам за 2 часа до урока." },
      { sel: 'a[href="/tutor/homework"]', emoji: "📝", title: "Задания",
        text: "Выдавай домашние задания и проверяй сданное — всё в одном месте." },
      { sel: 'a[href="/tutor/finance"]', emoji: "💰", title: "Финансы",
        text: "Сколько занятий проведено и на какую сумму, кто сколько должен — всё считается само." },
      { sel: 'a[href="/tutor/requests"]', emoji: "📥", title: "Заявки",
        text: "Заявки на занятия с твоей публичной страницы записи приходят сюда." },
      { sel: 'a[href="/tutor/settings"]', emoji: "⚙️", title: "Настройки",
        text: "Профиль, тема оформления и ссылка на бота." },
      { center: true, emoji: "🎉", title: "Готово!",
        text: "Это весь кабинет. Повторить обзор можно в любой момент — кнопка «Обзор» внизу меню." }
    ],
    student: [
      { center: true, emoji: "👋", title: "Добро пожаловать в Pingly!",
        text: "Быстрый обзор твоего кабинета — займёт полминуты." },
      { sel: 'a[href="/student"]', emoji: "🏠", title: "Главная",
        text: "Ближайшее занятие и кнопки «Буду / Отменяю»." },
      { sel: 'a[href="/student/calendar"]', emoji: "📅", title: "Календарь",
        text: "Все твои занятия — день, неделя, месяц." },
      { sel: 'a[href="/student/homework"]', emoji: "📝", title: "Задания",
        text: "Домашние задания от репетитора и их статус." },
      { center: true, emoji: "🎉", title: "Готово!",
        text: "Повторить обзор можно кнопкой «Обзор» внизу меню." }
    ]
  };

  var els = null, steps = [], idx = 0;

  function visibleTarget(sel) {
    if (!sel) return null;
    var list = document.querySelectorAll(sel);
    for (var i = 0; i < list.length; i++) {
      if (list[i].offsetParent !== null) return list[i];
    }
    return null;
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function build() {
    var mask = document.createElement("div"); mask.className = "tour-mask";
    var spot = document.createElement("div"); spot.className = "tour-spot hidden";
    var skip = document.createElement("button"); skip.className = "tour-skip"; skip.textContent = "Пропустить";
    var pop = document.createElement("div"); pop.className = "tour-pop";
    document.body.appendChild(mask);
    document.body.appendChild(spot);
    document.body.appendChild(skip);
    document.body.appendChild(pop);
    skip.addEventListener("click", finish);
    mask.addEventListener("click", function () {/* block clicks, no advance */});
    window.addEventListener("resize", render);
    window.addEventListener("keydown", onKey);
    return { mask: mask, spot: spot, skip: skip, pop: pop };
  }

  function onKey(e) {
    if (e.key === "Escape") finish();
    else if (e.key === "ArrowRight" || e.key === "Enter") next();
    else if (e.key === "ArrowLeft") prev();
  }

  function render() {
    if (!els) return;
    var step = steps[idx];
    var target = step.center ? null : visibleTarget(step.sel);

    // dots
    var dots = "";
    for (var i = 0; i < steps.length; i++) dots += '<span class="tour-dot' + (i === idx ? " on" : "") + '"></span>';

    var isLast = idx === steps.length - 1;
    els.pop.innerHTML =
      '<div class="tour-emoji">' + step.emoji + "</div>" +
      "<h4>" + step.title + "</h4>" +
      "<p>" + step.text + "</p>" +
      '<div class="tour-foot">' +
        '<div class="tour-dots">' + dots + "</div>" +
        '<div class="tour-btns">' +
          (idx > 0 ? '<button class="tour-btn tour-btn-ghost" data-act="prev">Назад</button>' : "") +
          '<button class="tour-btn tour-btn-primary" data-act="next">' + (isLast ? "Начать" : "Далее") + "</button>" +
        "</div>" +
      "</div>";
    els.pop.querySelector('[data-act="next"]').addEventListener("click", next);
    var pb = els.pop.querySelector('[data-act="prev"]');
    if (pb) pb.addEventListener("click", prev);

    var W = window.innerWidth, H = window.innerHeight;

    if (!target) {
      els.spot.classList.add("hidden");
      els.pop.classList.add("centered");
    } else {
      els.pop.classList.remove("centered");
      var r = target.getBoundingClientRect();
      var pad = 8;
      els.spot.classList.remove("hidden");
      els.spot.style.top = (r.top - pad) + "px";
      els.spot.style.left = (r.left - pad) + "px";
      els.spot.style.width = (r.width + pad * 2) + "px";
      els.spot.style.height = (r.height + pad * 2) + "px";

      var pw = els.pop.offsetWidth, ph = els.pop.offsetHeight, gap = 14, top, left;
      if (W - r.right > pw + gap + 16) {            // place to the right (desktop sidebar)
        left = r.right + gap; top = r.top;
      } else if (H - r.bottom > ph + gap + 16) {    // below
        top = r.bottom + gap; left = r.left;
      } else {                                       // above (mobile bottom-nav)
        top = r.top - ph - gap; left = r.left;
      }
      els.pop.style.left = clamp(left, 12, W - pw - 12) + "px";
      els.pop.style.top = clamp(top, 12, H - ph - 12) + "px";
    }
    requestAnimationFrame(function () { els.pop.classList.add("show"); });
  }

  function next() { if (idx < steps.length - 1) { idx++; els.pop.classList.remove("show"); render(); } else finish(); }
  function prev() { if (idx > 0) { idx--; els.pop.classList.remove("show"); render(); } }

  function finish() {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch (e) {}
    window.removeEventListener("resize", render);
    window.removeEventListener("keydown", onKey);
    if (els) {
      [els.mask, els.spot, els.skip, els.pop].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
      els = null;
    }
  }

  function start(role) {
    if (els) return;
    role = role || window.PINGLY_ROLE || "tutor";
    steps = STEPS[role] || STEPS.tutor;
    idx = 0;
    els = build();
    render();
  }

  window.startPinglyTour = function () { start(window.PINGLY_ROLE); };

  document.addEventListener("DOMContentLoaded", function () {
    var seen = false;
    try { seen = !!localStorage.getItem(STORAGE_KEY); } catch (e) {}
    if (seen || !window.PINGLY_ROLE) return;
    // only auto-run where the cabinet nav exists
    if (!document.querySelector(".nav, .bottom-nav")) return;
    setTimeout(function () { start(window.PINGLY_ROLE); }, 500);
  });
})();
