/* OpoTest TIC — interfaz web (se usa dentro de la APK y en el navegador) */
"use strict";

const $app = document.getElementById("app");
const isAndroid = typeof window.Android !== "undefined";
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const token = () => LS.get("token", "");
const L = ["a", "b", "c", "d"];

async function api(path, opts = {}) {
  const o = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
  const ctrl = new AbortController(); o.signal = ctrl.signal;
  const tmr = setTimeout(() => ctrl.abort(), opts.timeout || 90000);
  if (opts.body) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  if (token()) o.headers["X-Token"] = token();
  let r;
  try { r = await fetch("/api" + path, o); }
  catch (e) {
    clearTimeout(tmr);
    if (e.name === "AbortError") throw new Error("La Raspberry tarda demasiado en responder. Inténtalo de nuevo en un momento.");
    throw new Error("Sin conexión con la Raspberry. Comprueba que Tailscale está activo.");
  }
  clearTimeout(tmr);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Error " + r.status));
  return data;
}
const tokq = () => (token() ? "token=" + encodeURIComponent(token()) : "");

function toast(msg, ms = 2600) {
  const t = document.createElement("div");
  t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), ms);
}
function modal(html, onMount) {
  const m = document.createElement("div");
  m.className = "sheetmodal";
  m.innerHTML = `<div class="box" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div>`;
  m.addEventListener("click", (e) => { if (e.target === m) m.remove(); });
  document.body.appendChild(m);
  onMount && onMount(m.querySelector(".box"), () => m.remove());
  return m;
}
function topbar(title, { back = false, right = "" } = {}) {
  return `<header class="top">${back ? `<button class="back" aria-label="Volver" onclick="goBack()">‹</button>` : ""}<h1>${esc(title)}</h1>${right}</header>`;
}
const loading = () => `<div class="empty"><span class="spinner"></span></div>`;
const errBox = (e) => `<main><div class="empty err">${esc(e.message || e)}</div></main>`;
const pctClass = (p) => (p == null ? "" : p >= 70 ? "" : p >= 50 ? "mid" : "low");
const fmtDate = (s) => { if (!s) return ""; const d = new Date(s.replace(" ", "T")); return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }); };
const temaLabel = (id) => !id ? "" : id.startsWith("SP-") ? "Supuestos" : id.startsWith("A1-") ? "A1 · tema " + parseInt(id.slice(3)) : "A2 · " + id.slice(3).replace("-", " tema ").replace(/ tema 0/, " tema ");
const ICON = {
  gear: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`,
  book: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 5c3-1 6-1 10 1 4-2 7-2 10-1v14c-3-1-6-1-10 1-4-2-7-2-10-1z"/><path d="M12 6v14"/></svg>`,
  web: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>`,
  ai: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>`,
  hist: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="9"/></svg>`,
};

/* ------------------------------------------------------------------ router */
const routes = [];
const route = (re, fn, tab) => routes.push({ re, fn, tab });
let homeCache = null;

/* Salir de un test sin terminar: se pide confirmación (enlaces, botón ‹, atrás del navegador y de Android) */
let guard = null;          // { hash, sim, onFinish }
let tickTimer = null;
function askExit(go) {
  if (!guard) return go();
  const g = guard;
  modal(`<h2>${g.sp ? "¿Salir del supuesto?" : "¿Salir del test?"}</h2>
    <p class="small muted">${g.sp ? "Lo que has escrito está guardado, pero <b>el tiempo sigue corriendo</b>. Cuando se acabe, se entregará solo para corregirlo." : g.sim ? "Es un simulacro: <b>el tiempo sigue corriendo</b> aunque salgas. Cuando se acabe, se corregirá solo con lo que hayas respondido." : "Tus respuestas se guardan y podrás seguir donde lo dejaste desde «Hoy»."}</p>
    <div class="stack" style="margin-top:14px"><button class="btn block" id="stay">${g.sp ? "Seguir escribiendo" : "Seguir con el test"}</button>
    <button class="btn ghost block" id="fin">${g.sp ? "Entregar y corregir" : g.exam ? "Corregir ahora" : "Terminar ahora"}</button>
    <button class="btn quiet block" id="out">Salir sin terminar</button></div>`, (box, close) => {
    box.querySelector("#stay").onclick = close;
    box.querySelector("#out").onclick = () => { close(); guard = null; go(); };
    box.querySelector("#fin").onclick = () => { close(); g.onFinish && g.onFinish(); };
  });
}
function goBack() { askExit(() => history.back()); }
window.opoBack = () => {               // lo llama la APK al pulsar «atrás»
  if (document.querySelector(".sheetmodal")) { document.querySelectorAll(".sheetmodal").forEach((m) => m.remove()); return true; }
  if (!guard) return false;
  askExit(() => history.length > 1 ? history.back() : (location.hash = "#/"));
  return true;
};
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#"]');
  if (!a || !guard || a.getAttribute("href") === guard.hash) return;
  e.preventDefault();
  const to = a.getAttribute("href");
  askExit(() => { location.hash = to; });
}, true);

async function render() {
  const h = location.hash.replace(/^#/, "") || "/";
  document.querySelectorAll(".sheetmodal").forEach((m) => m.remove());
  if (guard && "#" + h !== guard.hash) {          // atrás del navegador: se vuelve al test y se pregunta
    const to = location.hash;
    history.pushState(null, "", guard.hash);
    askExit(() => { location.hash = to; });
    return;
  }
  guard = null;
  if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  document.body.classList.remove("testing");
  for (const r of routes) {
    const m = h.match(r.re);
    if (m) {
      document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === r.tab));
      window.scrollTo(0, 0);
      try { await r.fn(...m.slice(1).map((x) => (x === undefined ? undefined : decodeURIComponent(x)))); }
      catch (e) { console.error(e); $app.innerHTML = topbar("OpoTest") + errBox(e); }
      refreshBadge();
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", render);
async function refreshBadge() {
  try {
    homeCache = await api("/home");
    const b = document.getElementById("badge-rep");
    b.hidden = !homeCache.review_due; b.textContent = homeCache.review_due;
  } catch (e) {}
}

/* ------------------------------------------------------------------ inicio */
route(/^\/$/, async () => {
  $app.innerHTML = topbar("Hoy") + loading();
  const d = await api("/home");
  const done = d.answered >= d.goal;
  const seq = (d.today_seq || "").slice(-60);
  const ringPct = Math.min(1, d.answered / Math.max(1, d.goal));
  const R = 34, C = 2 * Math.PI * R;
  const pct = d.answered ? Math.round(100 * d.correct / d.answered) : null;
  const tem = d.temario || {};
  $app.innerHTML = topbar("Hoy", { right: `<a class="iconbtn" href="#/ajustes" aria-label="Ajustes">${ICON.gear}</a>` }) + `<main>
    <section class="sheet goal ${done ? "done" : ""}">
      <div class="goalrow">
        <svg class="ring" viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="${R}" class="trk"/>
          <circle cx="40" cy="40" r="${R}" class="val" stroke-dasharray="${(C * ringPct).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 40 40)"/>
          <text x="40" y="38" text-anchor="middle" class="big">${d.answered}</text><text x="40" y="53" text-anchor="middle" class="sm">de ${d.goal}</text></svg>
        <div class="goalinfo">
          <b>${done ? "Mínimo cumplido" : `Te faltan ${d.goal - d.answered}`}</b>
          <span>${pct != null ? `${pct}% de acierto hoy` : "Aún no has respondido hoy"}</span>
          <span>${d.streak ? `Racha de ${d.streak} día${d.streak > 1 ? "s" : ""}` : "Sin racha todavía"}</span>
        </div>
      </div>
      ${seq ? `<div class="seq" aria-label="Respuestas de hoy">${[...seq].map((c) => `<i class="${c === "1" ? "ok" : "ko"}"></i>`).join("")}</div>` : ""}
    </section>
    <section class="todo">
      ${d.open_test ? `<a href="#/t/${d.open_test.id}" class="hot"><span class="n">›</span><span class="t"><b>${d.open_test.kind === "simulacro" ? "Seguir con el simulacro" : "Seguir con el test"}</b><span>${esc(d.open_test.title)} · ${d.open_test.n} preguntas${d.open_test.kind === "simulacro" ? " · el tiempo corre" : ""}</span></span></a>` : ""}
      ${d.open_sp ? `<a href="#/sp/${d.open_sp.id}" class="hot"><span class="n">›</span><span class="t"><b>Seguir con el supuesto</b><span>${esc(d.open_sp.title)} · el tiempo corre</span></span></a>` : ""}
      <a href="#/test/5min" class="five"><span class="n">5′</span><span class="t"><b>Modo 5 minutos</b><span>10 preguntas: falladas de hoy y tus temas más flojos</span></span></a>
      <a href="#/test/repaso" class="${d.review_due ? "hot" : ""}"><span class="n ${d.review_due ? "" : "zero"}">${d.review_due}</span><span class="t"><b>Falladas por repasar</b><span>${d.review_due ? "Toca repasarlas hoy" : d.review_total ? `${d.review_total} en seguimiento, ninguna para hoy` : "Aún no hay fallos que repasar"}</span></span></a>
      <a href="#/test/nuevas" class="${d.new_questions ? "hot" : ""}"><span class="n ${d.new_questions ? "" : "zero"}">${d.new_questions}</span><span class="t"><b>Preguntas nuevas</b><span>${d.new_questions ? "Generadas con IA, sin hacer" : "Se generan cada mañana"}</span></span></a>
      <a href="#/fichas" class="${d.fichas_due ? "hot" : ""}"><span class="n ${d.fichas_due ? "" : "zero"}">${d.fichas_due}</span><span class="t"><b>Fichas de conceptos</b><span>${d.fichas_due ? "Tarjetas por repasar hoy" : "Se crean solas a partir de tus fallos"}</span></span></a>
      <a href="#/test/rapido"><span class="n">20</span><span class="t"><b>Test rápido</b><span>Prioriza tus temas débiles y lo que tienes olvidado</span></span></a>
    </section>
    <section class="row wrap"><a class="btn ghost grow" href="#/simulacro">Simulacro GSI</a><a class="btn ghost grow" href="#/supuesto">Supuesto práctico</a></section>
    <section class="row wrap"><a class="btn ghost grow" href="#/leyes">Leyes por artículos</a><a class="btn ghost grow" href="#/mapa">Mapa de temas</a></section>
    ${!d.ai_ready ? `<section class="sheet"><h3>Activa la IA</h3><p class="small muted">Para generar preguntas nuevas y explicaciones, añade tu API key de Gemini.</p><a class="btn small" href="#/ajustes">Ir a ajustes</a></section>` : ""}
    ${tem.work || tem.nopdf ? `<section class="small muted">Temario: ${tem.ok} de ${tem.n} documentos indexados${tem.work ? ", leyendo escaneados con OCR" : ""}${tem.nopdf ? `, ${tem.nopdf} sin PDF en la Raspberry` : ""}.</section>` : ""}
    <section class="row"><a class="btn quiet small" href="#/historial">${ICON.hist} Historial</a><span class="grow"></span><span class="tiny">${d.total_questions.toLocaleString("es-ES")} preguntas · ${d.ia_questions} de IA</span></section>
  </main>`;
}, "home");

/* ------------------------------------------------------------------ crear test */
const defaultCfg = { temario: "", bloques: [], temas: [], escalas: [], origen: "todas", solo_examen: false, no_vistas: false, priorizar_no_vistas: true, n: 20, mode: "practica" };
let catalog = null;
async function getCatalog() { if (!catalog) catalog = await api("/catalog"); return catalog; }

route(/^\/test\/(repaso|nuevas|rapido|5min)$/, async (kind) => {
  $app.innerHTML = topbar("Preparando test", { back: true }) + loading();
  try {
    const t = kind === "rapido" ? await api("/quick", { body: { n: 20, title: "Test rápido" } })
      : kind === "5min" ? await api("/quick", { body: { n: 10 } })
      : await api("/tests", { body: { kind, n: kind === "repaso" ? 100 : 50 } });
    location.replace("#/t/" + t.id);
  } catch (e) {
    $app.innerHTML = topbar(kind === "repaso" ? "Repaso" : "Nuevas", { back: true }) + `<main><div class="empty">${kind === "repaso" ? "No tienes falladas pendientes para hoy." : kind === "nuevas" ? "No hay preguntas nuevas sin hacer." : esc(e.message)}<br><a class="btn" href="#/test">Crear un test</a></div></main>`;
  }
});

route(/^\/test$/, async () => {
  const cfg = Object.assign({}, defaultCfg, LS.get("cfg", {}));
  const cat = await getCatalog();
  const draw = () => {
    const bl = cfg.temario === "A1" ? cat.bloques_a1 : cfg.temario === "A2" ? cat.bloques_a2 : null;
    const blKeys = bl ? Object.keys(bl) : [];
    const temasTxt = cfg.temas.length ? `${cfg.temas.length} tema${cfg.temas.length > 1 ? "s" : ""} elegido${cfg.temas.length > 1 ? "s" : ""}` : "Todos los temas";
    $app.innerHTML = topbar("Nuevo test", { right: `<a class="iconbtn" href="#/historial" aria-label="Historial">${ICON.hist}</a>` }) + `<main>
      <section class="row wrap"><a class="btn grow" href="#/simulacro">Simulacro GSI</a><a class="btn grow" href="#/supuesto">Supuesto práctico</a></section>
      <section class="row wrap"><a class="btn ghost grow" href="#/leyes">Leyes por artículos</a><a class="btn ghost grow" href="#/test/5min">5 minutos</a></section>
      <section class="sheet stack">
        <div><h3>Temario</h3><div class="chips" data-k="temario">
          ${[["", "Aleatorio"], ["A1", "A1 · CSSTIC"], ["A2", "A2 · GSI"]].map(([v, t]) => `<button class="chip" data-v="${v}" aria-pressed="${cfg.temario === v}">${t}</button>`).join("")}</div></div>
        ${bl ? `<div><h3>Bloque</h3><div class="chips" data-k="bloques">${blKeys.map((k) => `<button class="chip" data-v="${k}" aria-pressed="${cfg.bloques.includes(k)}" title="${esc(bl[k])}">${cfg.temario === "A2" ? "Bloque " + k : k}</button>`).join("")}</div>
          <p class="tiny" style="margin-top:6px">${cfg.bloques.map((k) => esc(bl[k])).join(" · ") || "Sin elegir: todos los bloques"}</p></div>
        <div><h3>Temas</h3><button class="btn quiet small" id="pick">${temasTxt}</button></div>` : ""}
        <div><h3>Escala</h3><div class="chips" data-k="escalas">${["A1", "A2", "C1"].map((v) => `<button class="chip" data-v="${v}" aria-pressed="${cfg.escalas.includes(v)}">${v}</button>`).join("")}</div>
          <p class="tiny" style="margin-top:6px">Según el examen de origen. Sin elegir: todas.</p></div>
        <div><h3>Origen</h3><div class="chips" data-k="origen">${[["todas", "Todas"], ["preparatic", "Banco PreparaTIC"], ["ia", "Generadas IA"]].map(([v, t]) => `<button class="chip" data-v="${v}" aria-pressed="${cfg.origen === v}">${t}</button>`).join("")}</div></div>
        <div>
          <label class="check"><input type="checkbox" data-c="solo_examen" ${cfg.solo_examen ? "checked" : ""}> Solo preguntas de exámenes oficiales</label>
          <label class="check"><input type="checkbox" data-c="no_vistas" ${cfg.no_vistas ? "checked" : ""}> Solo las que nunca he hecho</label>
          <label class="check"><input type="checkbox" data-c="priorizar_no_vistas" ${cfg.priorizar_no_vistas ? "checked" : ""}> Priorizar las que menos he visto</label>
        </div>
        <div class="row"><label class="field grow"><span>Preguntas</span><input type="number" id="n" min="1" max="200" value="${cfg.n}"></label>
          <div class="field grow"><span class="small muted" style="display:block;margin-bottom:4px">Corrección</span><div class="seg" id="mode">
            <button data-v="practica" aria-pressed="${cfg.mode === "practica"}">Al momento</button><button data-v="examen" aria-pressed="${cfg.mode === "examen"}">Al final</button></div></div></div>
        <p class="small muted" id="count">Contando preguntas…</p>
        <button class="btn block" id="go">Empezar test</button>
      </section>
      <section class="sheet">
        <h2>Generar preguntas con IA</h2>
        <p class="small muted">Crea preguntas nuevas con los filtros de arriba, a partir del temario, del banco y de tus fallos.</p>
        <div class="row"><input type="number" id="gn" min="1" max="100" value="10" style="max-width:110px" aria-label="Número de preguntas a generar"><button class="btn ghost grow" id="gen">Generar</button></div>
        <p class="small" id="genst"></p>
      </section>
    </main>`;
    const filters = () => ({ temario: cfg.temario || null, bloques: cfg.bloques, temas: cfg.temas, escalas: cfg.escalas, origen: cfg.origen, solo_examen: cfg.solo_examen, no_vistas: cfg.no_vistas, priorizar_no_vistas: cfg.priorizar_no_vistas });
    const save = () => LS.set("cfg", cfg);
    $app.querySelectorAll(".chips").forEach((g) => g.addEventListener("click", (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      const k = g.dataset.k, v = b.dataset.v;
      if (Array.isArray(cfg[k])) cfg[k] = cfg[k].includes(v) ? cfg[k].filter((x) => x !== v) : [...cfg[k], v];
      else cfg[k] = v;
      if (k === "temario") { cfg.bloques = []; cfg.temas = []; }
      if (k === "bloques") cfg.temas = [];
      save(); draw();
    }));
    $app.querySelectorAll("[data-c]").forEach((c) => c.addEventListener("change", () => { cfg[c.dataset.c] = c.checked; save(); count(); }));
    $app.querySelector("#n").addEventListener("change", (e) => { cfg.n = +e.target.value || 20; save(); });
    $app.querySelector("#mode").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; cfg.mode = b.dataset.v; save(); draw(); });
    const pick = $app.querySelector("#pick");
    pick && pick.addEventListener("click", () => pickTemas(cat, cfg, () => { save(); draw(); }));
    async function count() {
      try { const r = await api("/tests/count", { body: { filters: filters() } }); $app.querySelector("#count").textContent = `${r.count.toLocaleString("es-ES")} preguntas cumplen estos filtros.`; }
      catch (e) { $app.querySelector("#count").textContent = e.message; }
    }
    count();
    $app.querySelector("#go").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try { const t = await api("/tests", { body: { kind: "normal", n: cfg.n, mode: cfg.mode, filters: filters() } }); location.hash = "#/t/" + t.id; }
      catch (err) { toast(err.message); e.target.disabled = false; }
    });
    $app.querySelector("#gen").addEventListener("click", async (e) => {
      const n = +$app.querySelector("#gn").value || 10;
      e.target.disabled = true;
      try { const j = await api("/generate", { body: { n, filters: filters() } }); watchJob(j.id, $app.querySelector("#genst"), e.target); }
      catch (err) { toast(err.message); e.target.disabled = false; }
    });
  };
  draw();
}, "test");

function watchJob(id, el, btn) {
  const tick = async () => {
    if (!document.body.contains(el)) return;
    try {
      const j = await api("/generate/" + id);
      if (j.status === "ok") { el.innerHTML = `Listas ${j.generated} preguntas nuevas. <a href="#/test/nuevas">Hacerlas ahora</a>`; btn && (btn.disabled = false); return; }
      if (j.status === "error") { el.innerHTML = `<span class="err">No se generaron: ${esc((j.error || "").slice(0, 200))}</span>`; btn && (btn.disabled = false); return; }
      el.innerHTML = `<span class="spinner"></span> Generando… ${j.generated} de ${j.requested}`;
      setTimeout(tick, 2500);
    } catch (e) { el.textContent = e.message; }
  };
  tick();
}

function pickTemas(cat, cfg, done) {
  const list = cat.docs[cfg.temario].filter((d) => d.kind === "tema" && (!cfg.bloques.length || cfg.bloques.includes(d.bloque)));
  const sel = new Set(cfg.temas);
  modal(`<div class="row"><h2 class="grow" style="margin:0">Elige temas</h2><button class="btn small" id="ok">Listo</button></div>
    <input type="search" id="f" placeholder="Filtrar por título" style="margin:12px 0">
    <div id="l"></div>`, (box, close) => {
    const l = box.querySelector("#l");
    const paint = (f = "") => {
      const fl = f.toLowerCase();
      l.innerHTML = list.filter((d) => !fl || d.title.toLowerCase().includes(fl) || String(d.num) === fl).map((d) =>
        `<label class="check" style="align-items:flex-start;border-bottom:1px solid var(--line);padding:10px 0"><input type="checkbox" value="${d.id}" ${sel.has(d.id) ? "checked" : ""}>
        <span><b>${cfg.temario === "A2" ? d.bloque + "." : ""}${d.num}</b> ${esc(d.title)} <span class="tiny">${d.questions} preg.</span></span></label>`).join("");
    };
    paint();
    box.querySelector("#f").addEventListener("input", (e) => paint(e.target.value));
    l.addEventListener("change", (e) => { e.target.checked ? sel.add(e.target.value) : sel.delete(e.target.value); });
    box.querySelector("#ok").addEventListener("click", () => { cfg.temas = [...sel]; close(); done(); });
  });
}

/* ------------------------------------------------------------------ hacer test */
route(/^\/t\/(\d+)$/, async (id) => {
  $app.innerHTML = topbar("Test", { back: true }) + loading();
  let t = await api("/tests/" + id);
  if (t.finished_at) return results(t);
  const key = "pos-" + id;
  let pos = sessionStorage.getItem(key);
  pos = pos == null ? Math.max(0, t.items.findIndex((x) => x.chosen == null)) : +pos;
  let t0 = Date.now();
  document.body.classList.add("testing");
  guard = { hash: "#/t/" + id, sim: t.kind === "simulacro", exam: t.mode === "examen", onFinish: () => finish(true) };
  const deadline = t.time_left != null ? Date.now() + t.time_left * 1000 : null;
  const clock = () => {
    const el = document.getElementById("clock"); if (!deadline) return;
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    if (el) { el.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`; el.classList.toggle("low", left < 600); }
    if (left <= 0 && guard) { clearInterval(tickTimer); tickTimer = null; toast("Se acabó el tiempo", 3500); finish(true); }
  };
  if (deadline) tickTimer = setInterval(clock, 1000);

  const answered = () => t.items.filter((x) => x.chosen != null).length;
  const draw = () => {
    sessionStorage.setItem(key, pos);
    const it = t.items[pos];
    const shown = t.mode === "practica" && it.chosen != null;
    const tags = [
      it.origin === "ia" ? `<span class="tag ia">IA</span>` : "",
      it.is_exam ? `<span class="tag exam">Examen</span>` : "",
      it.escala ? `<span class="tag">${it.escala}</span>` : "",
      it.a1_doc ? `<span class="tag">${temaLabel(it.a1_doc)}</span>` : "",
      it.a2_doc ? `<span class="tag">${temaLabel(it.a2_doc)}</span>` : "",
    ].join("");
    $app.innerHTML = topbar(t.title || "Test", { back: true, right: `${deadline ? `<span class="clock" id="clock" aria-label="Tiempo restante"></span>` : ""}<button class="btn small quiet" id="nav">${pos + 1}/${t.n}</button>` }) + `<main>
      <div class="progress" aria-hidden="true"><i style="width:${(100 * answered()) / t.n}%"></i></div>
      <div class="qmeta">${tags}</div>
      <div class="qtext">${esc(it.text)}</div>
      <div class="opts" role="radiogroup">${L.filter((k) => it[k]).map((k) => {
        let c = "";
        if (shown) { if (k === it.correct) c = "right"; else if (k === it.chosen) c = "wrong"; }
        else if (k === it.chosen) c = "sel";
        return `<button class="opt ${c}" data-k="${k}" role="radio" aria-checked="${k === it.chosen}" ${shown ? "disabled" : ""}><span class="bub">${k}</span><span class="txt">${esc(it[k])}</span></button>`;
      }).join("")}</div>
      <div id="after">${shown ? afterAnswer(it) : t.mode === "practica" ? "" : `<p class="tiny" style="margin-top:12px">Modo examen: verás las soluciones al corregir. Acierto +1, fallo −1/3, en blanco 0.${it.chosen ? " Toca otra vez tu respuesta para dejarla en blanco." : ""}</p>`}</div>
    </main>
    <div class="testbar"><div class="in">
      <button class="btn quiet" id="prev" ${pos === 0 ? "disabled" : ""} aria-label="Anterior">‹</button>
      ${pos < t.n - 1 ? `<button class="btn grow" id="next">${it.chosen == null ? "Saltar" : "Siguiente"}</button>` : `<button class="btn grow guide" id="fin">${t.mode === "examen" ? "Corregir test" : "Terminar"}</button>`}
    </div></div>`;
    $app.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", () => choose(b.dataset.k)));
    $app.querySelector("#prev").onclick = () => { pos--; t0 = Date.now(); draw(); };
    const nx = $app.querySelector("#next"); nx && (nx.onclick = () => { pos++; t0 = Date.now(); draw(); });
    const fn = $app.querySelector("#fin"); fn && (fn.onclick = finish);
    $app.querySelector("#nav").onclick = navigator;
    if (shown) wireAfter(it);
    clock();
  };
  async function choose(k) {
    const it = t.items[pos];
    if (t.mode === "examen" && it.chosen === k) k = null;           // segunda pulsación: en blanco
    try {
      const r = await api(`/tests/${id}/answer`, { body: { pos, chosen: k, ms: Date.now() - t0 } });
      if (t.mode === "practica") Object.assign(it, r); else it.chosen = k;
      draw();
      if (t.mode === "examen" && k && pos < t.n - 1) setTimeout(() => { pos++; t0 = Date.now(); draw(); }, 180);
    } catch (e) { toast(e.message); }
  }
  async function finish(force) {
    const left = t.n - answered();
    if (!force && left && !confirm(`Te quedan ${left} sin responder. ¿Corregir igualmente?`)) return;
    try { t = await api(`/tests/${id}/finish`, { body: {} }); } catch (e) { return toast(e.message); }
    sessionStorage.removeItem(key);
    guard = null; if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    results(t);
  }
  function navigator() {
    modal(`<h2>Ir a la pregunta</h2><div class="navgrid">${t.items.map((x, i) => {
      let c = x.chosen != null ? "ans" : ""; if (t.mode === "practica" && x.is_correct != null) c = x.is_correct ? "ok" : "ko";
      return `<button class="${c} ${i === pos ? "cur" : ""}" data-i="${i}">${i + 1}</button>`; }).join("")}</div>
      <div class="hr"></div><button class="btn guide block" id="mf">${t.mode === "examen" ? "Corregir test" : "Terminar test"}</button>`, (box, close) => {
      box.querySelector(".navgrid").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; pos = +b.dataset.i; close(); draw(); });
      box.querySelector("#mf").onclick = () => { close(); finish(); };
    });
  }
  draw();
}, "test");

function afterAnswer(it) {
  const ok = it.chosen === it.correct;
  return `<div class="verdict ${ok ? "ok" : "ko"}">${ok ? "Correcta" : `Incorrecta. Es la ${it.correct.toUpperCase()}`}</div>
    ${it.overridden ? `<p class="tiny">Corregida por ti (el banco decía ${it.correct_bank.toUpperCase()}).</p>` : ""}
    ${it.explanation ? `<div class="note expl">${esc(it.explanation)}</div>` : ""}
    ${it.comments ? `<p class="tiny" style="margin-top:8px">Fuente: ${esc(it.comments)}</p>` : ""}
    ${it.law_id ? `<p class="small" style="margin-top:6px"><a href="#/ley/${encodeURIComponent(it.law_id)}/${encodeURIComponent(it.law_art || "")}">Leer el ${esc((it.law_art || "artículo").toLowerCase())} en el BOE consolidado</a></p>` : ""}
    ${it.origin === "ia" ? rateBlock(it) : ""}
    ${readyLine(it)}
    ${sourcesBlock(it)}`;
}
function readyLine(it) {
  const r = it.ready || {};
  const have = [r.ia && "IA", r.internet && "Internet"].filter(Boolean);
  if (!have.length) return `<p class="tiny ready-line">Sin precargar: IA e Internet tardarán unos segundos.</p>`;
  const miss = [!r.ia && "IA", !r.internet && "Internet"].filter(Boolean);
  const txt = have.length > 1 ? "Precargadas las respuestas de IA e Internet" : `Precargada la respuesta de ${have[0]}`;
  return `<p class="tiny ready-line"><span class="dot"></span>${txt}${miss.length ? ` · ${miss[0]} tardará unos segundos` : ""}.</p>`;
}
function rateBlock(it) {
  const b = (v, t) => `<button class="chip" data-rate="${v}" aria-pressed="${it.rating === v}">${t}</button>`;
  return `<div class="row wrap" data-rq="${it.id}" style="margin-top:10px"><span class="small muted">¿Nivel de examen?</span>
    ${b("facil", "Demasiado fácil")}${b("bien", "Nivel adecuado")}</div>`;
}
const readyDot = (it, k) => (it.ready && it.ready[k] ? `<span class="ready" title="Ya preparada: sale al instante">lista</span>` : "");
function sourcesBlock(it) {
  return `<div class="srcs" data-q="${it.id}" data-ch="${it.chosen || ""}">
      <button data-s="temario">${ICON.book}Temario</button><button data-s="internet">${ICON.web}Internet${readyDot(it, "internet")}</button><button data-s="ia">${ICON.ai}IA${readyDot(it, "ia")}</button></div>
    <div class="srcpanel" id="sp-${it.id}"></div>
    <p style="margin-top:12px"><button class="btn quiet small" data-fix="${it.id}">La correcta es otra</button></p>`;
}
function wireAfter(it, root = $app, onFix) {
  root.querySelectorAll(`[data-rq="${it.id}"]`).forEach((g) => g.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-rate]"); if (!b) return;
    const v = it.rating === b.dataset.rate ? "" : b.dataset.rate;
    try {
      const r = await api(`/questions/${it.id}/rate`, { body: { rating: v } });
      it.rating = v || null;
      g.querySelectorAll("[data-rate]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.rate === it.rating));
      if (v === "facil") toast(`Anotado. Las próximas saldrán más difíciles (nivel ${r.level} de 3)`);
      else if (v) toast("Anotado");
    } catch (err) { toast(err.message); }
  }));
  root.querySelectorAll(`.srcs[data-q="${it.id}"]`).forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    g.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    loadSource(it, b.dataset.s, root.querySelector("#sp-" + it.id));
  }));
  const fx = root.querySelector(`[data-fix="${it.id}"]`);
  fx && fx.addEventListener("click", () => fixCorrect(it, (q) => { Object.assign(it, q, { is_correct: it.chosen === q.correct ? 1 : 0 }); onFix ? onFix() : render(); }));
}
function fixCorrect(it, cb) {
  modal(`<h2>¿Cuál es la correcta?</h2><p class="small muted">Se guardará en el banco y se recalcularán tus resultados de esta pregunta.</p>
    <div class="opts">${L.filter((k) => it[k]).map((k) => `<button class="opt ${k === it.correct ? "right" : ""}" data-k="${k}"><span class="bub">${k}</span><span class="txt">${esc(it[k])}</span></button>`).join("")}</div>`,
    (box, close) => box.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", async () => {
      try { const q = await api(`/questions/${it.id}/correct`, { body: { letter: b.dataset.k } }); close(); toast("Respuesta corregida"); cb(q); }
      catch (e) { toast(e.message); }
    })));
}
const hl = (s) => esc(s).replace(/\{\{/g, '<mark class="ans">').replace(/\}\}/g, "</mark>").replace(/\[\[/g, "<mark>").replace(/\]\]/g, "</mark>");
/* Enlace al tema que salta al párrafo del fragmento y lo resalta */
function jumpHref(doc, page, snip) {
  const terms = [...new Set([...(snip || "").matchAll(/\{\{(.+?)\}\}|\[\[(.+?)\]\]/g)].map((m) => m[1] || m[2]))].slice(0, 14);
  const passage = (snip || "").replace(/\[\[|\]\]|\{\{|\}\}/g, "").replace(/^…|…$/g, "").trim().slice(0, 600);
  return `#/tema/${doc}/p/${page}/h/${encodeURIComponent(JSON.stringify({ t: terms, s: passage }))}`;
}
const reEsc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function markPage(text, hlInfo) {
  const termRe = hlInfo.t && hlInfo.t.length
    ? new RegExp("(?<![\\p{L}\\p{N}])(" + hlInfo.t.map((w) => reEsc(esc(w))).join("|") + ")(?![\\p{L}\\p{N}])", "giu") : null;
  const terms = (h) => (termRe ? h.replace(termRe, "<mark>$1</mark>") : h);
  let a = -1, b = -1;
  if (hlInfo.s && hlInfo.s.length > 8) {
    const words = hlInfo.s.split(/\s+/).filter(Boolean).map(reEsc);
    const m = new RegExp(words.join("\\s+")).exec(text);
    if (m) { a = m.index; b = m.index + m[0].length; }
  }
  if (a < 0) return { html: terms(esc(text)), found: false };
  return { html: esc(text.slice(0, a)) + `<mark class="jump" tabindex="-1">${terms(esc(text.slice(a, b)))}</mark>` + esc(text.slice(b)), found: true };
}
async function loadSource(it, which, el, refresh = false) {
  const markReady = () => { it.ready = Object.assign({}, it.ready, { [which]: true }); };
  el.innerHTML = `<div class="sheet"><span class="spinner"></span> ${which === "ia" ? "Preguntando a la IA…" : which === "internet" ? "Buscando en Internet…" : "Buscando en el temario…"}</div>`;
  try {
    const r = await api(`/questions/${it.id}/sources/${which}?chosen=${it.chosen || ""}${refresh ? "&refresh=1" : ""}`, { timeout: which === "ia" ? 100000 : 45000 });
    if (which !== "temario") markReady();
    if (which === "temario") {
      const strong = r.hits.some((h) => h.has_answer);
      el.innerHTML = `<div class="sheet">${r.hits.length ? (strong ? "" : `<p class="small muted" style="margin-bottom:6px">El temario no recoge la respuesta de forma literal; estos son los párrafos más relacionados. Contrasta con la IA o Internet.</p>`)
        + r.hits.map((h) => `<div class="hit"><div class="where">${h.has_answer ? `<span class="tag ok">Contiene la respuesta</span> ` : ""}<a href="${jumpHref(h.doc_id, h.page, h.snip)}">${h.temario} · ${h.temario === "A2" ? "Bloque " + h.bloque + ", " : ""}tema ${h.num} · pág. ${h.page}</a> — ${esc(h.title.slice(0, 70))}</div><div class="snip">${hl(h.snip)}</div></div>`).join("")
        : `<p class="muted small">No hay coincidencias en el temario indexado (${r.indexed_pages} páginas).</p>`}
        ${r.negative ? `<p class="tiny" style="margin-top:6px">Pregunta en negativo: se muestran los párrafos donde aparecen las opciones que sí son ciertas.</p>` : ""}</div>`;
    } else if (which === "internet") {
      const eng = (r.engines || []).filter(Boolean);
      el.innerHTML = `<div class="sheet">${r.results.length ? r.results.map((x) => `<div class="hit"><div class="where"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>${x.engine ? ` <span class="tiny">· ${esc(x.engine)}</span>` : ""}</div><div class="snip">${esc(x.snippet)}</div></div>`).join("")
        : `<p class="muted small">No he encontrado resultados que hablen de esta pregunta. Prueba con los enlaces de abajo.</p>`}
        ${[...(r.notes || []), ...(r.errors || [])].length ? `<p class="tiny" style="margin-top:6px">Aviso: ${esc([...(r.notes || []), ...(r.errors || [])].join(" · "))}</p>` : ""}
        <p class="tiny" style="margin-top:8px"><a href="${esc(r.search_url)}" target="_blank" rel="noopener">Buscar en Google</a> · <a href="${esc(r.wiki_url || "https://es.wikipedia.org")}" target="_blank" rel="noopener">Buscar en Wikipedia</a> · <a href="javascript:void 0" id="nr">Buscar de nuevo</a>${eng.length ? ` <span>· vía ${esc(eng.join(", "))}${r.cached ? " (precargado)" : ""}</span>` : ""}</p></div>`;
      const nr = el.querySelector("#nr"); nr && (nr.onclick = () => loadSource(it, which, el, true));
    } else {
      const agree = r.coincide && r.respuesta_ia === r.respuesta_banco;
      el.innerHTML = `<div class="sheet"><div class="ai-head"><b>La IA marca la ${String(r.respuesta_ia).toUpperCase()}</b>
        <span class="tag ${agree ? "" : "ia"}">${agree ? "Coincide con el banco" : "No coincide con el banco"}</span></div>
        <p>${esc(r.explicacion)}</p>
        ${(r.por_que_no || []).length ? `<ul class="small" style="padding-left:18px;margin:0 0 8px">${r.por_que_no.map((p) => `<li><b>${esc(p.letra.toUpperCase())}</b>: ${esc(p.motivo)}</li>`).join("")}</ul>` : ""}
        ${r.referencia ? `<p class="small muted">Referencia: ${esc(r.referencia)}</p>` : ""}
        ${r.truco ? `<p class="small"><b>Truco:</b> ${esc(r.truco)}</p>` : ""}
        <p class="tiny">La IA puede equivocarse; contrástalo con el temario. ${r.cached ? `<a href="javascript:void 0" id="rf">Volver a preguntar</a>` : ""}</p></div>`;
      const rf = el.querySelector("#rf"); rf && (rf.onclick = () => loadSource(it, which, el, true));
    }
  } catch (e) { el.innerHTML = `<div class="sheet err small">${esc(e.message)}</div>`; }
}

/* resultados */
const BLOQUES_GSI = { I: "Organización del Estado y AAPP", II: "Tecnología básica", III: "Desarrollo de sistemas", IV: "Sistemas y comunicaciones" };
function simBlock(t) {
  if (!t.breakdown) return "";
  const rows = Object.entries(t.breakdown).filter(([, v]) => v.ok + v.ko + v.blank);
  const hist = (t.history || []).filter((x) => x.nota10 != null);
  return `<section><h2>Por bloque</h2><div class="sheet"><table class="tbl"><thead><tr><th>Bloque</th><th>✓</th><th>✗</th><th>–</th><th>Puntos</th></tr></thead><tbody>
    ${rows.map(([b, v]) => `<tr><td><b>${b}</b> <span class="tiny">${esc(BLOQUES_GSI[b] || "")}</span></td><td>${v.ok}</td><td>${v.ko}</td><td>${v.blank}</td><td><b>${v.score}</b></td></tr>`).join("")}</tbody></table>
    <p class="tiny" style="margin-top:8px">Puntos = aciertos − fallos/3. Los blancos no restan: si dudas entre más de dos opciones, en blanco suele salir a cuenta.</p></div></section>
    ${hist.length > 1 ? `<section><h2>Tu evolución en simulacros</h2><div class="sheet">${barChart(hist.slice().reverse().map((x) => ({ label: x.finished_at, ok: x.ok, ko: x.ko, n: x.ok + x.ko })), { labels: (r) => new Date(r.label.replace(" ", "T")).toLocaleDateString("es-ES", { day: "numeric", month: "short" }) })}
      <p class="small" style="margin-top:8px">Notas: ${hist.slice(0, 8).map((x) => `<b>${x.nota10.toFixed(2)}</b>`).join(" · ")}</p></div></section>` : ""}`;
}
function results(t) {
  document.body.classList.remove("testing");
  guard = null;
  const total10 = t.n ? (Math.max(0, t.score) * 10 / t.n).toFixed(2) : "0";
  let filter = "ko";
  const draw = () => {
    const items = t.items.filter((x) => filter === "all" || (filter === "ko" ? x.is_correct !== 1 : x.is_correct === 1));
    $app.innerHTML = topbar(t.title || "Resultado", { back: true }) + `<main>
      <section class="sheet"><div class="score">
        <div class="ok"><b>${t.ok}</b><span>aciertos</span></div><div class="ko"><b>${t.ko}</b><span>fallos</span></div>
        <div><b>${t.blank}</b><span>en blanco</span></div><div><b>${total10}</b><span>nota /10</span></div></div>
        <p class="tiny" style="margin:10px 0 0;text-align:center">Puntuación ${t.score} (acierto +1, fallo −1/3) · ${fmtDate(t.finished_at)}</p></section>
      <section class="row wrap">
        ${t.ko + t.blank ? `<button class="btn grow" id="retry">Repetir los ${t.ko + t.blank} fallos</button>` : ""}
        <a class="btn ghost grow" href="${t.kind === "simulacro" ? "#/simulacro" : "#/test"}">${t.kind === "simulacro" ? "Otro simulacro" : "Otro test"}</a></section>
      ${simBlock(t)}
      <section><div class="seg" id="f"><button data-v="ko" aria-pressed="${filter === "ko"}">Fallos y blancos</button><button data-v="ok" aria-pressed="${filter === "ok"}">Aciertos</button><button data-v="all" aria-pressed="${filter === "all"}">Todas</button></div></section>
      <section class="reslist sheet">${items.length ? items.map((x) => `<div class="item" data-i="${x.pos}">
        <span class="mk ${x.is_correct === 1 ? "ok" : x.chosen == null ? "blank" : "ko"}">${x.is_correct === 1 ? "✓" : x.chosen == null ? "–" : "✗"}</span>
        <b>${x.pos + 1}.</b> ${esc(x.text)}<div class="detail" hidden></div></div>`).join("") : `<p class="muted small">Nada que mostrar.</p>`}</section>
    </main>`;
    $app.querySelector("#f").onclick = (e) => { const b = e.target.closest("button"); if (b) { filter = b.dataset.v; draw(); } };
    const rt = $app.querySelector("#retry"); rt && (rt.onclick = async () => { const n = await api(`/tests/${t.id}/retry`, { body: {} }); location.hash = "#/t/" + n.id; });
    $app.querySelectorAll(".item").forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.closest(".detail")) return;
      const d = el.querySelector(".detail"); const x = t.items[+el.dataset.i];
      if (!d.hidden) { d.hidden = true; return; }
      d.hidden = false;
      d.innerHTML = `<div class="opts" style="margin-top:10px">${L.filter((k) => x[k]).map((k) => `<div class="opt ${k === x.correct ? "right" : k === x.chosen ? "wrong" : ""}"><span class="bub">${k}</span><span class="txt">${esc(x[k])}</span></div>`).join("")}</div>${afterAnswer(x)}`;
      wireAfter(x, d, () => api("/tests/" + t.id).then((nt) => { t = nt; draw(); }));
    }));
  };
  draw();
}

/* ------------------------------------------------------------------ repaso / historial / pregunta */
route(/^\/repaso$/, async () => {
  $app.innerHTML = topbar("Repaso") + loading();
  const r = await api("/failed?limit=200");
  $app.innerHTML = topbar("Repaso") + `<main>
    <section class="sheet"><div class="count" style="font-size:2.2rem;font-weight:800;line-height:1">${r.due} <small class="muted" style="font-size:1rem;font-weight:600">para hoy</small></div>
      <p class="small muted" style="margin:6px 0 12px">Repaso inteligente: cada fallada vuelve justo antes de que se te olvide. Si la aciertas, el siguiente repaso se aleja (días, semanas, meses); si la vuelves a fallar, vuelve pronto. ${r.total} en seguimiento.</p>
      <div class="row wrap"><a class="btn grow ${r.due ? "" : "ghost"}" href="#/test/repaso">${r.due ? "Repasar ahora" : "Nada pendiente hoy"}</a>
      ${r.total ? `<button class="btn ghost grow" id="all">Test con todas las falladas</button>` : ""}</div></section>
    <section><h2>Falladas</h2><div class="sheet">${r.items.length ? r.items.map((x) => `<a class="list-item" href="#/q/${x.id}">
      <div class="small">${esc(x.text)}</div><div class="tiny">${x.fails} fallo${x.fails > 1 ? "s" : ""} · ${x.due <= new Date().toISOString().slice(0, 10) ? "<b style='color:var(--guide)'>toca hoy</b>" : "próximo repaso " + new Date(x.due).toLocaleDateString("es-ES", { day: "numeric", month: "short" })} · ${temaLabel(x.a1_doc || x.a2_doc)}</div></a>`).join("")
      : `<p class="muted small">Cuando falles una pregunta aparecerá aquí.</p>`}</div></section>
    <section><a class="btn quiet small" href="#/historial">${ICON.hist} Historial de tests</a></section></main>`;
  const all = $app.querySelector("#all");
  all && (all.onclick = async () => { const t = await api("/tests", { body: { kind: "falladas", n: 200, filters: { solo_falladas: true }, title: "Todas las falladas" } }); location.hash = "#/t/" + t.id; });
}, "repaso");

route(/^\/historial$/, async () => {
  $app.innerHTML = topbar("Historial", { back: true }) + loading();
  const r = await api("/history?limit=100");
  $app.innerHTML = topbar("Historial", { back: true }) + `<main><div class="sheet">${r.tests.length ? r.tests.map((t) => {
    const nota = t.finished_at && t.n ? (Math.max(0, t.score) * 10 / t.n).toFixed(1) : null;
    return `<a class="list-item row" href="#/t/${t.id}"><div class="grow"><b class="small">${esc(t.title)}</b><div class="tiny">${fmtDate(t.created_at)} · ${t.n} preguntas · ${t.mode === "examen" ? "examen" : "práctica"}</div></div>
      <div style="text-align:right">${nota != null ? `<b>${nota}</b><div class="tiny"><span style="color:var(--ok)">${t.ok}</span> / <span style="color:var(--ko)">${t.ko}</span></div>` : `<span class="tag">sin terminar</span>`}</div></a>`; }).join("")
    : `<div class="empty">Aún no has hecho ningún test.<br><a class="btn" href="#/test">Crear test</a></div>`}</div></main>`;
}, "test");

route(/^\/q\/(\d+)$/, async (id) => {
  $app.innerHTML = topbar("Pregunta", { back: true }) + loading();
  const q = await api("/questions/" + id);
  q.chosen = (q.attempts.find((a) => !a.is_correct) || {}).chosen || null;
  const draw = () => {
    $app.innerHTML = topbar("Pregunta", { back: true }) + `<main>
      <div class="qmeta">${q.origin === "ia" ? `<span class="tag ia">IA</span>` : ""}${q.is_exam ? `<span class="tag exam">Examen</span>` : ""}<span class="tag">${q.escala}</span>
        ${Object.entries(q.titles || {}).map(([k, v]) => `<a class="tag" href="#/tema/${q[k]}">${temaLabel(q[k])}</a>`).join("")}</div>
      <div class="qtext">${esc(q.text)}</div>
      <div class="opts">${L.filter((k) => q[k]).map((k) => `<div class="opt ${k === q.correct ? "right" : k === q.chosen ? "wrong" : ""}"><span class="bub">${k}</span><span class="txt">${esc(q[k])}</span></div>`).join("")}</div>
      ${q.explanation ? `<div class="note expl" style="margin-top:12px">${esc(q.explanation)}</div>` : ""}
      ${q.comments ? `<p class="tiny" style="margin-top:8px">Fuente: ${esc(q.comments)}</p>` : ""}
      ${readyLine(q)}
      ${sourcesBlock(q)}
      <section><h3>Tus intentos</h3><p class="small">${q.attempts.length ? q.attempts.map((a) => `<span class="mk ${a.is_correct ? "ok" : "ko"}" style="display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;color:#fff;font-size:.75rem;margin:2px">${a.chosen.toUpperCase()}</span>`).join("") : "Nunca la has respondido."}</p>
        ${q.review && !q.review.mastered ? `<p class="tiny">Próximo repaso: ${q.review.due}</p>` : ""}</section>
      <section><button class="btn quiet small" id="dis">Ocultar esta pregunta de los tests</button></section></main>`;
    wireAfter(q, $app, draw);
    $app.querySelector("#dis").onclick = async () => { if (!confirm("¿Ocultar esta pregunta? No volverá a salir en los tests.")) return; await api(`/questions/${q.id}/disable`, { body: { disabled: true } }); toast("Pregunta ocultada"); history.back(); };
  };
  draw();
}, "repaso");

/* ------------------------------------------------------------------ temario */
route(/^\/temario$/, async () => {
  const tem = LS.get("temario", "A2");
  $app.innerHTML = topbar("Temario") + loading();
  const cat = await getCatalog();
  catalog = null; // refresca el estado del OCR la próxima vez
  const docs = cat.docs[tem] || [];
  let groups;
  if (tem === "SP") {
    const K = [["sp-real", "Exámenes reales del tribunal"], ["sp-enun", "Enunciados de academias y simulacros"], ["sp-sol", "Soluciones y esquemas"],
      ["sp-feedback", "Correcciones de tu profesor"], ["sp-teoria", "Teoría y plantillas de las sesiones"], ["sp-otro", "Otros"]];
    groups = K.map(([k, name]) => [k, name, docs.filter((d) => d.kind === k).sort((a, b) => (a.bloque || "Z").localeCompare(b.bloque || "Z") || a.title.localeCompare(b.title))]).filter((g) => g[2].length);
  } else {
    const bl = tem === "A1" ? cat.bloques_a1 : cat.bloques_a2;
    groups = Object.keys(bl).map((k) => [k, bl[k], docs.filter((d) => d.bloque === k)]);
    if (tem === "A2") groups.push(["Otros", "Otros documentos", docs.filter((d) => d.bloque === "Otros")]);
  }
  const status = (d) => d.status === "ok" ? (d.questions ? `${d.questions} preg.` : "indexado") : d.status === "ocr" || d.status === "procesando" ? `OCR ${d.progress}%` : d.status === "sin_pdf" ? "sin PDF" : d.status === "error" ? "error" : "en cola";
  $app.innerHTML = topbar("Temario") + `<main>
    <section><div class="seg" id="tm"><button data-v="A2" aria-pressed="${tem === "A2"}">A2 · GSI</button><button data-v="A1" aria-pressed="${tem === "A1"}">A1 · CSSTIC</button><button data-v="SP" aria-pressed="${tem === "SP"}">Supuestos</button></div></section>
    <section><form id="sf" role="search"><input type="search" id="sq" placeholder="Buscar en ${tem === "SP" ? "tus supuestos y apuntes" : "todo el temario " + tem}" aria-label="Buscar en el temario"></form><div id="sr"></div></section>
    ${tem === "SP" && !docs.length ? `<section class="sheet small muted">Aún no hay documentos de supuestos en la Raspberry. Cópialos con <b>instalar.ps1 -SoloSupuestos</b> desde el PC.</section>` : ""}
    <section>${groups.map(([k, name, list]) => `<details class="bloque"><summary>${tem === "A2" && k !== "Otros" ? "Bloque " : ""}${esc(name)}<span class="tiny" style="margin-left:6px">${list.length}</span></summary>
      <ul class="temas">${list.map((d) => `<li><a href="#/tema/${d.id}"><span class="num">${d.kind === "tema" ? d.num : tem === "SP" ? (d.bloque || "·") : "·"}</span>
        <span class="tt">${esc(d.title)}${d.accuracy != null ? `<div class="pct ${pctClass(d.accuracy)}"><i style="width:${d.accuracy}%"></i></div>` : ""}</span>
        <span class="st">${status(d)}${d.accuracy != null ? `<br>${d.accuracy}%` : ""}</span></a></li>`).join("")}</ul></details>`).join("")}</section></main>`;
  $app.querySelector("#tm").onclick = (e) => { const b = e.target.closest("button"); if (b) { LS.set("temario", b.dataset.v); render(); } };
  $app.querySelector("#sf").onsubmit = async (e) => {
    e.preventDefault();
    const q = $app.querySelector("#sq").value.trim(); const sr = $app.querySelector("#sr");
    if (!q) { sr.innerHTML = ""; return; }
    sr.innerHTML = loading();
    const r = await api(`/temario/search?temario=${tem}&q=${encodeURIComponent(q)}&limit=25`);
    sr.innerHTML = `<div class="sheet" style="margin-top:10px">${r.hits.length ? r.hits.map((h) => `<div class="hit"><div class="where"><a href="${jumpHref(h.doc_id, h.page, h.snip)}">${h.num ? "Tema " + h.num : "Documento"} · pág. ${h.page}</a> — ${esc(h.title.slice(0, 60))}</div><div class="snip">${hl(h.snip)}</div></div>`).join("") : `<p class="muted small">Sin resultados.</p>`}</div>`;
  };
}, "temario");

route(/^\/tema\/([^/]+)(?:\/p\/(\d+))?(?:\/h\/(.+))?$/, async (id, page, hjson) => {
  let hlInfo = null;
  try { hlInfo = hjson ? JSON.parse(hjson) : null; } catch (e) { hlInfo = null; }
  $app.innerHTML = topbar("Tema", { back: true }) + loading();
  const d = await api("/temario/" + id);
  const name = d.kind === "tema" ? (d.temario === "A2" ? `Bloque ${d.bloque} · Tema ${d.num}` : `Tema ${d.num}`) : d.temario === "SP" ? "Supuestos" : "Documento";
  let from = page ? Math.max(1, +page - 1) : 1;
  $app.innerHTML = topbar(name, { back: true }) + `<main>
    <section><h2 style="font-size:1.15rem">${esc(d.title)}</h2>
      <p class="small muted">${d.pages ? d.pages + " páginas" : "PDF no disponible"}${d.indexed && d.indexed < d.pages ? ` · ${d.indexed} con texto (OCR en curso)` : ""} · ${d.questions} preguntas asociadas</p>
      <div class="row wrap">
        ${d.questions ? `<button class="btn grow" id="tt">Test de este tema</button>` : ""}
        ${d.pdf_available[0] && /\.pdf$/i.test(d.files[0] || "") ? `<a class="btn ghost grow" href="#/pdf/${id}/${page || 1}">Ver PDF</a>` : d.pdf_available[0] ? `<a class="btn ghost grow" href="/api/temario/${id}/pdf?file=0${token() ? "&" + tokq() : ""}" target="_blank">Abrir el archivo</a>` : ""}
        ${d.resumen_available ? `<a class="btn quiet grow" href="#/pdf/${id}/1/resumen">Resumen</a>` : ""}
      </div>
      ${d.kind === "tema" ? `<div class="row" style="margin-top:10px"><input type="number" id="gn" min="1" max="50" value="10" style="max-width:90px" aria-label="Número de preguntas"><button class="btn quiet grow" id="gen">${ICON.ai} Generar preguntas de este tema</button></div><p class="small" id="genst"></p>` : ""}
    </section>
    <section><form id="sf"><input type="search" id="sq" placeholder="Buscar en este tema"></form><div id="sr"></div></section>
    <section class="reader" id="rd">${d.indexed ? "" : `<p class="muted small">El texto de este tema aún no está disponible${d.status === "sin_pdf" ? ": falta copiar el PDF a la Raspberry." : "; se está procesando."}</p>`}</section>
    <section id="more"></section></main>`;
  const rd = $app.querySelector("#rd"), more = $app.querySelector("#more");
  async function load() {
    const r = await api(`/temario/${id}/pages?from=${from}&to=${from + 9}`);
    rd.insertAdjacentHTML("beforeend", r.pages.map((p) => {
      let body = esc(p.text);
      if (hlInfo && String(p.page) === String(page) && p.text) body = markPage(p.text, hlInfo).html;
      return `<div class="pgno" id="pg${p.page}">Página ${p.page}${p.ocr ? " · OCR" : ""}</div><div class="pg">${body || '<span class="muted">(página sin texto)</span>'}</div>`;
    }).join(""));
    from += 10;
    more.innerHTML = from <= r.total && r.pages.length ? `<button class="btn quiet block" id="lm">Cargar más páginas</button>` : "";
    const lm = more.querySelector("#lm"); lm && (lm.onclick = load);
  }
  if (d.indexed) {
    await load();
    if (page) {
      const target = rd.querySelector("mark.jump") || rd.querySelector(`#pg${page} + .pg mark`) || document.getElementById("pg" + page);
      if (target) {
        target.scrollIntoView({ block: target.matches("mark") ? "center" : "start" });
        if (target.matches("mark.jump")) { target.classList.add("flash"); target.focus({ preventScroll: true }); }
      }
    }
  }
  const tt = $app.querySelector("#tt");
  tt && (tt.onclick = async () => { const t = await api("/tests", { body: { n: 20, filters: { temario: d.temario, temas: [id], priorizar_no_vistas: true }, title: name } }); location.hash = "#/t/" + t.id; });
  const gen = $app.querySelector("#gen");
  gen && (gen.onclick = async () => {
    gen.disabled = true;
    try { const j = await api("/generate", { body: { n: +$app.querySelector("#gn").value || 10, filters: { temario: d.temario, temas: [id] } } }); watchJob(j.id, $app.querySelector("#genst"), gen); }
    catch (e) { toast(e.message); gen.disabled = false; }
  });
  $app.querySelector("#sf").onsubmit = async (e) => {
    e.preventDefault(); const q = $app.querySelector("#sq").value.trim(); const sr = $app.querySelector("#sr");
    if (!q) { sr.innerHTML = ""; return; }
    const r = await api(`/temario/search?doc=${id}&q=${encodeURIComponent(q)}`);
    sr.innerHTML = `<div class="sheet" style="margin-top:10px">${r.hits.length ? r.hits.map((h) => `<div class="hit"><div class="where"><a href="${jumpHref(id, h.page, h.snip)}">Página ${h.page}</a></div><div class="snip">${hl(h.snip)}</div></div>`).join("") : `<p class="muted small">Sin resultados.</p>`}</div>`;
  };
}, "temario");

/* visor PDF con pdf.js */
let pdfjs = null;
route(/^\/pdf\/([^/]+)\/(\d+)(?:\/(resumen))?$/, async (id, page, res) => {
  const url = `/api/temario/${id}/pdf?file=${res ? "resumen" : "0"}${token() ? "&" + tokq() : ""}`;
  $app.innerHTML = topbar(res ? "Resumen" : "PDF", { back: true, right: `<a class="btn small quiet" href="${url}" target="_blank" id="ext">Abrir fuera</a>` }) +
    `<main><div class="row" style="margin-bottom:10px"><button class="btn quiet small" id="pv">‹</button><span class="grow small" style="text-align:center" id="pi">Cargando…</span><button class="btn quiet small" id="nx">›</button></div><div class="pdfwrap" id="pw"></div></main>`;
  if (isAndroid) $app.querySelector("#ext").onclick = (e) => { e.preventDefault(); window.Android.openExternal(location.origin + url); };
  try {
    if (!pdfjs) {
      const CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/";
      try {
        pdfjs = await import("/static/vendor/pdf.min.mjs");
        pdfjs.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.min.mjs";
      } catch (e) {
        pdfjs = await import(CDN + "pdf.min.mjs");
        pdfjs.GlobalWorkerOptions.workerSrc = CDN + "pdf.worker.min.mjs";
      }
    }
    const task = pdfjs.getDocument({ url, disableAutoFetch: true, rangeChunkSize: 1 << 20 });
    task.onProgress = (ev) => { const pi = $app.querySelector("#pi"); if (pi && pi.textContent.startsWith("Cargando")) pi.textContent = `Cargando… ${(ev.loaded / 1e6).toFixed(1)} MB`; };
    const doc = await task.promise;
    let p = Math.min(+page || 1, doc.numPages);
    const pw = $app.querySelector("#pw"), pi = $app.querySelector("#pi");
    const show = async () => {
      pi.textContent = `Página ${p} de ${doc.numPages}`;
      const pg = await doc.getPage(p);
      const w = pw.clientWidth || 360, vp0 = pg.getViewport({ scale: 1 });
      const scale = (w / vp0.width) * Math.min(window.devicePixelRatio || 1, 2);
      const vp = pg.getViewport({ scale });
      const c = document.createElement("canvas"); c.width = vp.width; c.height = vp.height;
      await pg.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
      pw.innerHTML = ""; pw.appendChild(c);
    };
    $app.querySelector("#pv").onclick = () => { if (p > 1) { p--; show(); } };
    $app.querySelector("#nx").onclick = () => { if (p < doc.numPages) { p++; show(); } };
    await show();
  } catch (e) {
    $app.querySelector("#pi").innerHTML = `<span class="err">No se pudo abrir el PDF aquí (${esc(e.message)}). Prueba con «Abrir fuera».</span>`;
  }
}, "temario");

/* ------------------------------------------------------------------ estadísticas */
function barChart(rows, { goal = 0, labels = (r) => r.label } = {}) {
  const W = 340, H = 140, pad = 18, n = rows.length || 1;
  const max = Math.max(goal, ...rows.map((r) => r.n), 1);
  const bw = (W - pad) / n;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H + 18}" role="img" aria-label="Preguntas respondidas">`;
  rows.forEach((r, i) => {
    const x = pad + i * bw + 1, hOk = ((r.ok || 0) / max) * H, hKo = ((r.ko || 0) / max) * H;
    s += `<rect x="${x}" y="${H - hOk}" width="${Math.max(bw - 2, 1)}" height="${hOk}" fill="var(--ok)" rx="1"><title>${esc(labels(r))}: ${r.ok || 0} bien, ${r.ko || 0} mal</title></rect>`;
    s += `<rect x="${x}" y="${H - hOk - hKo}" width="${Math.max(bw - 2, 1)}" height="${hKo}" fill="var(--ko)" rx="1"></rect>`;
  });
  if (goal) { const y = H - (goal / max) * H; s += `<line x1="${pad}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--guide)" stroke-dasharray="4 3"/><text x="0" y="${y + 3}">${goal}</text>`; }
  s += `<text x="${pad}" y="${H + 14}">${esc(labels(rows[0] || { label: "" }))}</text><text x="${W}" y="${H + 14}" text-anchor="end">${esc(labels(rows[rows.length - 1] || { label: "" }))}</text></svg>`;
  return s;
}
function pctBars(rows, label) {
  return `<div class="bars">${rows.map((r) => { const p = r.pct ?? (r.n ? Math.round(100 * (r.ok || 0) / r.n) : 0);
    const col = p >= 70 ? "var(--ok)" : p >= 50 ? "#c98a14" : "var(--ko)";
    return `<div class="b"><span class="lab">${label(r)}</span><span class="val">${p}%</span><span class="track"><i style="width:${p}%;background:${col}"></i></span></div>`; }).join("")}</div>`;
}
route(/^\/stats$/, async () => {
  $app.innerHTML = topbar("Progreso") + loading();
  const s = await api("/stats");
  const T = s.totals;
  let period = LS.get("period", "dias");
  const pct = T.answered ? Math.round(100 * T.correct / T.answered) : 0;
  const weakA = [...s.temas_a1, ...s.temas_a2].filter((r) => r.n >= 5).sort((a, b) => a.pct - b.pct);
  const best = [...weakA].reverse().slice(0, 5);
  const dayNames = { dias: "Últimos 30 días", semanas: "Por semanas", meses: "Por meses" };
  const draw = () => {
    const rows = period === "dias" ? s.daily : period === "semanas" ? s.weekly : s.monthly;
    const lab = period === "dias" ? (r) => new Date(r.label).toLocaleDateString("es-ES", { day: "numeric", month: "short" }) : period === "semanas" ? (r) => "sem " + r.label.slice(5) : (r) => r.label;
    $app.innerHTML = topbar("Progreso") + `<main>
      <section class="row wrap"><a class="btn ghost grow" href="#/mapa">Mapa de temas</a><a class="btn ghost grow" href="#/simulacro">Simulacros</a></section>
      <section class="kpis">
        <div class="sheet"><b>${T.answered.toLocaleString("es-ES")}</b><span>preguntas respondidas</span></div>
        <div class="sheet"><b>${pct}%</b><span>de acierto global</span></div>
        <div class="sheet"><b>${T.streak}</b><span>días seguidos cumpliendo el mínimo</span></div>
        <div class="sheet"><b>${T.week_answered}</b><span>esta semana · ${T.week_goal_days}/7 días con mínimo</span></div>
        <div class="sheet"><b>${T.tests}</b><span>tests terminados${T.avg_score10 != null ? ` · nota media ${T.avg_score10}` : ""}</span></div>
        <div class="sheet"><b>${T.unique.toLocaleString("es-ES")}</b><span>preguntas distintas vistas</span></div>
      </section>
      <section class="sheet"><div class="seg" id="per">${Object.entries(dayNames).map(([k, v]) => `<button data-v="${k}" aria-pressed="${period === k}">${v.replace("Últimos 30 días", "Días")}</button>`).join("")}</div>
        <div style="margin-top:12px">${rows.length ? barChart(rows, { goal: period === "dias" ? T.goal : 0, labels: lab }) : `<p class="muted small">Sin datos todavía.</p>`}</div>
        <div class="legend"><span><i style="background:var(--ok)"></i>Aciertos</span><span><i style="background:var(--ko)"></i>Fallos</span>${period === "dias" ? `<span><i style="background:var(--guide)"></i>Mínimo diario</span>` : ""}</div></section>
      ${weakA.length ? `<section><h2>Temas que más fallas</h2><div class="sheet">${pctBars(weakA.slice(0, 8), (r) => `<a href="#/tema/${r.id}">${temaLabel(r.id)} · ${esc(r.title)}</a>`)}</div></section>
      <section><h2>Temas que mejor llevas</h2><div class="sheet">${pctBars(best, (r) => `<a href="#/tema/${r.id}">${temaLabel(r.id)} · ${esc(r.title)}</a>`)}</div></section>` : `<section class="sheet small muted">Cuando respondas al menos 5 preguntas de un tema verás aquí cuáles fallas más.</section>`}
      ${s.bloques_a2.length ? `<section><h2>Por bloque del A2</h2><div class="sheet">${pctBars(s.bloques_a2, (r) => "Bloque " + r.k)}</div></section>` : ""}
      ${s.bloques.length ? `<section><h2>Por bloque del A1</h2><div class="sheet">${pctBars(s.bloques, (r) => r.k)}</div></section>` : ""}
      ${s.escalas.length ? `<section><h2>Por escala y origen</h2><div class="sheet">${pctBars([...s.escalas.map((r) => ({ ...r, k: "Escala " + r.k })), ...s.origen.map((r) => ({ ...r, k: r.k === "ia" ? "Generadas por IA" : "Banco PreparaTIC" }))], (r) => r.k + ` <span class="tiny">(${r.n})</span>`)}</div></section>` : ""}
      ${s.worst_questions.length ? `<section><h2>Preguntas que más fallas</h2><div class="sheet">${s.worst_questions.map((q) => `<a class="list-item" href="#/q/${q.id}"><div class="small">${esc(q.text)}</div><div class="tiny">${q.ko} fallos de ${q.n}</div></a>`).join("")}</div></section>` : ""}
      ${s.hours.length ? `<section><h2>A qué hora rindes mejor</h2><div class="sheet">${pctBars(s.hours.filter((h) => h.n >= 5), (r) => `${String(r.h).padStart(2, "0")}:00 <span class="tiny">(${r.n})</span>`)}</div></section>` : ""}
    </main>`;
    $app.querySelector("#per").onclick = (e) => { const b = e.target.closest("button"); if (b) { period = b.dataset.v; LS.set("period", period); draw(); } };
  };
  draw();
}, "stats");

/* ------------------------------------------------------------------ simulacro */
route(/^\/simulacro$/, async () => {
  $app.innerHTML = topbar("Simulacro GSI", { back: true }) + loading();
  const [r, h] = await Promise.all([api("/simulacro"), api("/home")]);
  const open = r.items.find((x) => !x.finished_at);
  const done = r.items.filter((x) => x.finished_at);
  const nq = Object.values(r.per_block).reduce((a, b) => a + b, 0);
  $app.innerHTML = topbar("Simulacro GSI", { back: true }) + `<main>
    <section class="sheet"><h2>Como el examen real</h2>
      <p class="small muted">Primer ejercicio del GSI (ingreso libre): cuestionario de 4 opciones con una sola correcta, <b>acierto +1, fallo −1/3 y en blanco 0</b>. Con cuenta atrás y corrección al final; si se acaba el tiempo se corrige solo.</p>
      <div class="kpis" style="margin:12px 0">${Object.entries(r.per_block).map(([b, n]) => `<div class="sheet"><b>${n}</b><span>Bloque ${b} · ${esc(BLOQUES_GSI[b] || "")}</span></div>`).join("")}</div>
      <p class="tiny">${nq} preguntas, reparto proporcional al temario. Primero preguntas de exámenes oficiales y de escala A2, sin repetir las de tus simulacros del último mes. Ajusta preguntas y minutos en Ajustes.</p>
      ${open ? `<a class="btn block" href="#/t/${open.id}">Seguir con el simulacro abierto</a>` : `<button class="btn block" id="go">Empezar simulacro</button>`}
    </section>
    ${done.length ? `<section><h2>Simulacros anteriores</h2><div class="sheet">${done.map((x) => `<a class="list-item" href="#/t/${x.id}"><div class="row"><b class="grow">${fmtDate(x.finished_at)}</b><b class="${pctClass(x.nota10 * 10)}">${x.nota10.toFixed(2)}</b></div>
      <div class="tiny">${x.ok} aciertos · ${x.ko} fallos · ${x.blank} en blanco · ${x.score} puntos</div></a>`).join("")}</div></section>` : ""}
  </main>`;
  const go = $app.querySelector("#go");
  go && (go.onclick = async () => {
    if (h.open_test && h.open_test.kind !== "simulacro") { /* otro test abierto: no pasa nada, se puede volver luego */ }
    go.disabled = true;
    try { const t = await api("/simulacro", { body: {} }); location.hash = "#/t/" + t.id; }
    catch (e) { toast(e.message); go.disabled = false; }
  });
}, "test");

/* ------------------------------------------------------------------ mapa de temas */
const LVL = { dominado: "Dominado", bien: "Bien", flojo: "Flojo", mal: "Mal", nuevo: "Sin datos" };
route(/^\/mapa(?:\/(A1|A2))?$/, async (tem) => {
  tem = tem || LS.get("mapa", "A2");
  LS.set("mapa", tem);
  $app.innerHTML = topbar("Mapa de temas", { back: true }) + loading();
  const m = await api("/mapa?temario=" + tem);
  const groups = {};
  m.topics.forEach((x) => (groups[x.bloque] = groups[x.bloque] || []).push(x));
  const S = m.summary;
  $app.innerHTML = topbar("Mapa de temas", { back: true }) + `<main>
    <section><div class="seg"><a class="segl" href="#/mapa/A2" aria-pressed="${tem === "A2"}">A2 · GSI</a><a class="segl" href="#/mapa/A1" aria-pressed="${tem === "A1"}">A1 · CSSTIC</a></div></section>
    <section class="sheet"><div class="legend lv">${Object.keys(LVL).map((k) => `<span><i class="lv-${k}"></i>${LVL[k]} <b>${S[k] || 0}</b></span>`).join("")}<span><i class="lv-stale"></i>Olvidándose (+14 días)</span></div>
      <p class="tiny" style="margin-top:6px">El test rápido, el modo 5 minutos y las preguntas nuevas de cada día salen sobre todo de los temas flojos y de los que llevas tiempo sin tocar. Toca un tema para practicarlo.</p></section>
    ${Object.entries(groups).map(([b, xs]) => `<section><h2>${tem === "A2" ? "Bloque " + b + " · " + esc(BLOQUES_GSI[b] || "") : esc(b)}</h2>
      <div class="tmap">${xs.map((x) => `<button class="tile lv-${x.level} ${x.stale ? "stale" : ""}" data-id="${esc(x.id)}" title="${esc(x.title)}"><b>${x.num}</b><span>${x.accuracy != null ? x.accuracy + "%" : "·"}</span>${x.due ? `<i class="dot" aria-label="falladas por repasar"></i>` : ""}</button>`).join("")}</div></section>`).join("")}
  </main>`;
  $app.querySelectorAll(".tile").forEach((b) => b.addEventListener("click", () => {
    const x = m.topics.find((t) => t.id === b.dataset.id);
    modal(`<p class="tiny">${temaLabel(x.id)} · <b>${LVL[x.level]}</b>${x.stale ? " · olvidándose" : ""}</p><h2>${esc(x.title)}</h2>
      <p class="small muted">${x.answered ? `${x.answered} respuestas, ${x.accuracy}% de acierto · última vez hace ${x.days} día${x.days === 1 ? "" : "s"}` : "Aún no has respondido preguntas de este tema"}${x.due ? ` · ${x.due} falladas por repasar` : ""} · ${x.available} preguntas disponibles.</p>
      <div class="stack" style="margin-top:12px"><button class="btn block" id="t20">Test de 20 de este tema</button>
      <a class="btn ghost block" href="#/fichas/${encodeURIComponent(x.id)}">Fichas de este tema</a>
      <a class="btn quiet block" href="#/tema/${encodeURIComponent(x.id)}">Abrir el temario</a></div>`, (box, close) => {
      box.querySelectorAll("a").forEach((a) => a.addEventListener("click", close));
      box.querySelector("#t20").onclick = async () => {
        try { const t = await api("/tests", { body: { kind: "normal", n: 20, filters: { temario: tem, temas: [x.id], priorizar_no_vistas: true }, title: temaLabel(x.id) } }); close(); location.hash = "#/t/" + t.id; }
        catch (e) { toast(e.message); }
      };
    });
  }));
}, "stats");

/* ------------------------------------------------------------------ fichas */
route(/^\/fichas(?:\/([^/]+))?$/, async (doc) => {
  $app.innerHTML = topbar("Fichas", { back: true }) + loading();
  let r = await api("/fichas?limit=60" + (doc ? "&doc=" + encodeURIComponent(doc) + "&all=1" : ""));
  let i = 0, flipped = false, okN = 0, koN = 0;
  const intro = () => `<section class="sheet"><p class="small muted">La IA convierte cada pregunta que fallas en una ficha con el dato exacto que hay que recordar. Se crean solas en segundo plano (${r.requests_today}/${r.cap} lotes hoy) y se repasan con el mismo sistema inteligente que las falladas.</p>
    <p class="small">${r.total} fichas · ${r.due} por repasar hoy · ${r.pending} falladas aún sin ficha</p>
    ${r.pending ? `<button class="btn ghost small" id="gen">Crear 10 fichas ahora</button> <span class="small" id="genst"></span>` : ""}</section>`;
  const draw = () => {
    const f = r.items[i];
    if (!f) {
      $app.innerHTML = topbar("Fichas", { back: true }) + `<main>${okN + koN ? `<section class="sheet goal done"><div class="count">${okN} <small>de ${okN + koN} sabidas</small></div><p class="small muted" style="margin:6px 0 0">Las que no sabías volverán pronto.</p></section>` : ""}
        ${!r.items.length && !(okN + koN) ? `<div class="empty">${r.total ? "No tienes fichas por repasar hoy." : "Todavía no hay fichas."}</div>` : ""}
        ${intro()}
        ${r.by_doc && r.by_doc.length ? `<section><h2>Por tema</h2><div class="sheet">${r.by_doc.map((d) => `<a class="list-item" href="#/fichas/${encodeURIComponent(d.doc_id || "")}"><div class="small">${d.doc_id ? temaLabel(d.doc_id) + " · " + esc(d.title || "") : "Sin tema"}</div><div class="tiny">${d.n} fichas${d.due ? ` · <b style="color:var(--guide)">${d.due} hoy</b>` : ""}</div></a>`).join("")}</div></section>` : ""}
      </main>`;
      wireGen();
      return;
    }
    $app.innerHTML = topbar(doc ? temaLabel(doc) : "Fichas", { back: true, right: `<span class="small muted">${i + 1}/${r.items.length}</span>` }) + `<main>
      <div class="progress" aria-hidden="true"><i style="width:${(100 * i) / r.items.length}%"></i></div>
      <button class="flash ${flipped ? "on" : ""}" id="card" aria-live="polite">
        <span class="tiny">${f.doc_id ? temaLabel(f.doc_id) : ""}</span>
        <b class="concept">${esc(f.concepto)}</b>
        ${flipped ? `<span class="back">${esc(f.texto)}</span>` : `<span class="tiny">Piensa la respuesta y toca para darle la vuelta</span>`}
      </button>
      ${flipped ? `<div class="row" style="margin-top:14px"><button class="btn grow ko" id="no">No lo sabía</button><button class="btn grow okb" id="si">Lo sabía</button></div>
        ${f.question_id ? `<p class="tiny" style="text-align:center;margin-top:10px"><a href="#/q/${f.question_id}">Ver la pregunta original</a></p>` : ""}` : ""}
    </main>`;
    $app.querySelector("#card").onclick = () => { flipped = !flipped; draw(); };
    const ans = async (ok) => { try { await api(`/fichas/${f.id}/review`, { body: { ok } }); ok ? okN++ : koN++; i++; flipped = false; draw(); } catch (e) { toast(e.message); } };
    const no = $app.querySelector("#no"), si = $app.querySelector("#si");
    no && (no.onclick = () => ans(false)); si && (si.onclick = () => ans(true));
  };
  function wireGen() {
    const g = $app.querySelector("#gen"); if (!g) return;
    g.onclick = async () => {
      g.disabled = true; $app.querySelector("#genst").innerHTML = `<span class="spinner"></span>`;
      try { const x = await api("/fichas/generate", { body: {}, timeout: 120000 }); toast(`${x.created} fichas nuevas`); r = await api("/fichas?limit=60"); i = 0; draw(); }
      catch (e) { $app.querySelector("#genst").innerHTML = `<span class="err">${esc(e.message)}</span>`; g.disabled = false; }
    };
  }
  draw();
}, "repaso");

/* ------------------------------------------------------------------ supuesto práctico */
const SP_ORIGIN = { real: "Examen real", academia: "Academia", ia: "Nuevo · IA" };
const nota50 = (x) => (x == null ? "–" : String(Math.round(x * 100) / 100).replace(".", ","));
route(/^\/supuesto$/, async () => {
  $app.innerHTML = topbar("Supuesto práctico", { back: true }) + loading();
  let bloque = LS.get("spb", null);
  let r = await api("/sp" + (bloque ? "?bloque=" + bloque : ""));
  bloque = r.bloque;
  const draw = () => {
    const cases = r.cases.filter((c) => c.bloque === bloque);
    const open = r.attempts.find((a) => a.status === "abierto");
    const done = r.attempts.filter((a) => a.status !== "abierto");
    $app.innerHTML = topbar("Supuesto práctico", { back: true }) + `<main>
      <section><div class="seg" id="bq">${Object.entries(r.bloques).map(([k, v]) => `<button data-v="${k}" aria-pressed="${bloque === k}">${esc(v.split(" · ")[0])}</button>`).join("")}</div></section>
      ${open ? `<a class="btn block" href="#/sp/${open.id}">Seguir con «${esc(open.title)}»</a>` : ""}
      <section class="sheet"><h2>Segundo ejercicio del GSI</h2>
        <p class="small muted">5 preguntas, ${r.minutes} minutos. Escribe tus respuestas y añade fotos de lo que hagas a mano (diagramas). Se corrige con los criterios oficiales del INAP: <b>técnica 30, análisis 10, sistemática 5 y expresión 5</b>; se aprueba con 25.</p>
        <div class="row wrap" style="margin-top:10px"><button class="btn grow" id="real" ${cases.some((c) => c.origin !== "ia") ? "" : "disabled"}>Uno real al azar</button><button class="btn ghost grow" id="gen">${ICON.ai} Crear uno nuevo con IA</button></div>
        <p class="small" id="st"></p></section>
      <section class="sheet small muted">Tus documentos de supuestos: ${r.docs_ok} de ${r.docs_total} leídos en la Raspberry${r.pending_extract ? ` · la IA aún tiene ${r.pending_extract} por revisar para sacar enunciados (lo hace sola poco a poco) <button class="btn quiet small" id="ext">Revisar 2 ahora</button>` : ""}.</section>
      ${done.length ? `<section><h2>Tus supuestos</h2><div class="sheet">${done.map((a) => `<a class="list-item" href="#/sp/${a.id}"><div class="row"><b class="grow small">${esc(a.title)}</b><b class="${a.score == null ? "" : a.score >= 25 ? "okt" : "kot"}">${a.status === "corregido" ? nota50(a.score) + "/50" : a.status === "error" ? "error" : "corrigiendo…"}</b></div><div class="tiny">${fmtDate(a.finished_at || a.started_at)} · bloque ${a.bloque}</div></a>`).join("")}</div></section>` : ""}
      <section><h2>Catálogo · ${esc(r.bloques[bloque])}</h2><div class="sheet">${cases.length ? cases.map((c) => `<button class="list-item spc" data-id="${c.id}"><div class="row"><span class="tag ${c.origin === "ia" ? "ia" : c.origin === "real" ? "exam" : ""}">${SP_ORIGIN[c.origin]}</span><b class="grow small" style="text-align:left">${esc(c.title)}</b>${c.best != null ? `<b class="small">${nota50(c.best)}</b>` : ""}</div>
        <div class="tiny" style="text-align:left">${esc(c.year || "")}${c.has_solution ? " · con solución de academia" : ""}${c.tries ? ` · hecho ${c.tries} vez${c.tries > 1 ? "es" : ""}` : ""}</div></button>`).join("") : `<p class="muted small">Todavía no hay supuestos de este bloque en el catálogo. La IA los saca de tus PDF en segundo plano; mientras, puedes crear uno nuevo.</p>`}</div></section>
    </main>`;
    $app.querySelector("#bq").onclick = (e) => { const b = e.target.closest("button"); if (b) { bloque = b.dataset.v; LS.set("spb", bloque); draw(); } };
    const st = $app.querySelector("#st");
    const startCase = async (cid) => { try { const a = await api("/sp/start", { body: { case_id: cid } }); location.hash = "#/sp/" + a.id; } catch (e) { toast(e.message); } };
    $app.querySelectorAll(".spc").forEach((b) => b.onclick = async () => {
      const c = await api("/sp/case/" + b.dataset.id);
      modal(`<p class="tiny">${SP_ORIGIN[c.origin]} · bloque ${c.bloque} ${esc(c.year || "")}</p><h2>${esc(c.title)}</h2>
        <div class="small muted" style="max-height:30vh;overflow:auto;white-space:pre-wrap">${esc(c.enunciado.slice(0, 1200))}${c.enunciado.length > 1200 ? "…" : ""}</div>
        <ol class="small" style="margin:10px 0 0 18px">${c.preguntas.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
        <div class="stack" style="margin-top:12px"><button class="btn block" id="go">Empezar (cuenta atrás)</button></div>`, (box, close) => {
        box.querySelector("#go").onclick = () => { close(); startCase(c.id); };
      });
    });
    $app.querySelector("#real").onclick = () => { const pool = cases.filter((c) => c.origin !== "ia"); const fresh = pool.filter((c) => !c.tries); const pick = (fresh.length ? fresh : pool)[Math.floor(Math.random() * (fresh.length || pool.length))]; pick && startCase(pick.id); };
    $app.querySelector("#gen").onclick = async (e) => {
      e.target.disabled = true; st.innerHTML = `<span class="spinner"></span> Redactando un supuesto nuevo…`;
      try { const c = await api("/sp/generate", { body: { bloque }, timeout: 150000 }); st.textContent = ""; startCase(c.id); }
      catch (err) { st.innerHTML = `<span class="err">${esc(err.message)}</span>`; e.target.disabled = false; }
    };
    const ext = $app.querySelector("#ext");
    ext && (ext.onclick = async () => { ext.disabled = true; ext.innerHTML = `<span class="spinner"></span>`; try { r = await api("/sp/extract", { body: { k: 2 }, timeout: 300000 }); toast("Catálogo actualizado"); draw(); } catch (e) { toast(e.message); ext.disabled = false; ext.textContent = "Revisar 2 ahora"; } });
  };
  draw();
}, "test");

function shrinkImage(file, max = 1600) {
  return new Promise((res, rej) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas"); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      res(c.toDataURL("image/jpeg", 0.82));
    };
    img.onerror = () => rej(new Error("No se pudo leer la foto"));
    img.src = url;
  });
}

route(/^\/sp\/(\d+)$/, async (aid) => {
  $app.innerHTML = topbar("Supuesto", { back: true }) + loading();
  let a = await api("/sp/a/" + aid);
  if (a.status !== "abierto") return spResult(a);
  const c = a.case;
  const n = c.preguntas.length;
  let cur = +(sessionStorage.getItem("spq-" + aid) || 1);
  const imgUrl = (name) => `/api/sp/a/${aid}/img/${encodeURIComponent(name)}${token() ? "?" + tokq() : ""}`;
  const deadline = Date.now() + a.time_left * 1000;
  let dirty = false, saveT = null;
  guard = { hash: "#/sp/" + aid, sp: true, onFinish: () => deliver(true) };
  document.body.classList.add("testing");
  const clock = () => {
    const el = document.getElementById("clock"); const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    if (el) { el.textContent = `${Math.floor(left / 3600)}:${String(Math.floor(left / 60) % 60).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`; el.classList.toggle("low", left < 900); }
    if (left <= 0 && guard) { clearInterval(tickTimer); tickTimer = null; toast("Se acabó el tiempo: se entrega", 3500); deliver(true); }
  };
  tickTimer = setInterval(clock, 1000);
  async function save() {
    if (!dirty) return; dirty = false;
    const ta = $app.querySelector("#ans"); if (ta) a.answers[cur] = ta.value;
    try { await api(`/sp/a/${aid}/save`, { body: { answers: a.answers } }); const s = $app.querySelector("#sv"); s && (s.textContent = "Guardado"); }
    catch (e) { dirty = true; const s = $app.querySelector("#sv"); s && (s.textContent = "Sin guardar: " + e.message); }
  }
  const draw = () => {
    sessionStorage.setItem("spq-" + aid, cur);
    const imgs = a.images[cur] || [];
    $app.innerHTML = topbar(c.title, { back: true, right: `<span class="clock" id="clock"></span>` }) + `<main>
      <details class="sheet spenun" ${cur === 1 && !(a.answers[1] || "").length ? "open" : ""}><summary><b>Enunciado</b> <span class="tiny">bloque ${c.bloque}</span></summary><div class="small" style="white-space:pre-wrap;margin-top:8px">${esc(c.enunciado)}</div></details>
      <div class="qtabs">${c.preguntas.map((_, i) => `<button data-i="${i + 1}" aria-pressed="${cur === i + 1}" class="${(a.answers[i + 1] || "").trim() || (a.images[i + 1] || []).length ? "has" : ""}">${i + 1}</button>`).join("")}</div>
      <div class="qtext" style="font-size:1rem">${cur}. ${esc(c.preguntas[cur - 1])}</div>
      <textarea id="ans" class="spans" placeholder="Escribe tu respuesta. Para los diagramas puedes describirlos (actores y casos de uso, entidades y relaciones con cardinalidad, mensajes numerados…) o añadir fotos de lo que hagas en papel.">${esc(a.answers[cur] || "")}</textarea>
      <div class="row" style="margin-top:6px"><span class="tiny grow" id="sv">${(a.answers[cur] || "").length ? "Guardado" : ""}</span><span class="tiny" id="cc">${(a.answers[cur] || "").length} caracteres</span></div>
      <div class="thumbs">${imgs.map((nm) => `<div class="th"><img src="${imgUrl(nm)}" alt="Foto de la respuesta"><button data-n="${esc(nm)}" aria-label="Quitar foto">×</button></div>`).join("")}
        <label class="th add"><input type="file" accept="image/*" multiple hidden id="pic"><span>+ Foto</span></label></div>
    </main>
    <div class="testbar"><div class="in">
      <button class="btn quiet" id="prev" ${cur === 1 ? "disabled" : ""} aria-label="Anterior">‹</button>
      ${cur < n ? `<button class="btn grow" id="next">Siguiente pregunta</button>` : `<button class="btn grow guide" id="fin">Entregar y corregir</button>`}
    </div></div>`;
    const ta = $app.querySelector("#ans");
    ta.oninput = () => { a.answers[cur] = ta.value; dirty = true; $app.querySelector("#sv").textContent = "…"; $app.querySelector("#cc").textContent = ta.value.length + " caracteres"; clearTimeout(saveT); saveT = setTimeout(save, 1500); };
    $app.querySelector(".qtabs").onclick = async (e) => { const b = e.target.closest("button"); if (!b) return; await save(); cur = +b.dataset.i; draw(); };
    $app.querySelector("#prev").onclick = async () => { await save(); cur--; draw(); };
    const nx = $app.querySelector("#next"); nx && (nx.onclick = async () => { await save(); cur++; draw(); window.scrollTo(0, 0); });
    const fn = $app.querySelector("#fin"); fn && (fn.onclick = () => deliver(false));
    $app.querySelector("#pic").onchange = async (e) => {
      for (const f of e.target.files) {
        try { const data = await shrinkImage(f); const r = await api(`/sp/a/${aid}/image`, { body: { n: cur, data } }); a.images = r.images; }
        catch (err) { toast(err.message); }
      }
      draw();
    };
    $app.querySelectorAll(".th button").forEach((b) => b.onclick = async () => { const r = await api(`/sp/a/${aid}/image/del`, { body: { n: cur, name: b.dataset.n } }); a.images = r.images; draw(); });
    clock();
  };
  async function deliver(force) {
    await save();
    const empty = c.preguntas.filter((_, i) => !(a.answers[i + 1] || "").trim() && !(a.images[i + 1] || []).length).length;
    if (!force && !confirm(empty ? `Tienes ${empty} pregunta${empty > 1 ? "s" : ""} sin responder. ¿Entregar igualmente?` : "¿Entregar el supuesto para corregirlo?")) return;
    guard = null; if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    try { a = await api(`/sp/a/${aid}/finish`, { body: {} }); } catch (e) { return toast(e.message); }
    spResult(a);
  }
  draw();
}, "test");

function spResult(a) {
  document.body.classList.remove("testing");
  const c = a.case;
  const imgUrl = (name) => `/api/sp/a/${a.id}/img/${encodeURIComponent(name)}${token() ? "?" + tokq() : ""}`;
  if (a.status === "corrigiendo") {
    $app.innerHTML = topbar(c.title, { back: true }) + `<main><div class="empty"><span class="spinner"></span><p>Corrigiendo con los criterios del tribunal… suele tardar uno o dos minutos. Te llegará un aviso al terminar.</p></div></main>`;
    const t = setInterval(async () => {
      if (!location.hash.startsWith("#/sp/" + a.id)) return clearInterval(t);
      try { const n = await api("/sp/a/" + a.id); if (n.status !== "corrigiendo") { clearInterval(t); spResult(n); } } catch (e) {}
    }, 5000);
    return;
  }
  if (a.status === "error") {
    $app.innerHTML = topbar(c.title, { back: true }) + `<main><div class="empty err">No se pudo corregir: ${esc(a.error || "")}</div><button class="btn block" id="re">Volver a intentarlo</button></main>`;
    $app.querySelector("#re").onclick = async () => spResult(await api(`/sp/a/${a.id}/finish`, { body: {} }));
    return;
  }
  const r = a.result || {}, p = r.puntuacion || {};
  const crit = [["tecnica", "Conocimientos técnicos aplicados", 30], ["analisis", "Capacidad de análisis", 10], ["sistematica", "Sistemática", 5], ["expresion", "Expresión escrita", 5]];
  const pq = {}; (r.por_pregunta || []).forEach((x) => (pq[x.n] = x));
  $app.innerHTML = topbar(c.title, { back: true }) + `<main>
    <section class="sheet"><div class="goalrow"><div class="spscore ${r.total >= 25 ? "ok" : "ko"}"><b>${nota50(r.total)}</b><span>de 50</span></div>
      <div class="goalinfo"><b>${r.total >= 25 ? "Aprobado" : "Por debajo de 25"}</b><span>${esc(r.resumen || "")}</span></div></div>
      <div style="margin-top:12px">${crit.map(([k, t, m]) => `<div class="row small" style="margin-top:6px"><span class="grow">${t}</span><b>${nota50(p[k])} / ${m}</b></div><div class="pct ${pctClass(100 * (p[k] || 0) / m)}"><i style="width:${100 * (p[k] || 0) / m}%"></i></div>`).join("")}</div>
      <p class="tiny" style="margin-top:10px">Corrección orientativa de la IA con los criterios del INAP${c.solutions && c.solutions.length ? ", apoyada en la solución de la academia" : ""}. Los conceptos flojos se han añadido a tus fichas.</p></section>
    ${(r.consejos || []).length ? `<section class="sheet"><h3>Consejos para el examen</h3><ul class="small" style="margin:6px 0 0 18px">${r.consejos.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>` : ""}
    <section>${c.preguntas.map((q, i) => { const x = pq[i + 1] || {}; const imgs = a.images[i + 1] || [];
      return `<details class="sheet spq"><summary><span class="spn ${x.nota >= 5 ? "ok" : "ko"}">${x.nota != null ? String(x.nota).replace(".", ",") : "–"}</span><span class="small grow">${i + 1}. ${esc(q)}</span></summary>
        ${x.valoracion ? `<p class="small" style="margin-top:8px"><b>${esc(x.valoracion)}</b></p>` : ""}
        ${(x.bien || []).length ? `<p class="tiny" style="margin-top:6px">Bien</p><ul class="small okl">${x.bien.map((y) => `<li>${esc(y)}</li>`).join("")}</ul>` : ""}
        ${(x.falta || []).length ? `<p class="tiny" style="margin-top:6px">Te faltó</p><ul class="small kol">${x.falta.map((y) => `<li>${esc(y)}</li>`).join("")}</ul>` : ""}
        ${(x.errores || []).length ? `<p class="tiny" style="margin-top:6px">Errores</p><ul class="small kol">${x.errores.map((y) => `<li>${esc(y)}</li>`).join("")}</ul>` : ""}
        <details style="margin-top:8px"><summary class="small"><b>Tu respuesta</b></summary><div class="small" style="white-space:pre-wrap;margin-top:6px">${esc(a.answers[i + 1] || "(en blanco)")}</div>${imgs.length ? `<div class="thumbs">${imgs.map((nm) => `<a class="th" href="${imgUrl(nm)}" target="_blank"><img src="${imgUrl(nm)}" alt=""></a>`).join("")}</div>` : ""}</details>
        ${x.solucion_modelo ? `<details style="margin-top:8px"><summary class="small"><b>Respuesta modelo</b></summary><div class="small note expl" style="white-space:pre-wrap;margin-top:6px">${esc(x.solucion_modelo)}</div></details>` : ""}
        ${(x.refs || []).length ? `<p class="tiny" style="margin-top:8px">En tus apuntes: ${x.refs.map((rf) => `<a href="${jumpHref(rf.doc_id, rf.page, rf.snip)}">${esc(rf.title.slice(0, 50))} · pág. ${rf.page}</a>`).join(" · ")}</p>` : ""}
      </details>`; }).join("")}</section>
    ${c.solutions && c.solutions.length ? `<section class="sheet"><h3>Solución de la academia</h3>${c.solutions.map((s) => `<a class="list-item small" href="#/tema/${s.id}">${esc(s.title || s.id)}</a>`).join("")}</section>` : ""}
    <section class="sheet"><details><summary><b>Enunciado</b></summary><div class="small" style="white-space:pre-wrap;margin-top:8px">${esc(c.enunciado)}</div></details></section>
    <section class="row wrap"><a class="btn grow" href="#/supuesto">Otro supuesto</a><a class="btn ghost grow" href="#/fichas">Repasar fichas</a></section>
  </main>`;
}

/* ------------------------------------------------------------------ leyes por artículos */
route(/^\/leyes(?:\/(A1|A2))?$/, async (tem) => {
  tem = tem || LS.get("leyesT", "A2"); LS.set("leyesT", tem);
  $app.innerHTML = topbar("Leyes por artículos", { back: true }) + loading();
  const r = await api("/leyes?temario=" + tem);
  $app.innerHTML = topbar("Leyes por artículos", { back: true }) + `<main>
    <section><div class="seg"><a class="segl" href="#/leyes/A2" aria-pressed="${tem === "A2"}">A2 · GSI</a><a class="segl" href="#/leyes/A1" aria-pressed="${tem === "A1"}">A1 · CSSTIC</a></div></section>
    <section class="sheet small muted">Texto consolidado y vigente del BOE, descargado por la Raspberry. La IA crea preguntas literales de plazos, órganos, cifras y excepciones citando el artículo (${r.requests_today}/${r.cap} tandas hoy). También salen en los tests normales.</section>
    <section class="sheet">${r.laws.map((l) => `<div class="list-item lawrow"><a href="#/ley/${encodeURIComponent(l.id)}" class="grow" style="text-decoration:none;color:inherit"><b class="small">${esc(l.short)}</b> <span class="small muted">${esc(l.title)}</span>
        <div class="tiny">${l.status === "ok" ? `${l.n_articles} artículos · ${l.nq} preguntas${l.accuracy != null ? ` · ${l.accuracy}% de acierto en ${l.answered}` : ""}` : l.status === "error" ? `<span class="err">no se pudo descargar: ${esc(l.error || "")}</span>` : "descargando del BOE…"}</div></a>
        ${l.nq ? `<button class="btn small" data-t="${esc(l.id)}">Test</button>` : l.status === "ok" ? `<button class="btn small quiet" data-g="${esc(l.id)}">${ICON.ai}</button>` : ""}</div>`).join("")}</section>
  </main>`;
  $app.querySelectorAll("[data-t]").forEach((b) => b.onclick = async () => {
    const l = r.laws.find((x) => x.id === b.dataset.t);
    try { const t = await api("/tests", { body: { kind: "normal", n: 20, filters: { ley: l.id, priorizar_no_vistas: true }, title: l.short } }); location.hash = "#/t/" + t.id; } catch (e) { toast(e.message); }
  });
  $app.querySelectorAll("[data-g]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.innerHTML = `<span class="spinner"></span>`;
    try { const x = await api(`/leyes/${encodeURIComponent(b.dataset.g)}/generate`, { body: { n: 8 }, timeout: 150000 }); toast(`${x.created} preguntas nuevas`); render(); } catch (e) { toast(e.message); b.disabled = false; b.innerHTML = ICON.ai; }
  });
}, "temario");

route(/^\/ley\/([^/]+)(?:\/(.+))?$/, async (lid, art) => {
  $app.innerHTML = topbar("Ley", { back: true }) + loading();
  const r = await api("/leyes/" + encodeURIComponent(lid));
  const L = r.law;
  let q = "";
  const draw = () => {
    const ql = q.toLowerCase();
    const list = q ? r.articles.filter((a) => a.texto.toLowerCase().includes(ql) || (a.titulo || "").toLowerCase().includes(ql) || a.num.toLowerCase().includes(ql)) : r.articles;
    $app.querySelector("#arts").innerHTML = list.slice(0, 400).map((a) => `<details class="sheet art" id="art-${a.idx}" ${art && a.num === art ? "open" : ""}><summary><b>${esc(a.num)}</b> <span class="small muted">${esc(a.titulo || "")}</span>${a.nq ? ` <span class="tiny">· ${a.nq} preg.</span>` : ""}</summary><div class="small" style="white-space:pre-wrap;margin-top:8px">${esc(a.texto)}</div></details>`).join("") || `<p class="muted small">Sin resultados.</p>`;
  };
  $app.innerHTML = topbar(L.short, { back: true }) + `<main>
    <section><h2 style="font-size:1.1rem">${esc(L.title)}</h2><p class="tiny">${L.n_articles} preceptos · texto consolidado del BOE${L.fetched_at ? " · actualizado " + fmtDate(L.fetched_at) : ""}</p>
      <div class="row wrap"><button class="btn grow" id="tt">Test de esta ley</button><button class="btn ghost grow" id="gen">${ICON.ai} 8 preguntas nuevas</button></div></section>
    <section><input type="search" id="sq" placeholder="Buscar: «plazo», «tres meses», «artículo 21»…" aria-label="Buscar en la ley"></section>
    <section id="arts"></section></main>`;
  draw();
  if (art) { const el = $app.querySelector("details[open]"); el && el.scrollIntoView({ block: "start" }); }
  $app.querySelector("#sq").oninput = (e) => { q = e.target.value.trim(); draw(); };
  $app.querySelector("#tt").onclick = async () => { try { const t = await api("/tests", { body: { kind: "normal", n: 20, filters: { ley: L.id, priorizar_no_vistas: true }, title: L.short } }); location.hash = "#/t/" + t.id; } catch (e) { toast(e.message.includes("No hay") ? "Aún no hay preguntas de esta ley: genera unas cuantas" : e.message); } };
  $app.querySelector("#gen").onclick = async (e) => { e.target.disabled = true; try { const x = await api(`/leyes/${encodeURIComponent(L.id)}/generate`, { body: { n: 8 }, timeout: 150000 }); toast(`${x.created} preguntas nuevas`); } catch (err) { toast(err.message); } e.target.disabled = false; };
}, "temario");

/* ------------------------------------------------------------------ ajustes */
route(/^\/ajustes$/, async () => {
  $app.innerHTML = topbar("Ajustes", { back: true }) + loading();
  const s = await api("/settings");
  const theme = LS.get("theme", "auto");
  const num = (k, label, min, max) => `<label class="field"><span>${label}</span><input type="number" data-k="${k}" min="${min}" max="${max}" value="${s[k]}"></label>`;
  $app.innerHTML = topbar("Ajustes", { back: true }) + `<main>
    <section class="sheet"><h2>Estudio diario</h2>
      ${num("daily_goal", "Mínimo diario de preguntas", 1, 1000)}
      ${num("daily_new_questions", "Preguntas nuevas generadas cada día (0 = no generar)", 0, 100)}
      <label class="field"><span>Dificultad de las preguntas de IA ${s.gen_level_auto ? `(automática, ahora nivel ${s.gen_level})` : ""}</span>
        <select data-k="gen_level">${[["auto", "Automática según tus resultados"], ["1", "1 · Como la media del examen"], ["2", "2 · Alta"], ["3", "3 · Muy alta"]]
          .map(([v, t]) => `<option value="${v}" ${(s.gen_level_auto ? "auto" : String(s.gen_level)) === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <label class="field"><span>Escala que preparas (para las preguntas diarias)</span><select data-k="default_escala">${["A1", "A2", "C1"].map((v) => `<option ${s.default_escala === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      ${num("ai_prefetch_daily", "Explicaciones de IA preparadas por adelantado al día (0 = ninguna)", 0, 200)}
      ${num("net_prefetch_daily", "Búsquedas de Internet preparadas por adelantado al día (necesita clave de Tavily; 0 = ninguna)", 0, 500)}
      <label class="field"><span>Lote nocturno (recorre todo el banco de ${String(s.batch_start_hour ?? 1).padStart(2, "0")}:00 a ${String(s.batch_end_hour ?? 8).padStart(2, "0")}:00 con la cuota sobrante)</span>
        <select data-k="batch_enabled"><option value="1" ${s.batch_enabled !== false ? "selected" : ""}>Activado</option><option value="0" ${s.batch_enabled === false ? "selected" : ""}>Desactivado</option></select></label>
      <div class="row">${num("batch_max_requests", "Peticiones por noche (10 preguntas cada una)", 0, 1000)}${num("batch_net_nightly", "Búsquedas extra por noche", 0, 1000)}</div>
      <label class="field"><span>Modelo del lote (vacío = el «lite» de reserva)</span><input type="text" data-k="batch_model" value="${esc(s.batch_model || "")}"></label>
      <label class="field"><span>Repaso inteligente: cuánto quieres recordar</span><select data-k="target_retention">${[["0.85", "85 % · menos repasos"], ["0.9", "90 % · equilibrado"], ["0.95", "95 % · más repasos, más seguro"]].map(([v, t]) => `<option value="${v}" ${Math.abs((s.target_retention ?? 0.9) - +v) < 0.001 ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      ${num("fichas_daily_requests", "Lotes de fichas al día (10 fichas cada uno; 0 = no crear)", 0, 50)}
      <div class="row">${num("sim_questions", "Preguntas del simulacro", 10, 105)}${num("sim_minutes", "Minutos del simulacro", 5, 240)}</div>
      <div class="row"><label class="field grow"><span>Bloque del supuesto práctico</span><select data-k="sp_bloque">${[["III", "III · Desarrollo"], ["IV", "IV · Sistemas"]].map(([v, t]) => `<option value="${v}" ${s.sp_bloque === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>${num("sp_minutes", "Minutos del supuesto", 30, 300)}</div>
      <div class="row">${num("sp_extract_daily", "Documentos de supuestos leídos por la IA al día", 0, 100)}${num("leyes_daily_requests", "Tandas de preguntas de leyes al día (8 cada una)", 0, 50)}</div>
      <div class="row">${num("daily_gen_hour", "Hora de generación", 0, 23)}${num("review_reminder_hour", "Aviso de repaso", 0, 23)}${num("goal_reminder_hour", "Aviso de mínimo", 0, 23)}</div>
    </section>
    <section class="sheet"><h2>Inteligencia artificial (Gemini)</h2>
      <p class="small muted">Consigue una API key gratuita en aistudio.google.com → Get API key.</p>
      <label class="field"><span>API key ${s.gemini_api_key_set ? `(guardada, acaba en ${esc(s.gemini_api_key_hint)})` : "(sin configurar)"}</span><input type="password" id="key" placeholder="${s.gemini_api_key_set ? "Déjala vacía para mantenerla" : "AIza…"}" autocomplete="off"></label>
      <label class="field"><span>Modelo</span><input type="text" data-k="gemini_model" value="${esc(s.gemini_model)}"></label>
      <label class="field"><span>Modelos de reserva (separados por comas)</span><input type="text" data-k="gemini_fallback_models" value="${esc((s.gemini_fallback_models || []).join(", "))}"></label>
      <div class="row"><button class="btn quiet grow" id="tai">Probar la IA</button></div><p class="small" id="taist"></p>
    </section>
    <section class="sheet"><h2>Búsqueda en Internet (Tavily)</h2>
      <p class="small muted">Sin clave, la app busca en DuckDuckGo y Wikipedia, pero DuckDuckGo bloquea a ratos las búsquedas automáticas. Con una clave gratuita de Tavily (app.tavily.com, 1.000 búsquedas al mes y sin tarjeta) las búsquedas son estables y se pueden precargar.</p>
      <label class="field"><span>Clave de Tavily ${s.tavily_key_set ? `(guardada, acaba en ${esc(s.tavily_key_hint)} · ${s.tavily_used} usadas este mes)` : "(sin configurar)"}</span><input type="password" id="tkey" placeholder="${s.tavily_key_set ? "Déjala vacía para mantenerla; «-» para borrarla" : "tvly-…"}" autocomplete="off"></label>
    </section>
    <section class="sheet"><h2>Avisos y aplicación</h2>
      <div class="row wrap"><button class="btn quiet grow" id="dg">Diagnóstico</button></div><div id="dgo" class="small" style="margin:8px 0 12px"></div>
      <div class="row wrap"><button class="btn quiet grow" id="tn">Probar notificación</button>${isAndroid ? `<button class="btn quiet grow" id="srv">Cambiar servidor</button>` : ""}</div>
      <label class="field"><span>Tema de color</span><select id="theme">${[["auto", "Como el sistema"], ["light", "Claro"], ["dark", "Oscuro"]].map(([v, t]) => `<option value="${v}" ${theme === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <p class="tiny">Servidor: ${esc(location.host)} · temario en ${esc(s.temario_dir)}</p>
    </section>
    <button class="btn block" id="save">Guardar cambios</button><p></p></main>`;
  $app.querySelector("#save").onclick = async () => {
    const body = {};
    $app.querySelectorAll("[data-k]").forEach((el) => (body[el.dataset.k] = el.value));
    const key = $app.querySelector("#key").value.trim(); if (key) body.gemini_api_key = key;
    const tkey = $app.querySelector("#tkey").value.trim(); if (tkey) body.tavily_api_key = tkey;
    try { await api("/settings", { body }); toast("Cambios guardados"); render(); } catch (e) { toast(e.message); }
  };
  $app.querySelector("#tai").onclick = async () => {
    const st = $app.querySelector("#taist"); st.innerHTML = `<span class="spinner"></span>`;
    const key = $app.querySelector("#key").value.trim();
    try {
      if (key) await api("/settings", { body: { gemini_api_key: key } });
      const r = await api("/settings/test_ai", { body: {}, timeout: 75000 });
      st.innerHTML = `Funciona con <b>${esc(r.model)}</b>.${(r.notes || []).map((n) => " " + esc(n)).join("")}`;
      const mi = $app.querySelector('[data-k="gemini_model"]'), fi = $app.querySelector('[data-k="gemini_fallback_models"]');
      if (mi) mi.value = r.model; if (fi) fi.value = (r.fallbacks || []).join(", ");
    }
    catch (e) { st.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  $app.querySelector("#dg").onclick = async () => {
    const o = $app.querySelector("#dgo"); o.innerHTML = `<span class="spinner"></span>`;
    try {
      const d = await api("/diag");
      const busy = d.load && d.cpus && d.load[0] > d.cpus * 0.9;
      o.innerHTML = `<p>Carga de la Pi: <b>${(d.load || []).join(" · ")}</b> (${d.cpus} núcleos)${busy ? ' <span class="err">— saturada</span>' : ""} · temperatura ${d.temp ?? "?"} °C · RAM libre ${d.mem_free_mb ?? "?"} MB · consulta al temario ${d.db_ms} ms</p>
        <p>OCR: ${d.ocr.ok} de ${d.ocr.n} documentos listos${d.ocr.working ? ", procesando ahora" : ""}. Modelo: ${esc(d.model)}</p>
        ${d.prefetch ? `<p style="margin-top:6px"><b>Preparadas por adelantado:</b> IA ${d.prefetch.ia_today}/${d.prefetch.ia_cap} hoy (${d.prefetch.ia_ready} guardadas, ${d.prefetch.ia_pending} en cola) · Internet ${d.prefetch.net_today}/${d.prefetch.net_cap} hoy (${d.prefetch.net_ready} guardadas, ${d.prefetch.net_pending} en cola)</p>` : ""}
        ${d.night ? `<p style="margin-top:6px"><b>Banco precargado:</b> IA ${d.night.ia_ready.toLocaleString("es-ES")} de ${d.night.ia_total.toLocaleString("es-ES")} (${Math.round(100 * d.night.ia_ready / d.night.ia_total)}%) · Internet ${d.night.net_ready.toLocaleString("es-ES")} de ${d.night.net_total.toLocaleString("es-ES")} (${Math.round(100 * d.night.net_ready / d.night.net_total)}%)</p>
          <p class="tiny">Lote nocturno ${d.night.enabled ? `activado (${d.night.hours}, modelo ${esc(d.night.model)})` : "desactivado"}${d.night.avg_per_night ? ` · media ${d.night.avg_per_night} por noche · faltan unos ${d.night.days_left} días` : " · aún sin noches completadas"}</p>` : ""}
        ${d.search ? `<p style="margin-top:6px"><b>Búsqueda en Internet:</b> Tavily ${d.search.tavily_key ? `${d.search.tavily_month} consultas este mes` : "sin clave"}${["tavily", "duckduckgo", "wikipedia"].filter((e) => d.search[e].paused_until).map((e) => ` · <span class="err">${e} en pausa hasta las ${d.search[e].paused_until} (${esc(d.search[e].why)})</span>`).join("")}</p>` : ""}
        <p style="margin-top:6px"><b>Peticiones a Gemini hoy:</b> ${Object.entries(d.usage || {}).filter(([k]) => !k.startsWith("_")).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ") || "ninguna"}
          ${Object.entries(d.usage || {}).filter(([k]) => k.startsWith("_")).map(([k, v]) => `<span class="tiny">(${esc(k.slice(1))}: ${v})</span>`).join(" ")}</p>
        ${Object.keys(d.blocked || {}).length ? Object.entries(d.blocked).map(([m, b]) => `<p class="err tiny">${esc(m)}: ${esc(b.why)} — vuelve a las ${b.until}</p>`).join("") : ""}
        ${d.gen_retry ? `<p class="tiny">La generación diaria se reintentará a las ${d.gen_retry}.</p>` : ""}
        ${d.calls.length ? `<p style="margin-top:6px"><b>Últimas llamadas a la IA</b></p>` + d.calls.map((c) => `<div class="tiny">${c.when} · ${esc(c.kind)} · ${esc(c.model)} · <b>${c.secs} s</b> · ${c.ok ? "ok" : '<span class="err">' + esc(c.note) + "</span>"}</div>`).join("") : `<p class="tiny">Aún no hay llamadas registradas desde el último reinicio.</p>`}`;
    } catch (e) { o.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  $app.querySelector("#tn").onclick = async () => { await api("/notifications/test", { body: {} }); if (isAndroid) window.Android.checkNow(); toast(isAndroid ? "Enviada: debería llegar en unos segundos" : "Creada (las notificaciones llegan en la app del móvil)"); };
  const srv = $app.querySelector("#srv"); srv && (srv.onclick = () => window.Android.openSettings());
  $app.querySelector("#theme").onchange = (e) => { LS.set("theme", e.target.value); applyTheme(); };
});

function applyTheme() {
  const t = LS.get("theme", "auto");
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = t;
  // la APK pinta sus barras (estado y navegación) del mismo color que el fondo
  if (isAndroid && window.Android.setBars) {
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim() || "#eef1f6";
    const dark = t === "dark" || (t === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    try { window.Android.setBars(bg, dark); } catch (e) {}
  }
}
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme); } catch (e) {}
applyTheme();
render();
