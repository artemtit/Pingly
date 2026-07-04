/* ============================================================
   Pingly landing — interactivity
   Vanilla JS: chat demo, scroll reveal, product tour (sticky
   scene), autopilot day timeline, live stats counter,
   scrollspy, mobile menu, magnetic CTA.
   All animation honors prefers-reduced-motion.
   ============================================================ */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var isTouch = window.matchMedia('(hover: none)').matches;

  /* ---------------- Nav shadow on scroll ---------------- */
  var nav = document.querySelector('.nav');
  if (nav) {
    var navCheck = function () {
      nav.classList.toggle('scrolled', window.scrollY > 8);
    };
    window.addEventListener('scroll', navCheck, { passive: true });
    navCheck();
  }

  /* ---------------- Reveal on scroll ---------------- */
  var revealEls = Array.prototype.slice.call(document.querySelectorAll('[data-reveal]'));
  if (revealEls.length) {
    if ('IntersectionObserver' in window && !reduceMotion) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add('in');
            io.unobserve(e.target);
          }
        });
      }, { rootMargin: '0px 0px -10% 0px', threshold: 0.1 });
      revealEls.forEach(function (el) { io.observe(el); });
      // safety net: never leave content hidden
      setTimeout(function () {
        revealEls.forEach(function (el) { el.classList.add('in'); });
      }, 4000);
    } else {
      revealEls.forEach(function (el) { el.classList.add('in'); });
    }
  }

  /* ---------------- Mobile menu (burger + fullscreen overlay) ---------------- */
  (function mobileMenu() {
    var burger = document.getElementById('navBurger');
    var menu = document.getElementById('navMenu');
    if (!burger || !menu) return;
    var open = false;

    function setOpen(value, restoreFocus) {
      open = value;
      burger.setAttribute('aria-expanded', value ? 'true' : 'false');
      burger.setAttribute('aria-label', value ? 'Закрыть меню' : 'Открыть меню');
      menu.hidden = !value;
      document.body.style.overflow = value ? 'hidden' : '';
      if (value) {
        var first = menu.querySelector('a');
        if (first) first.focus();
      } else if (restoreFocus) {
        burger.focus();
      }
    }

    burger.addEventListener('click', function () { setOpen(!open, true); });
    menu.addEventListener('click', function (ev) {
      var link = ev.target && ev.target.closest ? ev.target.closest('a') : null;
      if (link) setOpen(false, false);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && open) setOpen(false, true);
    });
    window.addEventListener('resize', function () {
      if (open && window.innerWidth > 860) setOpen(false, false);
    });
    window.addEventListener('pageshow', function (ev) {
      setOpen(false, false);
      var navEntry = performance.getEntriesByType ? performance.getEntriesByType('navigation')[0] : null;
      if (location.pathname === '/' && !location.hash && (ev.persisted || (navEntry && navEntry.type === 'back_forward'))) {
        window.scrollTo(0, 0);
      }
    });
    window.addEventListener('pagehide', function () {
      if (open) setOpen(false, false);
      document.body.style.overflow = '';
    });
  })();

  /* ---------------- Magnetic CTA buttons ---------------- */
  if (!reduceMotion && !isTouch) {
    var magnets = Array.prototype.slice.call(document.querySelectorAll('.magnetic'));
    if (magnets.length) {
      var magTicking = false;
      var lastX = 0, lastY = 0;
      var applyMagnets = function () {
        magTicking = false;
        magnets.forEach(function (btn) {
          var r = btn.getBoundingClientRect();
          var cx = r.left + r.width / 2;
          var cy = r.top + r.height / 2;
          var dx = lastX - cx;
          var dy = lastY - cy;
          // active zone: button itself + 50px around it
          var inside = Math.abs(dx) < r.width / 2 + 50 && Math.abs(dy) < r.height / 2 + 50;
          if (inside) {
            btn.style.transform = 'translate(' + (dx * 0.12).toFixed(1) + 'px,' + (dy * 0.18).toFixed(1) + 'px)';
          } else if (btn.style.transform) {
            btn.style.transform = '';
          }
        });
      };
      document.addEventListener('mousemove', function (ev) {
        lastX = ev.clientX;
        lastY = ev.clientY;
        if (!magTicking) {
          magTicking = true;
          requestAnimationFrame(applyMagnets);
        }
      }, { passive: true });
    }
  }

  /* ---------------- Hero parallax: contextual cards only, ±6px max ----------------
     Disabled for touch devices and prefers-reduced-motion. */
  if (!reduceMotion && !isTouch) {
    (function heroParallax() {
      var hero = document.querySelector('.hero');
      var cards = Array.prototype.slice.call(document.querySelectorAll('.float-card'));
      if (!hero || !cards.length) return;
      var ticking = false, px = 0, py = 0;
      var apply = function () {
        ticking = false;
        cards.forEach(function (card, i) {
          var k = i === 0 ? 12 : -10; // opposite drift; ±0.5 * k = 6px max
          card.style.setProperty('--fx', (px * k).toFixed(1) + 'px');
          card.style.setProperty('--fy', (py * k * 0.7).toFixed(1) + 'px');
        });
      };
      hero.addEventListener('mousemove', function (ev) {
        var r = hero.getBoundingClientRect();
        px = ev.clientX / r.width - 0.5;
        py = (ev.clientY - r.top) / r.height - 0.5;
        if (!ticking) { ticking = true; requestAnimationFrame(apply); }
      }, { passive: true });
      hero.addEventListener('mouseleave', function () {
        cards.forEach(function (card) {
          card.style.setProperty('--fx', '0px');
          card.style.setProperty('--fy', '0px');
        });
      });
    })();
  }

  /* ---------------- Hero chat demo ---------------- */
  (function chatDemo() {
    var demo = document.getElementById('chatDemo');
    if (!demo) return;

    var steps = {};
    demo.querySelectorAll('[data-step]').forEach(function (el) {
      steps[el.getAttribute('data-step')] = el;
    });
    var btnYes = document.getElementById('chatYes');
    var btnNo = document.getElementById('chatNo');
    var replyBubble = document.getElementById('chatReply');
    var finalBubble = document.getElementById('chatFinal');
    var noteText = document.getElementById('chatNoteText');
    var noteCard = steps.notify;
    var replay = document.getElementById('chatReplay');
    // floating contextual cards around the device — driven by the demo state
    var floatWhen = document.getElementById('floatWhen');
    var floatPush = document.getElementById('floatPush');
    var floatPushTitle = document.getElementById('floatPushTitle');
    var timers = [];
    var answered = false;

    function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
    function clearTimers() { timers.forEach(clearTimeout); timers = []; }
    function show(name) { if (steps[name]) steps[name].classList.add('show'); }
    function hide(name) { if (steps[name]) steps[name].classList.remove('show'); }
    function floatShow(el) { if (el) el.classList.add('show'); }
    function floatHide(el) { if (el) el.classList.remove('show'); }

    function answer(choice) {
      if (answered) return;
      answered = true;
      clearTimers();
      var yes = choice === 'yes';
      btnYes.classList.toggle('pressed', yes);
      btnNo.classList.toggle('pressed', !yes);
      btnYes.classList.remove('pulse');
      btnNo.classList.remove('pulse');
      btnYes.disabled = btnNo.disabled = true;

      replyBubble.textContent = yes ? 'Буду' : 'Отменяю';
      finalBubble.textContent = yes ? 'Отлично! Жду тебя в 15:00.' : 'Понял, передам репетитору.';
      noteText.textContent = yes
        ? 'Маша подтвердила занятие в 15:00.'
        : 'Маша отменила занятие в 15:00 — слот свободен.';
      noteCard.classList.toggle('cancel', !yes);
      if (floatPushTitle) floatPushTitle.textContent = yes ? 'Маша подтвердила' : 'Маша отменила';
      if (floatPush) floatPush.classList.toggle('cancel', !yes);

      later(function () { show('reply'); }, 350);
      later(function () { show('typing2'); }, 1100);
      later(function () { hide('typing2'); show('final'); }, 2100);
      later(function () { show('notify'); }, 2900);
      later(function () { floatShow(floatPush); }, 3100);
      later(function () { replay.classList.add('show'); }, 3600);
    }

    function reset() {
      clearTimers();
      answered = false;
      Object.keys(steps).forEach(function (k) { steps[k].classList.remove('show'); });
      replay.classList.remove('show');
      btnYes.disabled = btnNo.disabled = false;
      btnYes.classList.remove('pressed', 'pulse');
      btnNo.classList.remove('pressed', 'pulse');
      noteCard.classList.remove('cancel');
      floatHide(floatWhen);
      floatHide(floatPush);
      if (floatPush) floatPush.classList.remove('cancel');
      if (floatPushTitle) floatPushTitle.textContent = 'Маша подтвердила';
    }

    function play() {
      reset();
      later(function () { show('typing1'); }, 500);
      later(function () { hide('typing1'); show('msg1'); }, 1700);
      later(function () { floatShow(floatWhen); }, 1950);
      later(function () {
        show('actions');
        btnYes.classList.add('pulse');
        btnNo.classList.add('pulse');
      }, 2500);
      // if visitor doesn't click, the demo answers for them
      later(function () { answer('yes'); }, 6200);
    }

    function showFinalState() {
      ['msg1', 'actions', 'reply', 'final', 'notify'].forEach(show);
      btnYes.classList.add('pressed');
      btnYes.disabled = btnNo.disabled = true;
      replay.classList.add('show');
      floatShow(floatWhen);
      floatShow(floatPush);
    }

    btnYes.addEventListener('click', function () { answer('yes'); });
    btnNo.addEventListener('click', function () { answer('no'); });
    replay.addEventListener('click', play);

    if (reduceMotion) {
      showFinalState();
      replay.addEventListener('click', function () { reset(); showFinalState(); });
      return;
    }

    // start once the phone is actually on screen
    if ('IntersectionObserver' in window) {
      var seen = false;
      var demoIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !seen) {
            seen = true;
            demoIO.disconnect();
            play();
          }
        });
      }, { threshold: 0.4 });
      demoIO.observe(demo);
    } else {
      play();
    }
  })();

  /* ---------------- Product tour (sticky scene, scroll-driven) ---------------- */
  (function productTour() {
    var tour = document.getElementById('tour');
    var scene = document.getElementById('tourScene');
    if (!tour || !scene || !('IntersectionObserver' in window)) return;

    var items = Array.prototype.slice.call(tour.querySelectorAll('.tour-item'));
    var railFill = document.getElementById('tourRailFill');
    var mq = window.matchMedia('(min-width: 861px)');
    var slides = [];
    var current = 0;

    // Desktop: move each feature's mini-UI into the sticky scene (single source
    // of truth, no duplicated markup). Mobile: move it back inline.
    function toScene() {
      if (slides.length) return;
      items.forEach(function (item) {
        var art = item.querySelector('.tour-art');
        var slide = document.createElement('div');
        slide.className = 'tour-slide';
        while (art.firstChild) slide.appendChild(art.firstChild);
        scene.appendChild(slide);
        slides.push(slide);
      });
      tour.classList.add('js-tour');
      setActive(current);
    }

    function toInline() {
      if (!slides.length) return;
      slides.forEach(function (slide, i) {
        var art = items[i].querySelector('.tour-art');
        while (slide.firstChild) art.appendChild(slide.firstChild);
      });
      slides = [];
      scene.innerHTML = '';
      tour.classList.remove('js-tour');
    }

    function setActive(i) {
      current = i;
      items.forEach(function (item, k) { item.classList.toggle('active', k === i); });
      slides.forEach(function (slide, k) { slide.classList.toggle('active', k === i); });
      if (railFill) railFill.style.transform = 'scaleY(' + ((i + 1) / items.length) + ')';
    }

    // A narrow band around the viewport middle decides the active step.
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) setActive(items.indexOf(e.target));
      });
    }, { rootMargin: '-45% 0px -45% 0px', threshold: 0 });
    items.forEach(function (item) { io.observe(item); });

    function apply() { if (mq.matches) toScene(); else toInline(); }
    if (mq.addEventListener) mq.addEventListener('change', apply);
    else if (mq.addListener) mq.addListener(apply);
    apply();
  })();

  /* ---------------- Autopilot: day timeline fills as it scrolls into view ----------------
     IntersectionObserver ratio → --fill custom property (no scroll listeners).
     The fill is monotonic (never rewinds); each stop lights up once the line
     reaches its dot. Reduced motion / no IO: everything fully drawn. */
  (function autopilot() {
    var day = document.getElementById('autoDay');
    if (!day) return;
    var stops = Array.prototype.slice.call(day.querySelectorAll('.auto-stop'));
    // dot positions along the track (fractions of its length), with a lead-in
    var marks = [0.15, 0.48, 0.8];

    function complete() {
      day.style.setProperty('--fill', '1');
      stops.forEach(function (s) { s.classList.add('on'); });
    }

    if (reduceMotion || !('IntersectionObserver' in window)) {
      complete();
      return;
    }

    var thresholds = [];
    for (var i = 0; i <= 20; i++) thresholds.push(i / 20);
    var current = 0;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        // the line completes once ~85% of the timeline is visible
        var p = Math.min(1, e.intersectionRatio / 0.85);
        if (p <= current) return;
        current = p;
        day.style.setProperty('--fill', p.toFixed(2));
        stops.forEach(function (s, k) { if (p >= marks[k]) s.classList.add('on'); });
        if (p >= 1) io.disconnect();
      });
    }, { threshold: thresholds });
    io.observe(day);
  })();

  /* ---------------- Live reminders counter (honest number from the DB) ---------------- */
  (function statsCounter() {
    var box = document.getElementById('proofCounter');
    var num = document.getElementById('reminderCount');
    if (!box || !num || !window.fetch) {
      if (box) { box.hidden = true; }
      return;
    }
    var sep = document.getElementById('proofSep');

    function hide() {
      box.hidden = true;
      if (sep) sep.hidden = true;
    }
    function fmt(v) { return v.toLocaleString('ru-RU'); }
    function show(v) {
      box.classList.remove('loading');
      if (reduceMotion || !('IntersectionObserver' in window)) {
        num.textContent = fmt(v);
        return;
      }
      num.textContent = fmt(0);
      var started = false;
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting || started) return;
          started = true;
          io.disconnect();
          var t0 = null;
          var tick = function (ts) {
            if (t0 === null) t0 = ts;
            var p = Math.min(1, (ts - t0) / 900);
            var eased = 1 - Math.pow(1 - p, 3);
            num.textContent = fmt(Math.round(v * eased));
            if (p < 1) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        });
      }, { threshold: 0.6 });
      io.observe(box);
    }

    // Honest counter: real number or nothing. A hung request drops the skeleton.
    var failsafe = setTimeout(hide, 6000);
    fetch('/api/public/stats', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) {
        clearTimeout(failsafe);
        var v = d && d.reminders_sent;
        if (typeof v !== 'number' || v < 10) { hide(); return; }
        show(v);
      })
      .catch(function () { clearTimeout(failsafe); hide(); });
  })();

  /* ---------------- Scrollspy: highlight the current section in the nav ---------------- */
  (function scrollSpy() {
    if (!('IntersectionObserver' in window)) return;
    var links = Array.prototype.slice.call(document.querySelectorAll('.nav-links a.navlink[href^="#"]'));
    if (!links.length) return;
    var byId = {};
    links.forEach(function (link) { byId[link.getAttribute('href').slice(1)] = link; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var link = byId[e.target.id]; // sections without a nav link clear the highlight
        links.forEach(function (l) { l.classList.toggle('active', l === link); });
      });
    }, { rootMargin: '-35% 0px -55% 0px', threshold: 0 });
    Array.prototype.slice.call(document.querySelectorAll('section[id]')).forEach(function (t) { io.observe(t); });
  })();
})();
