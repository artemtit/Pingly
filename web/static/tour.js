/* Pingly — guided product tour. Vanilla JS, no deps. */
(function () {
  "use strict";

  var STORAGE_KEY = "pingly_tour_v2";

  // Same Lucide paths as the sidebar nav (layout.html icon macro), so each tour
  // step shows the icon of the section it points at.
  var ICONS = {
    sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>',
    zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>',
    calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "calendar-clock": '<path d="M16 14v2.2l1.6 1"/><path d="M16 2v4"/><path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M3 10h5"/><path d="M8 2v4"/><circle cx="16" cy="16" r="6"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "russian-ruble": '<path d="M6 11h8a4 4 0 0 0 0-8H9v18"/><path d="M6 15h8"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
    "graduation-cap": '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>'
  };

  function iconSvg(name) {
    return '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || ICONS.sparkles) + "</svg>";
  }

  var STEPS = {
    tutor: [
      { center: true, icon: "sparkles", title: "Добро пожаловать в Pingly!",
        text: "Покажу за полминуты, что где в кабинете. Можно пропустить в любой момент." },
      { sel: 'a[href="/tutor"]', icon: "zap", title: "Обзор",
        text: "Главный экран: статистика, ближайшие занятия и задания, которые ученики сдали на проверку." },
      { sel: 'a[href="/tutor/students"]', icon: "users", title: "Ученики",
        text: "Здесь добавляешь учеников прямо на сайте и ведёшь их карточки — предмет, цель, заметки, история." },
      { sel: 'a[href="/tutor/calendar"]', icon: "calendar", title: "Календарь",
        text: "Все занятия наглядно. Переключай день, неделю и месяц, переноси и отменяй уроки." },
      { sel: 'a[href="/tutor/schedule"]', icon: "calendar-clock", title: "Расписание",
        text: "Настрой повторяющиеся занятия один раз — бот сам напомнит ученикам за 2 часа до урока." },
      { sel: 'a[href="/tutor/homework"]', icon: "circle-check", title: "Задания",
        text: "Выдавай домашние задания и проверяй сданное — всё в одном месте." },
      { sel: 'a[href="/tutor/finance"]', icon: "russian-ruble", title: "Финансы",
        text: "Сколько занятий проведено и на какую сумму, кто сколько должен — всё считается само." },
      { sel: 'a[href="/tutor/requests"]', icon: "inbox", title: "Заявки",
        text: "Заявки на занятия с твоей публичной страницы записи приходят сюда." },
      { sel: 'a[href="/tutor/settings"]', icon: "settings", title: "Настройки",
        text: "Профиль, тема оформления и ссылка на бота." },
      { center: true, icon: "flag", title: "Готово!",
        text: "Это весь кабинет. Повторить обзор можно в любой момент — кнопка «Обзор» внизу меню." }
    ],
    student: [
      { center: true, icon: "sparkles", title: "Добро пожаловать в Pingly!",
        text: "Быстрый обзор твоего кабинета — займёт полминуты." },
      { sel: 'a[href="/student"]', icon: "graduation-cap", title: "Главная",
        text: "Ближайшее занятие и кнопки «Буду / Отменяю»." },
      { sel: 'a[href="/student/calendar"]', icon: "calendar", title: "Календарь",
        text: "Все твои занятия — день, неделя, месяц." },
      { sel: 'a[href="/student/homework"]', icon: "circle-check", title: "Задания",
        text: "Домашние задания от репетитора и их статус." },
      { center: true, icon: "flag", title: "Готово!",
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
      '<div class="tour-ic">' + iconSvg(step.icon) + "</div>" +
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
