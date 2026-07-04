/* Pingly — AI assistant chat for the tutor cabinet. Vanilla JS, no deps.
   Talks to POST /api/ai/chat; history lives in sessionStorage (per tab). */
(function () {
  "use strict";

  var mount = document.getElementById("ai-assistant");
  if (!mount) return;

  var HISTORY_KEY = "pingly_ai_history";
  var MAX_HISTORY = 30;

  var SPARKLES =
    '<svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/></svg>';
  var CLOSE =
    '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  var SEND =
    '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/></svg>';

  var SUGGESTIONS = [
    "Составь план занятия",
    "Придумай домашнее задание",
    "Напиши сообщение ученику",
    "Как работает Pingly?"
  ];

  var history = [];
  try { history = JSON.parse(sessionStorage.getItem(HISTORY_KEY)) || []; } catch (e) {}

  function saveHistory() {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-MAX_HISTORY))); } catch (e) {}
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // --- Build UI ---
  var fab = document.createElement("button");
  fab.className = "ai-fab";
  fab.type = "button";
  fab.setAttribute("aria-label", "ИИ-помощник");
  fab.innerHTML = SPARKLES;

  var panel = document.createElement("div");
  panel.className = "ai-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "ИИ-помощник");
  panel.innerHTML =
    '<div class="ai-head">' +
      '<span class="ai-head-ic">' + SPARKLES + "</span>" +
      '<div class="ai-head-txt"><b>Помощник</b><span>план урока · ДЗ · сообщение ученику</span></div>' +
      '<button type="button" class="ai-close" aria-label="Закрыть">' + CLOSE + "</button>" +
    "</div>" +
    '<div class="ai-msgs" aria-live="polite"></div>' +
    '<form class="ai-form">' +
      '<textarea class="ai-input" rows="1" placeholder="Спроси о чём угодно…" aria-label="Сообщение помощнику"></textarea>' +
      '<button type="submit" class="ai-send" aria-label="Отправить">' + SEND + "</button>" +
    "</form>";

  mount.appendChild(fab);
  mount.appendChild(panel);

  var msgsEl = panel.querySelector(".ai-msgs");
  var form = panel.querySelector(".ai-form");
  var input = panel.querySelector(".ai-input");
  var sendBtn = panel.querySelector(".ai-send");
  var pending = false;

  function addBubble(role, text) {
    var b = document.createElement("div");
    b.className = "ai-msg ai-" + role;
    b.innerHTML = esc(text).replace(/\n/g, "<br>");
    msgsEl.appendChild(b);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return b;
  }

  function renderWelcome() {
    var w = document.createElement("div");
    w.className = "ai-msg ai-assistant";
    w.textContent = "Привет! Помогу с планом занятия, домашкой, сообщением ученику — или расскажу, как что работает в Pingly.";
    msgsEl.appendChild(w);
    var chips = document.createElement("div");
    chips.className = "ai-chips";
    SUGGESTIONS.forEach(function (s) {
      var c = document.createElement("button");
      c.type = "button";
      c.className = "ai-chip";
      c.textContent = s;
      c.addEventListener("click", function () { input.value = s; input.focus(); autosize(); });
      chips.appendChild(c);
    });
    msgsEl.appendChild(chips);
  }

  function renderHistory() {
    msgsEl.innerHTML = "";
    if (!history.length) { renderWelcome(); return; }
    history.forEach(function (m) { addBubble(m.role, m.content); });
  }

  function setPending(on) {
    pending = on;
    sendBtn.disabled = on;
    input.disabled = on;
    var t = panel.querySelector(".ai-typing");
    if (on && !t) {
      t = document.createElement("div");
      t.className = "ai-msg ai-assistant ai-typing";
      t.innerHTML = "<span></span><span></span><span></span>";
      msgsEl.appendChild(t);
      msgsEl.scrollTop = msgsEl.scrollHeight;
    } else if (!on && t) {
      t.parentNode.removeChild(t);
    }
  }

  function send() {
    var text = input.value.trim();
    if (!text || pending) return;
    if (!history.length) msgsEl.innerHTML = "";
    input.value = "";
    autosize();
    history.push({ role: "user", content: text });
    saveHistory();
    addBubble("user", text);
    setPending(true);

    fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history.slice(-10) })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        setPending(false);
        if (res.ok && res.data.reply) {
          history.push({ role: "assistant", content: res.data.reply });
          saveHistory();
          addBubble("assistant", res.data.reply);
        } else {
          addBubble("error", res.data.error || "Что-то пошло не так — попробуй ещё раз.");
        }
        input.focus();
      })
      .catch(function () {
        setPending(false);
        addBubble("error", "Нет связи — проверь интернет и попробуй ещё раз.");
      });
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  function toggle(open) {
    var on = open === undefined ? !panel.classList.contains("open") : open;
    panel.classList.toggle("open", on);
    fab.classList.toggle("hidden", on);
    if (on) { renderHistory(); input.focus(); }
  }

  fab.addEventListener("click", function () { toggle(true); });
  panel.querySelector(".ai-close").addEventListener("click", function () { toggle(false); });
  form.addEventListener("submit", function (e) { e.preventDefault(); send(); });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    if (e.key === "Escape") toggle(false);
  });
})();
