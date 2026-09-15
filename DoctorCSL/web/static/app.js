(() => {
  const STORE = "helpcsl.profile";
  const state = {
    tab: "computer",
    meta: null,
    lastKey: "",
    lastDraft: null,
    watchKey: "",
    timerStarted: 0,
    timerChanged: 0,
    timerStopped: 0,
    lastStatus: "",
    histShown: "",
    keepEdit: false,
    sceneHold: false,
    editChanged: 0,
    editing: false,
    busy: false,
    loggedIn: false,
  };
  let scene = null;

  const $ = (id) => document.getElementById(id);

  const PHONE_DIGITS = { "375": 12, "7": 11, "380": 12, "48": 11, "370": 11, "371": 11, "372": 11, "1": 11 };
  function phoneNorm(v) {
    let raw = (v || "").replace(/[\s().\u00a0-]/g, "");
    if (raw.startsWith("00")) raw = "+" + raw.slice(2);
    if (raw.startsWith("80")) raw = "+375" + raw.slice(2);
    else if (raw.startsWith("375") && !raw.startsWith("+")) raw = "+" + raw;
    else if (raw.startsWith("8") && raw.length >= 10) raw = "+375" + raw.slice(1);
    if (raw && raw[0] !== "+" && /\d/.test(raw[0])) raw = "+" + raw;
    return raw;
  }
  function phoneCountry(digits) {
    const codes = Object.keys(PHONE_DIGITS).sort((a, b) => b.length - a.length);
    for (const c of codes) if (digits.startsWith(c)) return [c, PHONE_DIGITS[c]];
    return ["", null];
  }
  function phoneOk(v) {
    const n = phoneNorm(v);
    if (!n.startsWith("+") || !/^\+[1-9]\d+$/.test(n)) return false;
    const d = n.slice(1);
    const [, exp] = phoneCountry(d);
    if (exp != null) return d.length === exp;
    return d.length >= 8 && d.length <= 15;
  }
  function phoneMsg(v) {
    const n = phoneNorm(v);
    if (!n.startsWith("+")) return "Номер с + и кодом страны. Пример: +375293761095";
    const d = n.slice(1);
    if (!/^\d+$/.test(d)) return "Только «+» и цифры.";
    const [, exp] = phoneCountry(d);
    if (exp != null) {
      if (d.length < exp) return `Ещё ${exp - d.length} цифр. Нужно ровно ${exp} после +.`;
      if (d.length > exp) return `Лишние цифры: для этого кода ровно ${exp} после +.`;
      return "";
    }
    if (d.length < 8) return "Слишком короткий номер. Пример: +375293761095";
    if (d.length > 15) return "Слишком длинный номер (максимум 15 цифр).";
    return "";
  }
  function phoneLimit(v) {
    const d = (v || "").replace(/\D/g, "");
    const [, exp] = phoneCountry(d);
    return exp ? 1 + exp : 16;
  }
  function bindPhone() {
    const el = $("phone");
    const hint = $("phone-hint");
    if (!el) return;
    const paint = () => {
      const msg = phoneMsg(el.value);
      if (hint) {
        hint.textContent = msg || (phoneOk(el.value) ? "Номер в международном формате, длина верная" : "Пример: +375293761095");
        hint.style.color = phoneOk(el.value) ? "#159756" : (msg ? "#F44A40" : "");
      }
      el.maxLength = phoneLimit(el.value);
    };
    el.addEventListener("input", () => {
      let v = "+" + el.value.replace(/[^\d]/g, "");
      const lim = phoneLimit(v);
      if (v.length > lim) v = v.slice(0, lim);
      el.value = v;
      paint();
    });
    paint();
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || "Ошибка запроса");
      return data;
    }
    if (!res.ok) throw new Error("Ошибка запроса");
    return res;
  }

  function loadProfile() {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}") || {}; }
    catch { return {}; }
  }
  function saveProfile(extra = {}) {
    const data = {
      login: $("login").value.trim(),
      password: $("password").value,
      phone: $("phone").value.trim(),
      anydesk: $("anydesk").value.trim(),
      rustdesk: $("rustdesk").value.trim(),
      last_issue_key: state.lastKey,
      last_draft: state.lastDraft,
      watch_issue_key: state.watchKey,
      ticket_started_at: state.timerStarted ? new Date(state.timerStarted).toISOString() : "",
      ticket_changed_at: state.timerChanged ? new Date(state.timerChanged).toISOString() : "",
      ticket_finished_at: state.timerStopped ? new Date(state.timerStopped).toISOString() : "",
      last_status: state.lastStatus || "",
      ...extra,
    };
    localStorage.setItem(STORE, JSON.stringify(data));
  }
  function wipeProfile() {
    localStorage.removeItem(STORE);
  }

  function parseWhen(raw) {
    if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) return raw;
    const text = String(raw || "").trim();
    if (!text) return 0;
    if (/^\d{10,16}$/.test(text)) return Number(text);
    const ms = Date.parse(text.replace(" ", "T"));
    return Number.isFinite(ms) ? ms : 0;
  }
  function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  function formatClock(ms) {
    if (!ms) return "—";
    const parts = new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Minsk",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date(ms));
    const hh = (parts.find((p) => p.type === "hour") || {}).value || "00";
    const mm = (parts.find((p) => p.type === "minute") || {}).value || "00";
    return `${hh}-${mm}`;
  }
  function timesDiffer(a, b, sec = 15) {
    if (!a || !b) return false;
    return Math.abs(a - b) >= sec * 1000;
  }
  function setTimerText(id, value, done) {
    const el = $(id);
    if (!el) return;
    el.textContent = value;
    el.classList.toggle("done", !!done);
  }
  function paintTimer() {
    const box = $("ticket-timers");
    if (box && !box._bound) {
      box._bound = true;
      box.addEventListener("click", showHistory);
    }
    if (!state.timerStarted) {
      setTimerText("timer-start", "—", false);
      setTimerText("timer-change", "—", false);
      setTimerText("timer-ready", "—", false);
      return;
    }
    const done = !!state.timerStopped;
    setTimerText("timer-start", formatClock(state.timerStarted), done);
    setTimerText("timer-change", formatClock(state.timerChanged), !!state.timerChanged);
    setTimerText("timer-ready", formatClock(state.timerStopped), done);
  }
  function startTimer(ts, key) {
    if (key) state.watchKey = key;
    const now = ts || Date.now();
    state.timerStarted = now;
    state.timerChanged = 0;
    state.timerStopped = 0;
    state.lastStatus = "";
    paintTimer();
  }
  function stopTimer(ts) {
    if (!state.timerStarted || state.timerStopped) return;
    state.timerStopped = ts || Date.now();
    if (state.timerStopped < state.timerStarted) state.timerStopped = state.timerStarted;
    paintTimer();
    saveProfile();
  }
  function noteStatusChange(status, changed) {
    status = String(status || "").trim();
    if (!status) return;
    const prev = String(state.lastStatus || "").trim();
    if (!prev) {
      state.lastStatus = status;
      if (timesDiffer(changed, state.timerStarted) && !isClosedStatus(status)) {
        state.timerChanged = changed;
      }
      paintTimer();
      return;
    }
    if (prev.toLowerCase() === status.toLowerCase()) return;
    if (isClosedStatus(status)) {
      state.lastStatus = status;
      paintTimer();
      return;
    }
    state.timerChanged = changed || Date.now();
    state.lastStatus = status;
    paintTimer();
  }
  function bindTimerToTicket(key, created, closed, status, changedRaw) {
    state.watchKey = key;
    const start = parseWhen(created);
    state.timerStarted = start || state.timerStarted || Date.now();
    const changed = parseWhen(changedRaw);
    const real = timesDiffer(changed, start);
    if (isClosedStatus(status)) {
      state.timerStopped = parseWhen(closed) || Date.now();
      if (state.timerStopped < state.timerStarted) state.timerStopped = state.timerStarted;
      state.timerChanged = real && timesDiffer(changed, state.timerStopped) ? changed : 0;
    } else {
      state.timerStopped = 0;
      state.timerChanged = real ? changed : 0;
    }
    state.lastStatus = status || "";
    paintTimer();
  }
  function isClosedStatus(status) {
    const blob = String(status || "").toLowerCase().replace("ё", "е");
    return ["готов", "закрыт", "решен", "выполнен", "resolved", "done", "closed", "complete", "отменен", "отклон", "rejected", "declined", "cancel"].some((m) => blob.includes(m));
  }
  function isPausedStatus(status) {
    const blob = String(status || "").toLowerCase().replace("ё", "е");
    return ["приостанов", "on hold", "on-hold", "paused", "suspended", "отложен"].some((m) => blob.includes(m));
  }
  function isProgressStatus(status) {
    const blob = String(status || "").toLowerCase().replace("ё", "е");
    return ["в работе", "in progress", "in-progress", "выполня", "working"].some((m) => blob.includes(m));
  }

  function setCredVisible(visible) {
    ["box-login", "box-password", "box-anydesk", "box-rustdesk"].forEach((id) => {
      $(id).style.display = visible ? "" : "none";
    });
    $("login-btn").style.display = visible ? "" : "none";
    $("cred-title").textContent = visible ? "Учётные данные портала  h.csl.by" : "Мобильный";
  }

  function setStatus(text, kind) {
    const el = $("status");
    el.textContent = text;
    el.className = "status" + (kind ? " " + kind : "");
  }

  function modal(title, body, buttons) {
    $("modal-title").textContent = title;
    $("modal").classList.toggle("hist", title === "История запросов");
    const box = $("modal-body");
    if (typeof body === "string") {
      box.className = "modal-body";
      box.textContent = body;
    } else {
      box.className = "modal-body wide";
      box.innerHTML = "";
      box.appendChild(body);
    }
    const acts = $("modal-actions");
    acts.innerHTML = "";
    (buttons || [{ label: "OK" }]).forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn" + (b.ghost ? " ghost" : "");
      btn.textContent = b.label;
      btn.addEventListener("click", () => {
        if (b.keep) { if (b.on) b.on(); return; }
        hideModal();
        if (b.on) b.on();
      });
      acts.appendChild(btn);
    });
    $("modal").classList.remove("hidden");
  }
  let toastTimer = 0;
  function hideSubmitBanner() {
    const el = $("submit-toast");
    if (el) el.classList.add("hidden");
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = 0; }
  }
  function showSubmitBanner(key) {
    const el = $("submit-toast");
    const lab = $("submit-toast-key");
    const fill = $("submit-toast-fill");
    if (!el || !lab) return;
    lab.textContent = "Заявка " + key;
    el.classList.remove("hidden");
    if (fill) {
      fill.style.animation = "none";
      void fill.offsetWidth;
      fill.style.animation = "";
    }
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(hideSubmitBanner, 5000);
    el.onclick = hideSubmitBanner;
  }
  function hideModal() {
    const wasHist = $("modal").classList.contains("hist");
    $("modal").classList.add("hidden");
    $("modal").classList.remove("hist");
    if (wasHist && !state.keepEdit) resetReadyUi();
  }
  function resetReadyUi() {
    state.editing = false;
    state.editChanged = 0;
    state.keepEdit = false;
    state.sceneHold = true;
    state.histShown = "";
    state.lastDraft = null;
    document.querySelectorAll("#computer-checks input, #printer-checks input, #user-checks input").forEach((el) => { el.checked = false; });
    ["computer-text", "printer-text", "purchase-text", "user-text"].forEach((id) => { if ($(id)) $(id).value = ""; });
    ["user-last", "user-first", "user-middle", "user-login"].forEach((id) => { if ($(id)) $(id).value = ""; });
    const create = document.querySelector('input[name=user-action][value="create"]');
    if (create) create.checked = true;
    showTab("computer");
    if (scene) { scene.stopReplay(); scene.resetHome(); }
    if (state.loggedIn) setStatus("Готово к новой заявке", "ok");
    paintTimer();
  }
  function confirmModal(title, text) {
    return new Promise((resolve) => {
      modal(title, text, [
        { label: "Отмена", ghost: true, on: () => resolve(false) },
        { label: "Да", on: () => resolve(true) },
      ]);
    });
  }

  function fillChecks(el, items, prefix) {
    el.innerHTML = "";
    items.forEach((it) => {
      const lab = document.createElement("label");
      const inp = document.createElement("input");
      inp.type = "checkbox";
      inp.dataset.id = it.id;
      inp.id = prefix + "-" + it.id;
      lab.appendChild(inp);
      lab.appendChild(document.createTextNode(it.title));
      el.appendChild(lab);
    });
  }

  function checkedMap(container) {
    const out = {};
    container.querySelectorAll("input[type=checkbox]").forEach((inp) => {
      out[inp.dataset.id] = inp.checked;
    });
    return out;
  }
  function applyChecks(container, map) {
    container.querySelectorAll("input[type=checkbox]").forEach((inp) => {
      inp.checked = !!(map && map[inp.dataset.id]);
    });
  }

  const TRANSLIT = {
    а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",
    н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"kh",ц:"ts",ч:"ch",ш:"sh",щ:"shch",
    ъ:"",ы:"y",ь:"",э:"e",ю:"yu",я:"ya",і:"i",ў:"u",ґ:"g",
  };
  function slug(text) {
    return Array.from((text || "").trim().toLowerCase()).map((ch) => {
      if (TRANSLIT[ch] !== undefined) return TRANSLIT[ch];
      if ((ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9") || "-_.".includes(ch)) return ch;
      return "";
    }).join("");
  }
  function syncUserLogin() {
    const f = slug($("user-first").value);
    const l = slug($("user-last").value);
    $("user-login").value = f && l ? f[0] + "." + l : "";
  }

  function snapshot() {
    return {
      tab: state.tab,
      computer: checkedMap($("computer-checks")),
      printer: checkedMap($("printer-checks")),
      computer_text: $("computer-text").value,
      printer_text: $("printer-text").value,
      purchase_text: $("purchase-text").value,
      user_action: document.querySelector("input[name=user-action]:checked")?.value || "create",
      user_last: $("user-last").value,
      user_first: $("user-first").value,
      user_middle: $("user-middle").value,
      user_login: $("user-login").value,
      user_services: checkedMap($("user-checks")),
      user_text: $("user-text").value,
    };
  }
  function restore(draft) {
    if (!draft) return;
    applyChecks($("computer-checks"), draft.computer);
    applyChecks($("printer-checks"), draft.printer);
    $("computer-text").value = draft.computer_text || "";
    $("printer-text").value = draft.printer_text || "";
    $("purchase-text").value = draft.purchase_text || "";
    const act = draft.user_action || "create";
    const radio = document.querySelector(`input[name=user-action][value="${act}"]`);
    if (radio) radio.checked = true;
    $("user-last").value = draft.user_last || "";
    $("user-first").value = draft.user_first || "";
    $("user-middle").value = draft.user_middle || "";
    $("user-login").value = draft.user_login || "";
    applyChecks($("user-checks"), draft.user_services);
    $("user-text").value = draft.user_text || "";
    showTab(draft.tab || "computer");
  }

  function showTab(key) {
    state.tab = key;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === key));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + key));
  }

  function paintHours() {
    const m = state.meta;
    if (!m) return;
    const banner = $("hours-banner");
    const hours = m.hours || "09:00–17:30";
    document.querySelector(".meta-hours").textContent = `заявки ${hours}  ·  пн–пт`;
    if (m.holiday_title) {
      banner.textContent = `Сегодня нерабочий день РБ: ${m.holiday_title}. Срочно: ${m.phone_display}`;
      banner.className = "hours-banner bad";
    } else if (m.open) {
      banner.textContent = `Приём заявок открыт  ·  до ${hours.split("–")[1]} (Минск ${m.now})`;
      banner.className = "hours-banner";
    } else if (!m.workday) {
      banner.textContent = `Выходной. Заявки ${hours}, пн–пт (календарь РБ). Срочно: ${m.phone_display}`;
      banner.className = "hours-banner bad";
    } else {
      banner.textContent = `Вне времени подачи (${hours}). Срочно: ${m.phone_display}`;
      banner.className = "hours-banner bad";
    }
    const tw = scene ? scene.towerWidth() : 70;
    banner.style.marginRight = Math.max(80, tw * 2) + "px";
  }

  async function refreshMeta() {
    try {
      state.meta = await api("/api/meta");
      $("ver").textContent = "v" + state.meta.version;
      if (scene) {
        scene.mapsUrl = state.meta.maps;
        scene.siteUrl = state.meta.site;
      }
      paintHours();
    } catch { /* offline preview still works */ }
  }

  async function doLogin(silent) {
    const login = $("login").value.trim();
    const password = $("password").value;
    const phone = $("phone").value.trim();
    if (!login || !password) {
      if (!silent) modal("Help CSL", "Введите логин и пароль портала.");
      setCredVisible(true);
      return;
    }
    if (!silent && phone && !phoneOk(phone)) {
      modal("Help CSL", phoneMsg(phone) || "Укажите мобильный в международном формате, например +375293761095.");
      return;
    }
    setStatus(silent ? "Автоматический вход…" : "Выполняется вход…");
    try {
      const data = await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ login, password, phone }),
      });
      state.loggedIn = true;
      setCredVisible(false);
      saveProfile();
      setStatus(`Вход выполнен: ${data.name}  ·  ${data.desks}`, "ok");
      if (state.lastKey || state.watchKey) pollOnce();
      if (!silent) modal("Help CSL", `Добро пожаловать, ${data.name}.\nHelp CSL уже в пути.`);
    } catch (e) {
      state.loggedIn = false;
      setCredVisible(true);
      setStatus("Ошибка входа", "bad");
      if (!silent) modal("Help CSL", `Не удалось войти в https://h.csl.by.\n\n${e.message}`);
    }
  }

  async function submit() {
    if (state.busy) return;
    if (!$("login").value.trim() || !$("password").value) {
      setCredVisible(true);
      modal("Help CSL", "Сначала войдите в Service Desk.");
      return;
    }
    const phone = $("phone").value.trim();
    if (!phoneOk(phone)) {
      setCredVisible(true);
      modal("Help CSL", phoneMsg(phone) || "Укажите мобильный в международном формате, например +375293761095.");
      return;
    }
    const draft = snapshot();
    const hours = state.meta?.hours || "09:00–17:30";
    let warn = "";
    if (state.meta && !state.meta.open) {
      warn = `\n\nСейчас вне времени подачи (${hours}). Срочно: ${state.meta.phone_display}.`;
    }
    const summaryGuess = guessSummary(draft);
    const msg = state.editing && state.lastKey
      ? `Старая заявка ${state.lastKey} будет закрыта и отправлена заново.\n\n${summaryGuess}${warn}`
      : `Отправить сервисный запрос?\n\n${summaryGuess}${warn}`;
    if (!await confirmModal("Help CSL", msg)) return;
    state.lastDraft = draft;
    saveProfile();
    state.busy = true;
    setStatus("Отправка заявки…");
    try {
      const payload = {
        ...draft,
        phone,
        anydesk: $("anydesk").value.trim(),
        rustdesk: $("rustdesk").value.trim(),
        close_key: state.editing ? state.lastKey : "",
      };
      const created = await api("/api/submit", { method: "POST", body: JSON.stringify(payload) });
      state.editing = false;
      state.lastKey = created.issue_key;
      state.watchKey = created.issue_key;
      state.histShown = created.issue_key;
      startTimer(Date.now(), created.issue_key);
      saveProfile();
      setStatus(`Заявка ${created.issue_key} создана`, "ok");
      if (scene) {
        scene.stopReplay();
        scene.arm(created.issue_key, $("login").value.trim() || "Клиент");
      }
      showSubmitBanner(created.issue_key);
      pollOnce();
    } catch (e) {
      setStatus("Ошибка отправки", "bad");
      modal("Help CSL", `Не удалось отправить заявку.\n\n${e.message}`);
    } finally {
      state.busy = false;
    }
  }

  function guessSummary(d) {
    if (d.tab === "computer") {
      const t = Object.entries(d.computer || {}).filter(([, v]) => v).map(([k]) => k);
      return "[Компьютер] " + ((d.computer_text || "").split("\n")[0] || "заявка");
    }
    if (d.tab === "printer") return "[Принтеры] " + ((d.printer_text || "").split("\n")[0] || "заявка");
    if (d.tab === "users") return `[Пользователи] ${d.user_login || ""}`;
    return "[Закупки] " + ((d.purchase_text || "").split("\n")[0] || "заявка");
  }

  function editTicket() {
    if (!state.lastKey) {
      modal("Help CSL", "Сначала отправьте заявку — потом её можно изменить.");
      return;
    }
    restore(state.lastDraft);
    state.editing = true;
    modal("Help CSL",
      `Заявка ${state.lastKey} открыта для правки.\nИзмените поля и нажмите «Отправить заявку».\nСтарый запрос будет закрыт, новый уйдёт как сервисный запрос.`);
  }

  async function showHistory() {
    if (!state.loggedIn) {
      modal("Help CSL", "Сначала выполните вход.");
      return;
    }
    try {
      const data = await api("/api/history");
      const wrap = document.createElement("div");
      wrap.innerHTML = `<div class="hist-stats">Всего: ${data.total}   ·   открыто: ${data.open}   ·   в работе: ${data.progress}   ·   закрыто: ${data.closed}</div>`;
      const table = document.createElement("table");
      table.className = "hist-table";
      table.innerHTML = "<thead><tr><th>Номер</th><th>Создана</th><th>Закрыта</th><th>Статус</th><th>Тип</th><th>Тема</th><th>Описание</th></tr></thead>";
      const tb = document.createElement("tbody");
      const cut = (s, n) => {
        const t = String(s || "").replace(/\s+/g, " ").trim();
        return t.length > n ? t.slice(0, n - 1) + "…" : t;
      };
      const note = document.createElement("div");
      note.className = "hint";
      note.textContent = "Клик — анимация. Двойной клик — правка («Изменено»). Сохранение — только «Отправить заявку».";
      wrap.appendChild(note);
      data.rows.forEach((r) => {
        const tr = document.createElement("tr");
        [r.key, r.created || "", r.closed || "", r.status || "", r.type || "", cut(r.summary, 80), cut(r.description, 140)].forEach((c) => {
          const td = document.createElement("td");
          td.textContent = c;
          tr.appendChild(td);
        });
        tr.addEventListener("click", () => {
          table.querySelectorAll("tr.on").forEach((x) => x.classList.remove("on"));
          tr.classList.add("on");
          showTicketScene(r);
        });
        tr.addEventListener("dblclick", (ev) => {
          ev.preventDefault();
          state.keepEdit = true;
          state.editing = true;
          state.lastKey = r.key;
          state.watchKey = r.key;
          state.editChanged = Date.now();
          state.timerChanged = state.editChanged;
          state.timerStopped = 0;
          state.lastStatus = "Изменено";
          state.sceneHold = true;
          const stamp = new Date(state.editChanged).toLocaleString("ru-RU");
          setStatus(`${r.key}: Изменено  ·  ${stamp}`, "ok");
          hideModal();
          modal("Help CSL",
            `Заявка ${r.key} открыта для правки.\nСтатус: Изменено\nВремя изменения: ${stamp}\n\nПравки сохранятся только по кнопке «Отправить заявку».`);
        });
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      wrap.appendChild(table);
      modal("История запросов", wrap, [
        { label: "Excel", ghost: true, keep: true, on: () => { window.location.href = "/api/history.xlsx"; } },
        { label: "Закрыть" },
      ]);
    } catch (e) {
      modal("Help CSL", e.message);
    }
  }

  async function serviceExit() {
    if (!await confirmModal("Help CSL", "Выйти из учётки? Логин и пароль будут удалены, поля входа появятся снова.")) return;
    try { await api("/api/logout", { method: "POST", body: "{}" }); } catch { /* ignore */ }
    wipeProfile();
    $("login").value = "";
    $("password").value = "";
    $("phone").value = "+375";
    $("anydesk").value = "";
    $("rustdesk").value = "";
    state.lastKey = "";
    state.lastDraft = null;
    state.watchKey = "";
    state.timerStarted = 0;
    state.timerChanged = 0;
    state.timerStopped = 0;
    state.lastStatus = "";
    state.histShown = "";
    state.loggedIn = false;
    setCredVisible(true);
    setStatus("Выполнен выход");
    paintTimer();
    if (scene) {
      scene.stopReplay();
      scene.resetHome();
    }
  }

  function showTicketScene(row) {
    if (!scene || !row || !row.key) return;
    const closed = isClosedStatus(row.status);
    const already = row.key === state.watchKey && row.key === scene.issueKey && !scene.replay && scene.state !== window.SCENE_HOME;
    if (row.key === state.histShown && !closed) {
      bindTimerToTicket(row.key, row.created, row.closed, row.status, row.status_changed);
      return;
    }
    if (row.key === state.histShown && closed && scene.replay) return;
    state.histShown = row.key;
    bindTimerToTicket(row.key, row.created, row.closed, row.status);
    if (closed) {
      scene.playReplay(row.key, $("login").value.trim() || "Клиент", 8);
      return;
    }
    if (already) return;
    scene.stopReplay();
    scene.arm(row.key, $("login").value.trim() || "Клиент");
    applyTicketStatus(row.key, row.status, row);
  }

  function applyTicketStatus(key, status, extra) {
    extra = extra || {};
    if (!key || !scene) return;
    if (scene.replay) {
      if (isClosedStatus(status) && key === state.watchKey) {
        if (!state.timerStarted && extra.created) state.timerStarted = parseWhen(extra.created);
        if (!state.timerStopped) stopTimer(parseWhen(extra.closed) || Date.now());
      }
      return;
    }
    if (key === state.watchKey || key === state.lastKey) {
      if (!state.timerStarted && extra.created) state.timerStarted = parseWhen(extra.created);
      noteStatusChange(status, parseWhen(extra.status_changed));
      if (isClosedStatus(status)) stopTimer(parseWhen(extra.closed) || Date.now());
      paintTimer();
    }
    if (isClosedStatus(status) || isPausedStatus(status)) {
      if (![window.SCENE_RETURN, window.SCENE_WALK_IN, window.SCENE_HOME].includes(scene.state)) {
        scene.playReturn(key);
      }
    } else if (isProgressStatus(status) || extra.in_progress) {
      if (scene.state === window.SCENE_HOME) {
        scene.playDepart(key, $("login").value.trim() || "Клиент");
      } else {
        scene.playOnsite(key);
      }
    }
  }

  async function pollOnce() {
    const key = state.watchKey || state.lastKey;
    if (!state.loggedIn || !key || !scene) return;
    try {
      const data = await api("/api/ticket/" + encodeURIComponent(key));
      if (state.sceneHold) {
        if (!state.timerStarted && data.created) state.timerStarted = parseWhen(data.created);
        if (!state.editing) {
          noteStatusChange(data.status, parseWhen(data.status_changed));
          if (isClosedStatus(data.status)) stopTimer(parseWhen(data.closed) || Date.now());
        }
        paintTimer();
        return;
      }
      applyTicketStatus(key, data.status, data);
    } catch { /* skip */ }
  }

  function bindMenus() {
    document.querySelectorAll("[data-act]").forEach((el) => {
      el.addEventListener("click", () => {
        document.querySelectorAll(".menu").forEach((m) => m.classList.remove("open"));
        const act = el.dataset.act;
        if (act === "submit") submit();
        else if (act === "edit") editTicket();
        else if (act === "history") showHistory();
        else if (act === "exit") serviceExit();
        else if (act === "contacts") {
          const m = state.meta || {};
          modal("Контакты CSL",
            `${m.company || "ООО «Компьютерная безопасность»"}\n${m.address || ""}\n\n${m.phone_display || ""}\n${m.site || "https://csl.by"}\n${m.email || ""}\n${m.jira || ""}\n\nЗаявки: ${m.hours || "09:00–17:30"}, пн–пт.`);
        } else if (act === "holiday") {
          if (scene) scene.setHoliday(true);
          modal("Help CSL", "Новогодняя сцена: зимний лес, Дед Мороз и олени.\nПо календарю она сама включается с 25 декабря по 14 января.\nВернуть обычный вид: Справка → Обычная сцена.");
        } else if (act === "replay") {
          if (scene) scene.playReplay("C1-DEMO", $("login").value.trim() || "Клиент", 8);
        } else if (act === "normal") {
          if (scene) scene.setHoliday(false);
        } else if (act === "about") {
          const m = state.meta || {};
          modal(`О программе ${m.app || "Help CSL"}`,
            `${m.app || "Help CSL"}  v${m.version || ""}\n${m.slogan || ""}\n\nСервисный запрос → ${m.jira || "https://h.csl.by"}\nРазработчик: CSL\nБраузерная версия`);
        }
      });
    });
    document.querySelectorAll(".menu-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = btn.parentElement;
        const open = menu.classList.contains("open");
        document.querySelectorAll(".menu").forEach((m) => m.classList.remove("open"));
        if (!open) menu.classList.add("open");
      });
    });
    document.addEventListener("click", () => {
      document.querySelectorAll(".menu").forEach((m) => m.classList.remove("open"));
    });
    $("modal").addEventListener("click", (e) => {
      if (e.target.id === "modal") hideModal();
    });
  }

  async function start() {
    fillChecks($("computer-checks"), [], "c");
    scene = new CityScene($("scene"));
    window.helpScene = scene;
    await scene.boot();
    bindMenus();
    document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
    bindPhone();
    $("login-btn").addEventListener("click", () => doLogin(false));
    $("user-last").addEventListener("input", syncUserLogin);
    $("user-first").addEventListener("input", syncUserLogin);
    $("password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(false); });

    try {
      state.meta = await api("/api/meta");
      fillChecks($("computer-checks"), state.meta.computer, "c");
      fillChecks($("printer-checks"), state.meta.printer, "p");
      fillChecks($("user-checks"), state.meta.users, "u");
      $("ver").textContent = "v" + state.meta.version;
      scene.mapsUrl = state.meta.maps;
      scene.siteUrl = state.meta.site;
      if (state.meta.holiday_scene) scene.setHoliday(null);
      paintHours();
    } catch (e) {
      fillChecks($("computer-checks"), [
        {id:"pc_power",title:"Не включается компьютер"},
        {id:"pc_boot",title:"Не загружается Windows / чёрный экран"},
        {id:"pc_slow",title:"Компьютер зависает или работает очень медленно"},
        {id:"pc_net",title:"Нет сети или интернета"},
        {id:"pc_mail",title:"Не работает электронная почта"},
        {id:"pc_login",title:"Не могу войти в учётную запись / сброс пароля"},
      ], "c");
    }

    const saved = loadProfile();
    if (saved.login) $("login").value = saved.login;
    if (saved.password) $("password").value = saved.password;
    if (saved.phone) $("phone").value = saved.phone;
    if (saved.anydesk) $("anydesk").value = saved.anydesk;
    if (saved.rustdesk) $("rustdesk").value = saved.rustdesk;
    state.lastKey = saved.last_issue_key || "";
    state.lastDraft = saved.last_draft || null;
    state.watchKey = saved.watch_issue_key || state.lastKey;
    state.timerStarted = parseWhen(saved.ticket_started_at);
    state.timerChanged = parseWhen(saved.ticket_changed_at);
    if (state.timerChanged && state.timerStarted && Math.abs(state.timerChanged - state.timerStarted) < 15000) {
      state.timerChanged = 0;
    }
    state.timerStopped = parseWhen(saved.ticket_finished_at);
    state.lastStatus = saved.last_status || "";
    paintTimer();
    if (saved.login && saved.password) {
      setCredVisible(false);
      setStatus("Автовход…");
      await doLogin(true);
    } else {
      setCredVisible(true);
    }

    const timerBox = $("ticket-timers");
    if (timerBox) timerBox.addEventListener("click", showHistory);
    setInterval(refreshMeta, 30000);
    setInterval(pollOnce, 6000);
    setInterval(paintTimer, 250);
    window.addEventListener("beforeunload", () => {
      if ($("login").value.trim() || $("password").value) saveProfile();
    });
  }

  start();
})();
