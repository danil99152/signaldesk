"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ACTION = { BUY: "Покупать", HOLD: "Держать", SELL: "Продавать" };
const ACTION_ORDER = { BUY: 0, HOLD: 1, SELL: 2 };
const SENT = {
  bullish: { label: "Позитивное", cls: "BUY" },
  neutral: { label: "Нейтральное", cls: "HOLD" },
  bearish: { label: "Негативное", cls: "SELL" },
};
const HORIZON = { short: "Краткосрок", medium: "Среднесрок", long: "Долгосрок" };
const HORIZON_ORDER = { short: 0, medium: 1, long: 2 };
const MARKET = { global: "Глобальный", russia: "Россия", all: "Оба рынка" };

const state = {
  report: null,
  reports: [],
  settings: null,
  wasRunning: false,
  recFilter: { market: "all", action: "all", q: "", sort: "action", dir: 1, open: new Set() },
  newsFilter: { region: "all", q: "" },
};

// ---------- utils ----------
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) {
  return /^https?:\/\//i.test(u || "") ? esc(u) : "#";
}
function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return Number(v).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtPct(v) {
  if (v === null || v === undefined) return '<span class="muted">—</span>';
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  const arrow = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `<span class="${cls}">${arrow}${Math.abs(v).toFixed(1)}%</span>`;
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}
function actionBadge(a) {
  a = String(a || "").toUpperCase();
  return ACTION[a] ? `<span class="badge ${a}">${ACTION[a]}</span>` : `<span class="badge neutral">${esc(a || "—")}</span>`;
}
function stars(n) {
  n = Math.max(0, Math.min(5, parseInt(n) || 0));
  return `<span class="stars" title="Уверенность ${n}/5" aria-label="Уверенность ${n} из 5">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>`;
}

// ---------- theme ----------
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem("sd-theme")); } catch (_) {}
$("#theme-btn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("sd-theme", next); } catch (_) {}
});

// ---------- tabs ----------
function showTab(name) {
  $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  ["dashboard", "history", "settings"].forEach((t) => $(`#tab-${t}`).classList.toggle("hidden", t !== name));
  if (name === "history") loadHistory();
  if (name === "settings") loadSettings();
}
$$("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------- run / status ----------
$("#run-btn").addEventListener("click", async () => {
  const body = { market: $("#run-market").value };
  const h = parseInt($("#run-hours").value);
  const n = parseInt($("#run-articles").value);
  if (h) body.hours = h;
  if (n) body.max_articles = n;
  try {
    await api("/api/run", { method: "POST", body: JSON.stringify(body) });
    $("#error-banner").classList.add("hidden");
    pollStatus();
  } catch (e) {
    toast(e.message);
  }
});

let pollTimer = null;
async function pollStatus() {
  clearTimeout(pollTimer);
  let st;
  try { st = await api("/api/status"); } catch (_) { pollTimer = setTimeout(pollStatus, 5000); return; }
  $("#key-banner").classList.toggle("hidden", st.api_key_set);
  const job = st.job;
  $("#run-btn").disabled = job.running;
  $("#run-btn").textContent = job.running ? "Анализ идёт…" : "Запустить анализ";
  $("#progress").classList.toggle("hidden", !job.running);
  if (job.running) {
    $("#progress-title").textContent = `Идёт анализ: ${MARKET[job.market] || ""}`;
    $("#progress-time").textContent = job.started_at ? `запущен ${fmtDate(job.started_at)}` : "";
    $("#progress-steps").innerHTML = Array.from({ length: job.stages }, (_, i) =>
      `<div class="${i + 1 < job.stage ? "done" : i + 1 === job.stage ? "active" : ""}"></div>`).join("");
    $("#progress-log").innerHTML = job.log.map(esc).join("<br>");
    $("#progress-log").scrollTop = 1e6;
  }
  if (state.wasRunning && !job.running) {
    if (job.error) {
      $("#error-banner").innerHTML = `<b>Анализ не удался:</b> ${esc(job.error)}`;
      $("#error-banner").classList.remove("hidden");
    } else if (job.report_id) {
      toast("Отчёт готов");
      await openReport(job.report_id);
      showTab("dashboard");
    }
  }
  state.wasRunning = job.running;
  pollTimer = setTimeout(pollStatus, job.running ? 2000 : 15000);
}

// ---------- dashboard ----------
async function openReport(id) {
  try {
    state.report = await api(`/api/reports/${encodeURIComponent(id)}`);
    state.recFilter.open = new Set();
  } catch (e) {
    toast(e.message);
    return;
  }
  renderDashboard();
}

function renderDashboard() {
  const root = $("#tab-dashboard");
  const r = state.report;
  if (!r) {
    root.innerHTML = `<div class="card empty"><h2>Отчётов пока нет</h2>
      <p>Нажмите «Запустить анализ». SignalDesk соберёт свежие новости, отберёт важное
      и предложит, что покупать, держать и продавать.</p></div>`;
    return;
  }
  const a = r.analysis || {};
  const recs = (a.recommendations || []).filter((x) => x && typeof x === "object");
  const counts = { BUY: 0, HOLD: 0, SELL: 0 };
  recs.forEach((x) => { const k = String(x.action || "").toUpperCase(); if (k in counts) counts[k]++; });

  const sentTile = (title, region) => {
    const s = SENT[String((region || {}).sentiment || "").toLowerCase()];
    return `<div class="card kpi"><div class="label">${title}</div>
      <div class="value" style="font-size:20px;margin-top:10px">${s ? `<span class="badge ${s.cls}">${s.label}</span>` : "—"}</div>
      <div class="sub">настроение рынка</div></div>`;
  };
  const countTile = (k) => `<div class="card kpi"><div class="label"><span class="dot" style="background:var(--${{ BUY: "good", HOLD: "warning", SELL: "critical" }[k]})"></span>${ACTION[k]}</div>
      <div class="value">${counts[k]}</div><div class="sub">сигналов</div></div>`;

  const regionCard = (title, region) => {
    if (!region || (!region.summary && !(region.key_drivers || []).length)) return "";
    const s = SENT[String(region.sentiment || "").toLowerCase()];
    return `<div class="card"><div class="card-head"><h2>${title}</h2>${s ? `<span class="badge ${s.cls}">${s.label}</span>` : ""}</div>
      <div>${esc(region.summary)}</div>
      ${(region.key_drivers || []).length ? `<ul class="clean">${region.key_drivers.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}</div>`;
  };

  const listCard = (title, items) => (items || []).length
    ? `<div class="card"><h2>${title}</h2><ul class="clean">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";

  root.innerHTML = `
    <div class="card-head" style="margin-bottom:16px">
      <h1 style="font-size:20px">Отчёт от ${esc(fmtDate(r.created_at))}</h1>
      <span class="badge neutral">${esc(MARKET[r.market] || r.market)}</span>
      <span class="spacer"></span>
      <a class="btn" href="/api/reports/${encodeURIComponent(r.id)}/markdown" style="text-decoration:none;border:1px solid var(--border);border-radius:8px;padding:6px 10px;color:var(--text)">Скачать .md</a>
    </div>
    ${a.raw ? `<div class="card"><h2>Ответ модели</h2><pre style="white-space:pre-wrap">${esc(a.raw)}</pre></div>` : `
    <div class="grid kpis">${countTile("BUY")}${countTile("HOLD")}${countTile("SELL")}
      ${r.market !== "russia" ? sentTile("Глобальный рынок", a.global) : ""}
      ${r.market !== "global" ? sentTile("Российский рынок", a.russia) : ""}</div>
    ${a.market_overview ? `<div class="card" style="margin-top:16px"><h2 style="margin-bottom:8px">Общая картина</h2><div class="overview">${esc(a.market_overview)}</div></div>` : ""}
    <div class="grid two" style="margin-top:16px">${regionCard("Глобальный рынок", a.global)}${regionCard("Российский рынок", a.russia)}</div>
    <div class="card" style="margin-top:16px" id="recs-card"></div>`}
    <div class="card" style="margin-top:16px" id="quotes-card"></div>
    <div class="grid two" style="margin-top:16px">${listCard("Ключевые риски", a.key_risks)}${listCard("За чем следить", a.upcoming_events)}</div>
    <div class="card" style="margin-top:16px" id="news-card"></div>
    <footer class="meta">
      Модели: отбор и выжимки — <code>${esc(r.meta?.fast_model)}</code>, анализ — <code>${esc(r.meta?.reasoning_model)}</code>.
      Просмотрено заголовков: ${esc(r.meta?.headlines)}, прочитано статей: ${(r.news || []).length}, окно: ${esc(r.meta?.lookback_hours)} ч.
      Токены: ${esc(r.meta?.usage?.prompt_tokens)} вход / ${esc(r.meta?.usage?.completion_tokens)} выход.<br>
      Отчёт сгенерирован языковыми моделями на основе открытых новостей и не является индивидуальной инвестиционной рекомендацией.
    </footer>`;
  if (!a.raw) renderRecs();
  renderQuotes();
  renderNews();
}

function renderRecs() {
  const card = $("#recs-card");
  if (!card) return;
  const f = state.recFilter;
  const news = state.report.news || [];
  let recs = (state.report.analysis.recommendations || []).filter((x) => x && typeof x === "object");
  recs = recs.map((x, i) => ({ ...x, _i: i, action: String(x.action || "").toUpperCase() }));
  const visible = recs.filter((x) =>
    (f.market === "all" || x.market === f.market) &&
    (f.action === "all" || x.action === f.action) &&
    (!f.q || `${x.asset} ${x.ticker} ${x.rationale}`.toLowerCase().includes(f.q.toLowerCase())));

  const keyFn = {
    action: (x) => ACTION_ORDER[x.action] ?? 9,
    asset: (x) => String(x.asset || "").toLowerCase(),
    market: (x) => x.market || "",
    horizon: (x) => HORIZON_ORDER[x.horizon] ?? 9,
    confidence: (x) => -(parseInt(x.confidence) || 0),
  }[f.sort];
  visible.sort((p, q) => {
    const a = keyFn(p), b = keyFn(q);
    if (a < b) return -f.dir;
    if (a > b) return f.dir;
    return (parseInt(q.confidence) || 0) - (parseInt(p.confidence) || 0);
  });

  const seg = (name, opts) => `<div class="seg" data-filter="${name}">${opts.map(([v, l]) =>
    `<button data-v="${v}" class="${f[name] === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const th = (key, label) => `<th data-sort="${key}">${label} <span class="arrow">${f.sort === key ? (f.dir > 0 ? "↑" : "↓") : ""}</span></th>`;

  const rows = visible.map((x) => {
    const open = f.open.has(x._i);
    const sources = (x.sources || []).map((id) => {
      const n = news[parseInt(id)];
      return n ? `<li><span class="idx">[${esc(id)}]</span><a href="${safeUrl(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a> <span class="muted small">— ${esc(n.source)}</span></li>` : "";
    }).join("");
    return `<tr class="rec" data-i="${x._i}" aria-expanded="${open}">
        <td>${actionBadge(x.action)}</td>
        <td><b>${esc(x.asset)}</b> <span class="ticker">${esc(x.ticker)}</span></td>
        <td>${esc(MARKET[x.market] || x.market)}</td>
        <td>${esc(HORIZON[x.horizon] || x.horizon || "—")}</td>
        <td>${stars(x.confidence)}</td>
        <td style="max-width:480px">${esc(x.rationale)}</td>
      </tr>
      ${open ? `<tr class="detail"><td colspan="6"><div class="detail-grid">
        <div><b>Обоснование</b><div>${esc(x.rationale)}</div><b style="display:block;margin-top:10px">Риски</b><div>${esc(x.risks || "—")}</div></div>
        <div><b>Источники</b>${sources ? `<ul class="clean">${sources}</ul>` : '<div class="muted">не указаны</div>'}</div>
      </div></td></tr>` : ""}`;
  }).join("");

  card.innerHTML = `
    <div class="card-head"><h2>Сигналы</h2><span class="muted small">${visible.length} из ${recs.length} · нажмите на строку, чтобы раскрыть</span>
      <span class="spacer"></span>
      <div class="filters">
        ${seg("market", [["all", "Все"], ["global", "Глобальный"], ["russia", "Россия"]])}
        ${seg("action", [["all", "Все"], ["BUY", "Покупать"], ["HOLD", "Держать"], ["SELL", "Продавать"]])}
        <input class="search" id="rec-q" placeholder="Поиск по активу…" value="${esc(f.q)}">
      </div></div>
    <div class="table-wrap"><table>
      <thead><tr>${th("action", "Сигнал")}${th("asset", "Актив")}${th("market", "Рынок")}${th("horizon", "Горизонт")}${th("confidence", "Уверенность")}<th class="nosort">Обоснование</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="6" class="muted">Нет сигналов под выбранные фильтры</td></tr>`}</tbody>
    </table></div>`;

  $$(".seg", card).forEach((s) => s.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    f[s.dataset.filter] = b.dataset.v;
    renderRecs();
  }));
  $$("th[data-sort]", card).forEach((h) => h.addEventListener("click", () => {
    f.dir = f.sort === h.dataset.sort ? -f.dir : 1;
    f.sort = h.dataset.sort;
    renderRecs();
  }));
  $$("tr.rec", card).forEach((tr) => tr.addEventListener("click", () => {
    const i = parseInt(tr.dataset.i);
    f.open.has(i) ? f.open.delete(i) : f.open.add(i);
    renderRecs();
  }));
  const q = $("#rec-q", card);
  q.addEventListener("input", () => {
    f.q = q.value;
    const pos = q.selectionStart;
    renderRecs();
    const nq = $("#rec-q");
    nq.focus();
    nq.setSelectionRange(pos, pos);
  });
}

function sparkline(values) {
  if (!values || values.length < 2) return "";
  const w = 200, h = 44, pad = 4;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    pad + (i * (w - 2 * pad)) / (values.length - 1),
    pad + (h - 2 * pad) * (1 - (v - min) / span),
  ]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" data-values="${values.join(",")}">
    <path d="${d}" fill="none" stroke="var(--spark)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="3" fill="var(--spark)" stroke="var(--surface)" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <line class="cross hidden" x1="0" x2="0" y1="0" y2="${h}" stroke="var(--muted)" stroke-width="1" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

function renderQuotes() {
  const card = $("#quotes-card");
  const quotes = state.report.quotes || [];
  if (!quotes.length) { card.classList.add("hidden"); return; }
  const recByTicker = {};
  (state.report.analysis.recommendations || []).forEach((x) => {
    if (x && x.ticker) recByTicker[String(x.ticker).toUpperCase()] = String(x.action || "").toUpperCase();
  });
  const block = (title, list) => list.length ? `<h3 class="small muted" style="margin:12px 0 8px">${title}</h3>
    <div class="quotes">${list.map((q) => `
      <div class="quote">
        <div class="top"><span class="sym">${esc(q.ticker)}</span>${recByTicker[q.ticker] ? actionBadge(recByTicker[q.ticker]) : ""}</div>
        <div class="last">${fmtNum(q.last)} <span class="small muted">${esc(q.currency)}</span></div>
        <div class="chg"><span>1д ${fmtPct(q.change_1d)}</span><span>1н ${fmtPct(q.change_1w)}</span><span>1м ${fmtPct(q.change_1m)}</span></div>
        ${sparkline(q.history)}
      </div>`).join("")}</div>` : "";
  card.innerHTML = `<div class="card-head" style="margin-bottom:0"><h2>Котировки</h2>
      <span class="muted small">дневные закрытия за месяц · Yahoo Finance и Мосбиржа</span></div>
    ${block("Глобальный рынок", quotes.filter((q) => q.market === "global"))}
    ${block("Российский рынок", quotes.filter((q) => q.market === "russia"))}`;

  $$(".spark", card).forEach((svg) => {
    const values = svg.dataset.values.split(",").map(Number);
    const quote = svg.closest(".quote");
    const cross = $(".cross", svg);
    let tip = null;
    svg.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const i = Math.round(ratio * (values.length - 1));
      const x = 4 + (i * (200 - 8)) / (values.length - 1);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x);
      cross.classList.remove("hidden");
      if (!tip) { tip = document.createElement("div"); tip.className = "spark-tip"; quote.appendChild(tip); }
      const back = values.length - 1 - i;
      tip.textContent = `${fmtNum(values[i])} · ${back ? `${back} торг. дн. назад` : "последнее закрытие"}`;
      const qr = quote.getBoundingClientRect();
      tip.style.left = `${rect.left - qr.left + (x / 200) * rect.width}px`;
      tip.style.top = `${rect.top - qr.top}px`;
    });
    svg.addEventListener("mouseleave", () => { cross.classList.add("hidden"); tip?.remove(); tip = null; });
  });
}

function renderNews() {
  const card = $("#news-card");
  const f = state.newsFilter;
  const all = (state.report.news || []).map((n, i) => ({ ...n, _i: i }));
  const list = all.filter((n) =>
    (f.region === "all" || n.region === f.region) &&
    (!f.q || `${n.title} ${n.summary}`.toLowerCase().includes(f.q.toLowerCase())));
  const imp = (v) => `<span class="imp" title="Важность ${v}/10">${Array.from({ length: 10 }, (_, k) => `<i class="${k < v ? "on" : ""}"></i>`).join("")}</span>`;
  const asset = (a) => {
    const s = parseInt(a.sentiment) || 0;
    return `<span class="chip ${s > 0 ? "sent-pos" : s < 0 ? "sent-neg" : ""}" title="${esc(a.note)}">${esc(a.name)}${a.ticker ? ` · ${esc(a.ticker)}` : ""}</span>`;
  };
  card.innerHTML = `
    <div class="card-head"><h2>Новости в основе анализа</h2><span class="muted small">${list.length} из ${all.length}</span>
      <span class="spacer"></span>
      <div class="filters">
        <div class="seg" id="news-seg">${[["all", "Все"], ["global", "Глобальные"], ["russia", "Россия"]].map(([v, l]) =>
          `<button data-v="${v}" class="${f.region === v ? "on" : ""}">${l}</button>`).join("")}</div>
        <input class="search" id="news-q" placeholder="Поиск по новостям…" value="${esc(f.q)}">
      </div></div>
    ${list.map((n) => `<div class="news-item">
      <div class="news-title"><span class="idx">[${n._i}]</span><a href="${safeUrl(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></div>
      <div class="news-meta">${imp(parseInt(n.importance) || 0)}<span>${esc(n.source)}</span>
        ${n.kind === "telegram" ? '<span class="chip">Telegram</span>' : ""}
        ${n.published ? `<span>${esc(fmtDate(n.published))}</span>` : ""}</div>
      <div>${esc(n.summary)}</div>
      ${n.macro ? `<div class="small muted" style="margin-top:2px">Макро: ${esc(n.macro)}</div>` : ""}
      ${(n.assets || []).length ? `<div style="margin-top:4px">${n.assets.map(asset).join("")}</div>` : ""}
    </div>`).join("") || '<div class="muted">Ничего не найдено</div>'}`;
  $("#news-seg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) { f.region = b.dataset.v; renderNews(); }
  });
  const q = $("#news-q");
  q.addEventListener("input", () => {
    f.q = q.value;
    const pos = q.selectionStart;
    renderNews();
    const nq = $("#news-q");
    nq.focus();
    nq.setSelectionRange(pos, pos);
  });
}

// ---------- history ----------
async function loadHistory() {
  const root = $("#tab-history");
  try { state.reports = await api("/api/reports"); } catch (e) { root.innerHTML = esc(e.message); return; }
  if (!state.reports.length) {
    root.innerHTML = '<div class="card empty"><h2>История пуста</h2><p>Запустите первый анализ.</p></div>';
    return;
  }
  root.innerHTML = `<div class="card"><div class="card-head"><h2>История отчётов</h2><span class="muted small">${state.reports.length}</span></div>
    <div class="table-wrap"><table><thead><tr><th class="nosort">Дата</th><th class="nosort">Рынок</th>
      <th class="nosort">Покупать</th><th class="nosort">Держать</th><th class="nosort">Продавать</th><th class="nosort"></th></tr></thead>
    <tbody>${state.reports.map((r) => `<tr>
      <td><a href="#" data-open="${esc(r.id)}">${esc(fmtDate(r.created_at))}</a>${state.report?.id === r.id ? ' <span class="chip">открыт</span>' : ""}</td>
      <td>${esc(MARKET[r.market] || r.market)}</td>
      <td>${r.counts.BUY}</td><td>${r.counts.HOLD}</td><td>${r.counts.SELL}</td>
      <td style="text-align:right;white-space:nowrap">
        <a href="/api/reports/${encodeURIComponent(r.id)}/markdown" title="Скачать Markdown">.md</a>
        <button class="icon-btn" data-del="${esc(r.id)}" title="Удалить" aria-label="Удалить отчёт">✕</button></td>
    </tr>`).join("")}</tbody></table></div></div>`;
  $$("[data-open]", root).forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    await openReport(a.dataset.open);
    showTab("dashboard");
  }));
  $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Удалить отчёт?")) return;
    await api(`/api/reports/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
    if (state.report?.id === b.dataset.del) { state.report = null; renderDashboard(); }
    loadHistory();
  }));
}

// ---------- settings ----------
const splitList = (s) => s.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean);

async function loadSettings() {
  const root = $("#tab-settings");
  let s;
  try { s = state.settings = await api("/api/settings"); } catch (e) { root.innerHTML = esc(e.message); return; }
  const feedBox = (region) => s.feeds.filter((f) => f.region === region).map((f) =>
    `<label title="${esc(f.url)}"><input type="checkbox" data-feed="${esc(f.name)}" ${s.disabled_feeds.includes(f.name) ? "" : "checked"}> ${esc(f.name)}</label>`).join("");
  root.innerHTML = `<div class="card">
    <div class="card-head"><h2>Настройки</h2><span class="spacer"></span><button class="btn primary" id="save-settings">Сохранить</button></div>
    <div class="form-row"><div><label class="title">Список наблюдения — глобальный</label><div class="hint">Тикеры Yahoo Finance: AAPL, SPY, GC=F (золото), BZ=F (Brent), BTC-USD, EURUSD=X</div></div>
      <textarea id="wl-global">${esc(s.watchlist_global.join(", "))}</textarea></div>
    <div class="form-row"><div><label class="title">Список наблюдения — Россия</label><div class="hint">Тикеры Мосбиржи: SBER, GAZP, LKOH; индексы IMOEX, RTSI, RGBI</div></div>
      <textarea id="wl-russia">${esc(s.watchlist_russia.join(", "))}</textarea></div>
    <div class="form-row"><div><label class="title">Telegram-каналы</label><div class="hint">Только публичные каналы. По одному в строке: markettwits, @channel или https://t.me/channel</div></div>
      <textarea id="tg">${esc(s.telegram_channels.join("\n"))}</textarea></div>
    <div class="form-row"><div><label class="title">Параметры по умолчанию</label><div class="hint">Применяются, если поля в шапке пустые</div></div>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <label>Окно новостей, ч <input id="set-hours" type="number" min="1" max="168" value="${s.lookback_hours}"></label>
        <label>Статей для чтения <input id="set-articles" type="number" min="4" max="80" value="${s.max_articles}"></label>
      </div></div>
    <div class="form-row"><div><label class="title">Новостные ленты</label><div class="hint">Снимите галочку, чтобы отключить источник</div></div>
      <div><div class="small muted" style="margin-bottom:4px">Глобальные</div><div class="feeds">${feedBox("global")}</div>
        <div class="small muted" style="margin:10px 0 4px">Российские</div><div class="feeds">${feedBox("russia")}</div></div></div>
    <div class="form-row"><div><label class="title">Модели и ключ</label><div class="hint">Меняются в файле .env (FAST_MODEL, REASONING_MODEL, OPENROUTER_API_KEY), затем перезапустите контейнер</div></div>
      <div>Отбор и выжимки: <code>${esc(s.fast_model)}</code><br>Анализ: <code>${esc(s.reasoning_model)}</code><br>
        Ключ OpenRouter: ${s.api_key_set ? '<span class="badge BUY">задан</span>' : '<span class="badge SELL">не задан</span>'}</div></div>
  </div>`;
  $("#save-settings").addEventListener("click", async () => {
    const body = {
      watchlist_global: splitList($("#wl-global").value),
      watchlist_russia: splitList($("#wl-russia").value),
      telegram_channels: splitList($("#tg").value),
      lookback_hours: parseInt($("#set-hours").value) || 24,
      max_articles: parseInt($("#set-articles").value) || 25,
      disabled_feeds: $$("[data-feed]", root).filter((c) => !c.checked).map((c) => c.dataset.feed),
    };
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
      toast("Настройки сохранены");
      loadSettings();
    } catch (e) {
      toast(e.message);
    }
  });
}

// ---------- init ----------
(async function init() {
  try {
    state.reports = await api("/api/reports");
    if (state.reports.length) await openReport(state.reports[0].id);
    else renderDashboard();
  } catch (e) {
    renderDashboard();
  }
  pollStatus();
})();
