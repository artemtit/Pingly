/* Собственная аналитика Pingly.
 *
 * Данные уходят только на свой сервер (POST /api/track) и нигде больше.
 * Здесь сознательно нет: отпечатка браузера, чтения canvas/шрифтов/плагинов,
 * записи содержимого страницы, чтения полей форм. Собираем ровно то, что
 * нужно для ответа «сколько людей пришло, откуда и что сделали».
 *
 * visitor_id — случайное число, а не отпечаток: два разных браузера одного
 * человека дадут два id, и это правильно. Идентифицировать человека мы не
 * пытаемся и не хотим.
 */
(function () {
  'use strict';

  var ENDPOINT = '/api/track';
  var VISITOR_KEY = 'pl_vid';
  var SESSION_KEY = 'pl_sid';
  var UTM_KEY = 'pl_utm';
  var SESSION_TTL = 30 * 60 * 1000; // визит рвётся после 30 минут молчания

  // Уважаем Do Not Track: если человек явно попросил не следить — не следим.
  var dnt = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack;
  if (dnt === '1' || dnt === 'yes') return;

  function rand() {
    // crypto там, где есть; Math.random — запасной путь. Нужна уникальность,
    // а не криптостойкость: это счётчик, а не токен доступа.
    try {
      var a = new Uint32Array(2);
      crypto.getRandomValues(a);
      return a[0].toString(36) + a[1].toString(36);
    } catch (e) {
      return Math.random().toString(36).slice(2) + Date.now().toString(36);
    }
  }

  // Приватный режим и заблокированные хранилища бросают на любом обращении.
  function store(kind, key, value) {
    try {
      var s = kind === 'local' ? localStorage : sessionStorage;
      if (value === undefined) return s.getItem(key);
      s.setItem(key, value);
      return value;
    } catch (e) {
      return null;
    }
  }

  function visitorId() {
    var id = store('local', VISITOR_KEY);
    if (!id) id = store('local', VISITOR_KEY, 'v' + rand());
    return id || ('v' + rand()); // хранилище недоступно — считаем разовым визитом
  }

  function sessionId() {
    var now = Date.now();
    var raw = store('session', SESSION_KEY);
    if (raw) {
      var parts = raw.split('.');
      if (parts.length === 2 && now - parseInt(parts[1], 10) < SESSION_TTL) {
        store('session', SESSION_KEY, parts[0] + '.' + now); // продлеваем
        return parts[0];
      }
    }
    var fresh = 's' + rand();
    store('session', SESSION_KEY, fresh + '.' + now);
    return fresh;
  }

  /* UTM-метки запоминаем на весь визит: человек приходит по ссылке с utm на
   * лендинг, а регистрируется через три страницы — без этого источник
   * регистрации потерялся бы и всё выглядело бы как «прямой заход». */
  function utm() {
    var found = {};
    var has = false;
    try {
      var q = new URLSearchParams(location.search);
      ['utm_source', 'utm_medium', 'utm_campaign'].forEach(function (k) {
        var v = q.get(k);
        if (v) { found[k] = v.slice(0, 120); has = true; }
      });
    } catch (e) { /* нет URLSearchParams — просто без меток */ }

    if (has) {
      try { store('session', UTM_KEY, JSON.stringify(found)); } catch (e) {}
      return found;
    }
    try {
      var saved = store('session', UTM_KEY);
      return saved ? JSON.parse(saved) : {};
    } catch (e) {
      return {};
    }
  }

  function send(event, props) {
    var payload = {
      event: event,
      path: location.pathname,
      v: visitorId(),
      s: sessionId(),
      ref: document.referrer || '',
      utm: utm(),
      props: props || {}
    };
    var body = JSON.stringify(payload);

    // sendBeacon переживает уход со страницы — обычный fetch на unload
    // браузер отменяет, и последнее событие визита терялось бы.
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon(ENDPOINT, blob)) return;
      }
    } catch (e) { /* падаем в fetch ниже */ }

    try {
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
        keepalive: true,
        credentials: 'same-origin'
      }).catch(function () {});
    } catch (e) { /* аналитика не имеет права ломать страницу */ }
  }

  // Публичный API. Совместим с plTrack: обе системы зовутся одним вызовом.
  window.plMetrics = { track: send };

  var prevTrack = window.plTrack;
  window.plTrack = function (name, props) {
    try { if (prevTrack) prevTrack(name, props); } catch (e) {}
    send(name, props);
  };

  send('pageview');
}());
