/* ============================================================
   Pingly landing — interactivity
   Vanilla JS: chat demo, scroll reveal, tabs, mobile menu,
   magnetic CTA, scroll progress.
   All animation honors prefers-reduced-motion.
   ============================================================ */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var isTouch = window.matchMedia('(hover: none)').matches;

  /* ---------------- Scroll progress bar ---------------- */
  var progressFill = document.getElementById('scrollProgress');
  if (progressFill) {
    var progressTicking = false;
    var updateProgress = function () {
      var max = doc.scrollHeight - window.innerHeight;
      var p = max > 0 ? window.scrollY / max : 0;
      progressFill.style.transform = 'scaleX(' + Math.min(1, Math.max(0, p)) + ')';
      progressTicking = false;
    };
    window.addEventListener('scroll', function () {
      if (!progressTicking) {
        progressTicking = true;
        requestAnimationFrame(updateProgress);
      }
    }, { passive: true });
    updateProgress();
  }

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
    var timers = [];
    var answered = false;

    function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
    function clearTimers() { timers.forEach(clearTimeout); timers = []; }
    function show(name) { if (steps[name]) steps[name].classList.add('show'); }
    function hide(name) { if (steps[name]) steps[name].classList.remove('show'); }

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

      later(function () { show('reply'); }, 350);
      later(function () { show('typing2'); }, 1100);
      later(function () { hide('typing2'); show('final'); }, 2100);
      later(function () { show('notify'); }, 2900);
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
    }

    function play() {
      reset();
      later(function () { show('typing1'); }, 500);
      later(function () { hide('typing1'); show('msg1'); }, 1700);
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

  /* ---------------- Features tabs ---------------- */
  (function featureTabs() {
    var bar = document.getElementById('ftabs');
    if (!bar) return;
    var tabs = Array.prototype.slice.call(bar.querySelectorAll('.ftab'));
    var panels = Array.prototype.slice.call(document.querySelectorAll('.fpanel'));
    var indicator = document.getElementById('ftabInd');
    var current = 0;

    function moveIndicator(tab) {
      indicator.style.width = tab.offsetWidth + 'px';
      indicator.style.transform = 'translateX(' + tab.offsetLeft + 'px)';
    }

    function select(i, focus) {
      if (i === current) return;
      var prev = current;
      current = i;
      tabs.forEach(function (t, k) {
        var on = k === i;
        t.classList.toggle('active', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
      });
      panels[prev].classList.remove('active');
      panels[prev].classList.add('leaving');
      panels[i].classList.add('active');
      setTimeout(function () { panels[prev].classList.remove('leaving'); }, 350);
      moveIndicator(tabs[i]);
      if (focus) tabs[i].focus();
      tabs[i].scrollIntoView({ block: 'nearest', inline: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { select(i); });
    });
    bar.addEventListener('keydown', function (ev) {
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
      ev.preventDefault();
      var next = ev.key === 'ArrowRight' ? (current + 1) % tabs.length : (current - 1 + tabs.length) % tabs.length;
      select(next, true);
    });

    moveIndicator(tabs[0]);
    window.addEventListener('resize', function () { moveIndicator(tabs[current]); });
    // fonts can shift widths after first paint
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () { moveIndicator(tabs[current]); });
    }
  })();
})();
