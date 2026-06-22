/* ============================================================
   Pingly cabinet — shared UI runtime
   Toasts, clipboard, animated counters, relative time,
   card stagger, button loading, modal behavior, sidebar
   collapse, micro-confetti. Page-specific logic stays in
   each template and calls window.pingly.*
   ============================================================ */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var pingly = window.pingly = { reduceMotion: reduceMotion };

  /* ---------------- Toasts ---------------- */
  var toastBox = null;
  function ensureToastBox() {
    if (!toastBox) {
      toastBox = document.createElement('div');
      toastBox.className = 'toasts';
      toastBox.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastBox);
    }
    return toastBox;
  }
  /** type: success | error | info | action */
  pingly.toast = function (msg, type, sticky) {
    type = type || 'success';
    var box = ensureToastBox();
    var t = document.createElement('div');
    t.className = 'toast toast-' + type;
    if (type === 'error') t.setAttribute('role', 'alert');
    var icons = { success: '✓', error: '✕', info: 'i', action: '★' };
    t.innerHTML = '<span class="toast-ic" aria-hidden="true">' + (icons[type] || '✓') + '</span><span class="toast-msg"></span><button class="toast-x" aria-label="Закрыть">✕</button>';
    t.querySelector('.toast-msg').textContent = msg;
    box.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('in'); });
    function dismiss() {
      if (t.dataset.gone) return;
      t.dataset.gone = '1';
      t.classList.remove('in');
      setTimeout(function () { t.remove(); }, 350);
    }
    t.querySelector('.toast-x').addEventListener('click', dismiss);
    if (type !== 'error' && !sticky) setTimeout(dismiss, 4000);
    return dismiss;
  };

  /* ---------------- Clipboard ---------------- */
  pingly.copy = function (text, msg, type) {
    function ok() { if (msg) pingly.toast(msg, type || 'success'); }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); ok(); } catch (e) { pingly.toast('Не удалось скопировать', 'error'); }
      ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok, fallback);
    } else fallback();
  };

  /* ---------------- Number formatting + counters ---------------- */
  pingly.fmt = function (n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  };
  function tickCounters() {
    document.querySelectorAll('[data-count]').forEach(function (el) {
      var target = parseFloat(el.getAttribute('data-count'));
      if (isNaN(target)) return;
      var suffix = el.getAttribute('data-suffix') || '';
      if (reduceMotion || target === 0) {
        el.textContent = pingly.fmt(target) + suffix;
        return;
      }
      var t0 = null;
      var dur = 700;
      function frame(ts) {
        if (!t0) t0 = ts;
        var p = Math.min(1, (ts - t0) / dur);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = pingly.fmt(target * eased) + suffix;
        if (p < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  /* ---------------- Relative time («через 2 ч») ---------------- */
  function relLabel(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return null;
    var diffMin = Math.round((d - Date.now()) / 60000);
    var sameDay = new Date().toDateString() === d.toDateString();
    var tomorrow = new Date(Date.now() + 86400000).toDateString() === d.toDateString();
    var hm = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    if (diffMin <= 0) return { text: 'сейчас', hot: true, today: sameDay };
    if (diffMin < 60) return { text: 'через ' + diffMin + ' мин', hot: true, today: sameDay };
    if (diffMin < 60 * 12) {
      var h = Math.round(diffMin / 60);
      var word = (h % 10 === 1 && h % 100 !== 11) ? 'час' : (h % 10 >= 2 && h % 10 <= 4 && (h % 100 < 12 || h % 100 > 14)) ? 'часа' : 'часов';
      return { text: 'через ' + h + ' ' + word, hot: h <= 3, today: sameDay };
    }
    if (sameDay) return { text: 'сегодня в ' + hm, hot: false, today: true };
    if (tomorrow) return { text: 'завтра в ' + hm, hot: false, today: false };
    return { text: d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) + ' в ' + hm, hot: false, today: false };
  }
  function updateRelTimes() {
    document.querySelectorAll('[data-reltime]').forEach(function (el) {
      var r = relLabel(el.getAttribute('data-reltime'));
      if (!r) return;
      el.textContent = r.text;
      el.classList.toggle('rel-hot', r.hot);
      var row = el.closest('[data-rel-row]');
      if (row) row.classList.toggle('is-today', r.today);
    });
  }
  pingly.relLabel = relLabel;

  /* ---------------- Card stagger on load ---------------- */
  function staggerCards() {
    if (reduceMotion) return;
    var cards = document.querySelectorAll('.main .card, .main .stat-card');
    cards.forEach(function (c, i) {
      if (i > 0) c.style.animationDelay = Math.min(i * 55, 440) + 'ms';
    });
  }

  /* ---------------- Buttons: loading on submit ---------------- */
  // Bubble phase (not capture) so an inline `onsubmit="return confirm(...)"` runs
  // first: if the user clicks «Нет» the submit is cancelled (defaultPrevented),
  // and we must NOT disable the button — otherwise it spins forever with no
  // navigation to reset it.
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented) return;
    var form = e.target;
    // Hard guard against double-submit (e.g. double-click создавало два занятия).
    // A real submit navigates away, so the flag is gone on the next page load;
    // a confirm()-cancelled submit hits the defaultPrevented return above first.
    if (form.dataset.submitting) { e.preventDefault(); return; }
    form.dataset.submitting = '1';
    // Auto-expire the guard. A real submit navigates away long before this fires;
    // but a form that stays on the page (target=_blank, download, a handler that
    // doesn't navigate) must NOT be bricked forever — re-arm it after a beat.
    var rearm = setTimeout(function () { delete form.dataset.submitting; }, 2500);
    if (form.dataset.noLoading !== undefined) return;
    var btn = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
    if (!btn || !btn.classList.contains('btn')) return;
    // defer so the click value still posts
    setTimeout(function () {
      btn.classList.add('btn-loading');
      btn.disabled = true;
    }, 0);
    // Fallback un-stick: if we're still here after 4s the navigation never
    // happened, so clear the spinner instead of leaving it spinning forever.
    setTimeout(function () {
      clearTimeout(rearm);
      delete form.dataset.submitting;
      btn.classList.remove('btn-loading');
      btn.disabled = false;
    }, 4000);
  }, false);

  // When the page is restored from the back-forward cache (e.g. the user hit
  // «Назад» after being sent to the payment page and cancelling), buttons left
  // in their loading state stay frozen with a spinner forever. Reset them — and
  // re-arm the double-submit guard — every time the page is shown.
  window.addEventListener('pageshow', function () {
    document.querySelectorAll('.btn-loading').forEach(function (b) {
      b.classList.remove('btn-loading');
      b.disabled = false;
    });
    document.querySelectorAll('form[data-submitting]').forEach(function (f) {
      delete f.dataset.submitting;
    });
  });

  /* ---------------- Modals: esc, backdrop, autofocus ---------------- */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.modal-backdrop.open').forEach(function (m) { m.classList.remove('open'); });
  });
  document.addEventListener('click', function (e) {
    if (e.target.classList && e.target.classList.contains('modal-backdrop')) {
      e.target.classList.remove('open');
    }
  });
  pingly.openModal = function (id) {
    var m = document.getElementById(id);
    if (!m) return;
    m.classList.add('open');
    var f = m.querySelector('input:not([type=hidden]), select, textarea, button');
    if (f) setTimeout(function () { f.focus(); }, 50);
  };
  pingly.closeModal = function (id) {
    var m = document.getElementById(id);
    if (m) m.classList.remove('open');
  };
  // simple focus containment inside an open modal
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    var m = document.querySelector('.modal-backdrop.open .modal');
    if (!m) return;
    var items = m.querySelectorAll('a[href], button:not([disabled]), input:not([type=hidden]), select, textarea');
    if (!items.length) return;
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  /* ---------------- Sidebar collapse ---------------- */
  function initSidebar() {
    var btn = document.getElementById('sb-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var collapsed = doc.classList.toggle('sb-collapsed');
      try { localStorage.setItem('pingly_sb', collapsed ? '1' : ''); } catch (e) {}
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
  }

  /* ---------------- Micro-confetti (mass payment feedback) ---------------- */
  pingly.confetti = function (x, y) {
    if (reduceMotion) return;
    var colors = ['#F97316', '#22C55E', '#3B82F6', '#FDBA74', '#86EFAC'];
    for (var i = 0; i < 14; i++) {
      var p = document.createElement('i');
      p.className = 'confetti';
      p.style.left = x + 'px';
      p.style.top = y + 'px';
      p.style.background = colors[i % colors.length];
      var ang = Math.random() * Math.PI * 2;
      var dist = 40 + Math.random() * 60;
      p.style.setProperty('--dx', Math.cos(ang) * dist + 'px');
      p.style.setProperty('--dy', (Math.sin(ang) * dist - 40) + 'px');
      p.style.setProperty('--rot', (Math.random() * 360 - 180) + 'deg');
      document.body.appendChild(p);
      p.addEventListener('animationend', function () { this.remove(); });
    }
  };

  /* ---------------- Boot ---------------- */
  function init() {
    staggerCards();
    tickCounters();
    updateRelTimes();
    setInterval(updateRelTimes, 60000);
    initSidebar();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
