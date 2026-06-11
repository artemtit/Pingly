/* ============================================================
   Pingly landing — interactivity
   Vanilla JS: chat demo, scroll reveal, tabs, carousel,
   tilt, magnetic CTA, scroll progress.
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

  /* ---------------- Step number tick (00 → NN) ---------------- */
  document.querySelectorAll('.step-n[data-target]').forEach(function (el) {
    var target = parseInt(el.getAttribute('data-target'), 10);
    if (reduceMotion || !('IntersectionObserver' in window)) return;
    var card = el.closest('[data-reveal]') || el;
    var tickIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        tickIO.disconnect();
        var cur = 0;
        var iv = setInterval(function () {
          cur++;
          el.textContent = (cur < 10 ? '0' : '') + cur;
          if (cur >= target) clearInterval(iv);
        }, 180);
      });
    }, { threshold: 0.4 });
    tickIO.observe(card);
  });

  /* ---------------- 3D tilt on step cards ---------------- */
  if (!reduceMotion && !isTouch) {
    document.querySelectorAll('[data-tilt]').forEach(function (card) {
      var rect = null;
      card.addEventListener('mouseenter', function () {
        rect = card.getBoundingClientRect();
        card.style.willChange = 'transform';
      });
      card.addEventListener('mousemove', function (ev) {
        if (!rect) rect = card.getBoundingClientRect();
        var px = (ev.clientX - rect.left) / rect.width - 0.5;
        var py = (ev.clientY - rect.top) / rect.height - 0.5;
        card.style.transform =
          'perspective(700px) rotateY(' + (px * 5).toFixed(2) + 'deg)' +
          ' rotateX(' + (-py * 5).toFixed(2) + 'deg) translateY(-2px)';
      });
      card.addEventListener('mouseleave', function () {
        rect = null;
        card.style.transform = '';
        card.style.willChange = '';
      });
    });
  }

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

      replyBubble.textContent = yes ? '✅ Буду' : '❌ Отменяю';
      finalBubble.textContent = yes ? 'Отлично! Жду тебя в 15:00 👋' : 'Понял, передам репетитору 👌';
      noteText.textContent = yes
        ? 'Маша подтвердила занятие в 15:00 ✅'
        : 'Маша отменила занятие в 15:00 — слот свободен';
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

  /* ---------------- Reviews carousel ---------------- */
  (function carousel() {
    var track = document.getElementById('carTrack');
    if (!track) return;
    var slides = Array.prototype.slice.call(track.children);
    var dots = Array.prototype.slice.call(document.querySelectorAll('.car-dot'));
    var root = track.closest('.carousel');
    var current = 0;
    var timer = null;

    function go(i) {
      current = (i + slides.length) % slides.length;
      track.style.transform = 'translateX(-' + current * 100 + '%)';
      slides.forEach(function (s, k) {
        s.classList.toggle('active', k === current);
        s.setAttribute('aria-hidden', k === current ? 'false' : 'true');
      });
      dots.forEach(function (d, k) { d.classList.toggle('active', k === current); });
    }

    function start() {
      if (reduceMotion || timer) return;
      timer = setInterval(function () { go(current + 1); }, 5000);
    }
    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
    }

    dots.forEach(function (d, k) {
      d.addEventListener('click', function () { stop(); go(k); start(); });
    });
    root.addEventListener('mouseenter', stop);
    root.addEventListener('mouseleave', start);
    root.addEventListener('focusin', stop);
    root.addEventListener('focusout', start);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop(); else start();
    });

    go(0);
    // autoplay only while the carousel is actually on screen
    if ('IntersectionObserver' in window) {
      var carIO = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) start(); else stop();
        });
      }, { threshold: 0.3 });
      carIO.observe(root);
    } else {
      start();
    }
  })();
})();
