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
  if (opts.body) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  if (token()) o.headers["X-Token"] = token();
  let r;
  try { r = await fetch("/api" + path, o); }
  catch (e) { throw new Error("Sin conexión con la Raspberry. Comprueba que Tailscale está activo."); }
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
  return `<header class="top">${back ? `<button class="back" aria-label="Volver" onclick="history.back()">‹</button>` : ""}<h1>${esc(title)}</h1>${right}</header>`;
}
const loading = () => `<div class="empty"><span class="spinner"></span></div>`;
const errBox = (e) => `<main><div class="empty err">${esc(e.message || e)}</div></main>`;
const pctClass = (p) => (p == null ? "" : p >= 70 ? "" : p >= 50 ? "mid" : "low");
const fmtDate = (s) => { if (!s) return ""; const d = new Date(s.replace(" ", "T")); return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" }) + " " + d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }); };
const temaLabel = (id) => !id ? "" : id.startsWith("A1-") ? "A1 · tema " + parseInt(id.slice(3)) : "A2 · " + id.slice(3).replace("-", " tema ").replace(/ tema 0/, " tema ");
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

async function render() {
  const h = location.hash.replace(/^#/, "") || "/";
  document.body.classList.remove("testing");
  for (const r of routes) {
    const m = h.match(r.re);
    if (m) {
      document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === r.tab));
      window.scrollTo(0, 0);
      try { await r.fn(...m.slice(1).map(decodeURIComponent)); }
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
  const slots = Math.max(d.goal, d.answered);
  const seq = d.today_seq || "";
  let bub = "";
  for (let i = 0; i < Math.min(slots, 200); i++) {
    const c = seq[i] === "1" ? "ok" : seq[i] === "0" ? "ko" : "";
    bub += `<i class="${c} ${i >= d.goal ? "extra" : ""}"></i>`;
  }
  const pct = d.answered ? Math.round(100 * d.correct / d.answered) : null;
  const tem = d.temario || {};
  $app.innerHTML = topbar("Hoy", { right: `<a class="iconbtn" href="#/ajustes" aria-label="Ajustes">${ICON.gear}</a>` }) + `<main>
    <section class="sheet goal ${done ? "done" : ""}">
      <div class="count">${d.answered} <small>de ${d.goal} preguntas</small></div>
      <div class="bubbles" aria-hidden="true">${bub}</div>
      <p class="small muted" style="margin:8px 0 0">${done ? "Mínimo diario cumplido." : `Te faltan ${d.goal - d.answered} para el mínimo de hoy.`}
        ${pct != null ? ` Aciertas el ${pct}% hoy.` : ""} ${d.streak ? ` Racha: ${d.streak} día${d.streak > 1 ? "s" : ""}.` : ""}</p>
    </section>
    <section class="todo">
      ${d.open_test ? `<a href="#/t/${d.open_test.id}" class="hot"><span class="n">›</span><span class="t"><b>Seguir con el test</b><span>${esc(d.open_test.title)} · ${d.open_test.n} preguntas</span></span></a>` : ""}
      <a href="#/test/repaso" class="${d.review_due ? "hot" : ""}"><span class="n ${d.review_due ? "" : "zero"}">${d.review_due}</span><span class="t"><b>Falladas por repasar</b><span>${d.review_due ? "Toca repasarlas hoy" : d.review_total ? `${d.review_total} en seguimiento, ninguna para hoy` : "Aún no hay fallos que repasar"}</span></span></a>
      <a href="#/test/nuevas" class="${d.new_questions ? "hot" : ""}"><span class="n ${d.new_questions ? "" : "zero"}">${d.new_questions}</span><span class="t"><b>Preguntas nuevas</b><span>${d.new_questions ? "Generadas con IA, sin hacer" : "Se generan cada mañana"}</span></span></a>
      <a href="#/test/rapido"><span class="n">20</span><span class="t"><b>Test rápido</b><span>Aleatorias, priorizando las que no has visto</span></span></a>
    </section>
    ${!d.ai_ready ? `<section class="sheet"><h3>Activa la IA</h3><p class="small muted">Para generar preguntas nuevas y explicaciones, añade tu API key de Gemini.</p><a class="btn small" href="#/ajustes">Ir a ajustes</a></section>` : ""}
    ${tem.work || tem.nopdf ? `<section class="small muted">Temario: ${tem.ok} de ${tem.n} documentos indexados${tem.work ? ", leyendo escaneados con OCR" : ""}${tem.nopdf ? `, ${tem.nopdf} sin PDF en la Raspberry` : ""}.</section>` : ""}
    <section class="row"><a class="btn quiet small" href="#/historial">${ICON.hist} Historial</a><span class="grow"></span><span class="tiny">${d.total_questions.toLocaleString("es-ES")} preguntas · ${d.ia_questions} de IA</span></section>
  </main>`;
}, "home");

/* ------------------------------------------------------------------ crear test */
const defaultCfg = { temario: "", bloques: [], temas: [], escalas: [], origen: "todas", solo_examen: false, no_vistas: false, priorizar_no_vistas: true, n: 20, mode: "practica" };
let catalog = null;
async function getCatalog() { if (!catalog) catalog = await api("/catalog"); return catalog; }

route(/^\/test\/(repaso|nuevas|rapido)$/, async (kind) => {
  $app.innerHTML = topbar("Preparando test", { back: true }) + loading();
  try {
    const body = kind === "rapido" ? { kind: "normal", n: 20, filters: { priorizar_no_vistas: true }, title: "Test rápido" } : { kind, n: kind === "repaso" ? 100 : 50 };
    const t = await api("/tests", { body });
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
    $app.innerHTML = topbar(t.title || "Test", { back: true, right: `<button class="btn small quiet" id="nav">${pos + 1}/${t.n}</button>` }) + `<main>
      <div class="progress" aria-hidden="true"><i style="width:${(100 * answered()) / t.n}%"></i></div>
      <div class="qmeta">${tags}</div>
      <div class="qtext">${esc(it.text)}</div>
      <div class="opts" role="radiogroup">${L.filter((k) => it[k]).map((k) => {
        let c = "";
        if (shown) { if (k === it.correct) c = "right"; else if (k === it.chosen) c = "wrong"; }
        else if (k === it.chosen) c = "sel";
        return `<button class="opt ${c}" data-k="${k}" role="radio" aria-checked="${k === it.chosen}" ${shown ? "disabled" : ""}><span class="bub">${k}</span><span class="txt">${esc(it[k])}</span></button>`;
      }).join("")}</div>
      <div id="after">${shown ? afterAnswer(it) : t.mode === "practica" ? "" : `<p class="tiny" style="margin-top:12px">Modo examen: verás las soluciones al corregir. Acierto +1, fallo −1/3.</p>`}</div>
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
  };
  async function choose(k) {
    const it = t.items[pos];
    try {
      const r = await api(`/tests/${id}/answer`, { body: { pos, chosen: k, ms: Date.now() - t0 } });
      if (t.mode === "practica") Object.assign(it, r); else it.chosen = k;
      draw();
      if (t.mode === "examen" && pos < t.n - 1) setTimeout(() => { pos++; t0 = Date.now(); draw(); }, 180);
    } catch (e) { toast(e.message); }
  }
  async function finish() {
    const left = t.n - answered();
    if (left && !confirm(`Te quedan ${left} sin responder. ¿Corregir igualmente?`)) return;
    t = await api(`/tests/${id}/finish`, { body: {} });
    sessionStorage.removeItem(key);
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
    ${it.origin === "ia" ? rateBlock(it) : ""}
    ${sourcesBlock(it)}`;
}
function rateBlock(it) {
  const b = (v, t) => `<button class="chip" data-rate="${v}" aria-pressed="${it.rating === v}">${t}</button>`;
  return `<div class="row wrap" data-rq="${it.id}" style="margin-top:10px"><span class="small muted">¿Nivel de examen?</span>
    ${b("facil", "Demasiado fácil")}${b("bien", "Nivel adecuado")}</div>`;
}
function sourcesBlock(it) {
  return `<div class="srcs" data-q="${it.id}" data-ch="${it.chosen || ""}">
      <button data-s="temario">${ICON.book}Temario</button><button data-s="internet">${ICON.web}Internet</button><button data-s="ia">${ICON.ai}IA</button></div>
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
const hl = (s) => esc(s).replace(/\[\[/g, "<mark>").replace(/\]\]/g, "</mark>");
/* Enlace al tema que salta al párrafo del fragmento y lo resalta */
function jumpHref(doc, page, snip) {
  const terms = [...new Set([...(snip || "").matchAll(/\[\[(.+?)\]\]/g)].map((m) => m[1]))].slice(0, 12);
  const passage = (snip || "").replace(/\[\[|\]\]/g, "").replace(/^…|…$/g, "").trim().slice(0, 400);
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
  el.innerHTML = `<div class="sheet"><span class="spinner"></span> ${which === "ia" ? "Preguntando a la IA…" : which === "internet" ? "Buscando en Internet…" : "Buscando en el temario…"}</div>`;
  try {
    const r = await api(`/questions/${it.id}/sources/${which}?chosen=${it.chosen || ""}${refresh ? "&refresh=1" : ""}`);
    if (which === "temario") {
      el.innerHTML = `<div class="sheet">${r.hits.length ? r.hits.map((h) => `<div class="hit"><div class="where"><a href="${jumpHref(h.doc_id, h.page, h.snip)}">${h.temario} · ${h.temario === "A2" ? "Bloque " + h.bloque + ", " : ""}tema ${h.num} · pág. ${h.page}</a> — ${esc(h.title.slice(0, 70))}</div><div class="snip">${hl(h.snip)}</div></div>`).join("")
        : `<p class="muted small">No hay coincidencias en el temario indexado (${r.indexed_pages} páginas).</p>`}</div>`;
    } else if (which === "internet") {
      el.innerHTML = `<div class="sheet">${r.results.length ? r.results.map((x) => `<div class="hit"><div class="where"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a></div><div class="snip">${esc(x.snippet)}</div></div>`).join("")
        : `<p class="muted small">No se obtuvieron resultados${r.errors && r.errors.length ? ": " + esc(r.errors.join("; ")) : ""}.</p>`}
        <p class="tiny" style="margin-top:8px"><a href="${esc(r.search_url)}" target="_blank" rel="noopener">Buscar en el navegador</a></p></div>`;
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
function results(t) {
  document.body.classList.remove("testing");
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
        <a class="btn ghost grow" href="#/test">Otro test</a></section>
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
  const boxes = ["mañana", "3 días", "1 semana", "2 semanas", "1 mes"];
  $app.innerHTML = topbar("Repaso") + `<main>
    <section class="sheet"><div class="count" style="font-size:2.2rem;font-weight:800;line-height:1">${r.due} <small class="muted" style="font-size:1rem;font-weight:600">para hoy</small></div>
      <p class="small muted" style="margin:6px 0 12px">Cada fallada vuelve a los 1, 3, 7, 15 y 30 días. Si aciertas, sube de nivel; si fallas, vuelve al principio. ${r.total} en seguimiento.</p>
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
  const bl = tem === "A1" ? cat.bloques_a1 : cat.bloques_a2;
  const docs = cat.docs[tem];
  const groups = Object.keys(bl).map((k) => [k, bl[k], docs.filter((d) => d.bloque === k)]);
  if (tem === "A2") groups.push(["Otros", "Otros documentos", docs.filter((d) => d.bloque === "Otros")]);
  const status = (d) => d.status === "ok" ? (d.questions ? `${d.questions} preg.` : "indexado") : d.status === "ocr" || d.status === "procesando" ? `OCR ${d.progress}%` : d.status === "sin_pdf" ? "sin PDF" : d.status === "error" ? "error" : "en cola";
  $app.innerHTML = topbar("Temario") + `<main>
    <section><div class="seg" id="tm"><button data-v="A2" aria-pressed="${tem === "A2"}">A2 · GSI</button><button data-v="A1" aria-pressed="${tem === "A1"}">A1 · CSSTIC</button></div></section>
    <section><form id="sf" role="search"><input type="search" id="sq" placeholder="Buscar en todo el temario ${tem}" aria-label="Buscar en el temario"></form><div id="sr"></div></section>
    <section>${groups.map(([k, name, list]) => `<details class="bloque"><summary>${tem === "A2" && k !== "Otros" ? "Bloque " : ""}${esc(name)}<span class="tiny" style="margin-left:6px">${list.length}</span></summary>
      <ul class="temas">${list.map((d) => `<li><a href="#/tema/${d.id}"><span class="num">${d.kind === "tema" ? d.num : "·"}</span>
        <span class="tt">${esc(d.title)}${d.accuracy != null ? `<div class="pct ${pctClass(d.accuracy)}"><i style="width:${d.accuracy}%"></i></div>` : ""}</span>
        <span class="st">${status(d)}${d.accuracy != null ? `<br>${d.accuracy}%` : ""}</span></a></li>`).join("")}</ul></details>`).join("")}</section></main>`;
  $app.querySelector("#tm").onclick = (e) => { const b = e.target.closest("button"); if (b) { LS.set("temario", b.dataset.v); render(); } };
  $app.querySelector("#sf").onsubmit = async (e) => {
    e.preventDefault();
    const q = $app.querySelector("#sq").value.trim(); const sr = $app.querySelector("#sr");
    if (!q) { sr.innerHTML = ""; return; }
    sr.innerHTML = loading();
    const r = await api(`/temario/search?temario=${tem}&q=${encodeURIComponent(q)}&limit=25`);
    sr.innerHTML = `<div class="sheet" style="margin-top:10px">${r.hits.length ? r.hits.map((h) => `<div class="hit"><div class="where"><a href="${jumpHref(h.doc_id, h.page, h.snip)}">Tema ${h.num} · pág. ${h.page}</a> — ${esc(h.title.slice(0, 60))}</div><div class="snip">${hl(h.snip)}</div></div>`).join("") : `<p class="muted small">Sin resultados.</p>`}</div>`;
  };
}, "temario");

route(/^\/tema\/([^/]+)(?:\/p\/(\d+))?(?:\/h\/(.+))?$/, async (id, page, hjson) => {
  let hlInfo = null;
  try { hlInfo = hjson ? JSON.parse(hjson) : null; } catch (e) { hlInfo = null; }
  $app.innerHTML = topbar("Tema", { back: true }) + loading();
  const d = await api("/temario/" + id);
  const name = d.kind === "tema" ? (d.temario === "A2" ? `Bloque ${d.bloque} · Tema ${d.num}` : `Tema ${d.num}`) : "Documento";
  let from = page ? Math.max(1, +page - 1) : 1;
  $app.innerHTML = topbar(name, { back: true }) + `<main>
    <section><h2 style="font-size:1.15rem">${esc(d.title)}</h2>
      <p class="small muted">${d.pages ? d.pages + " páginas" : "PDF no disponible"}${d.indexed && d.indexed < d.pages ? ` · ${d.indexed} con texto (OCR en curso)` : ""} · ${d.questions} preguntas asociadas</p>
      <div class="row wrap">
        ${d.questions ? `<button class="btn grow" id="tt">Test de este tema</button>` : ""}
        ${d.pdf_available[0] ? `<a class="btn ghost grow" href="#/pdf/${id}/${page || 1}">Ver PDF</a>` : ""}
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
      pdfjs = await import("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs");
      pdfjs.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";
    }
    const doc = await pdfjs.getDocument({ url, disableAutoFetch: true, rangeChunkSize: 1 << 20 }).promise;
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
      <div class="row">${num("daily_gen_hour", "Hora de generación", 0, 23)}${num("review_reminder_hour", "Aviso de repaso", 0, 23)}${num("goal_reminder_hour", "Aviso de mínimo", 0, 23)}</div>
    </section>
    <section class="sheet"><h2>Inteligencia artificial (Gemini)</h2>
      <p class="small muted">Consigue una API key gratuita en aistudio.google.com → Get API key.</p>
      <label class="field"><span>API key ${s.gemini_api_key_set ? `(guardada, acaba en ${esc(s.gemini_api_key_hint)})` : "(sin configurar)"}</span><input type="password" id="key" placeholder="${s.gemini_api_key_set ? "Déjala vacía para mantenerla" : "AIza…"}" autocomplete="off"></label>
      <label class="field"><span>Modelo</span><input type="text" data-k="gemini_model" value="${esc(s.gemini_model)}"></label>
      <label class="field"><span>Modelos de reserva (separados por comas)</span><input type="text" data-k="gemini_fallback_models" value="${esc((s.gemini_fallback_models || []).join(", "))}"></label>
      <div class="row"><button class="btn quiet grow" id="tai">Probar la IA</button></div><p class="small" id="taist"></p>
    </section>
    <section class="sheet"><h2>Avisos y aplicación</h2>
      <div class="row wrap"><button class="btn quiet grow" id="tn">Probar notificación</button>${isAndroid ? `<button class="btn quiet grow" id="srv">Cambiar servidor</button>` : ""}</div>
      <label class="field"><span>Tema de color</span><select id="theme">${[["auto", "Como el sistema"], ["light", "Claro"], ["dark", "Oscuro"]].map(([v, t]) => `<option value="${v}" ${theme === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <p class="tiny">Servidor: ${esc(location.host)} · temario en ${esc(s.temario_dir)}</p>
    </section>
    <button class="btn block" id="save">Guardar cambios</button><p></p></main>`;
  $app.querySelector("#save").onclick = async () => {
    const body = {};
    $app.querySelectorAll("[data-k]").forEach((el) => (body[el.dataset.k] = el.value));
    const key = $app.querySelector("#key").value.trim(); if (key) body.gemini_api_key = key;
    try { await api("/settings", { body }); toast("Cambios guardados"); render(); } catch (e) { toast(e.message); }
  };
  $app.querySelector("#tai").onclick = async () => {
    const st = $app.querySelector("#taist"); st.innerHTML = `<span class="spinner"></span>`;
    const key = $app.querySelector("#key").value.trim();
    try { if (key) await api("/settings", { body: { gemini_api_key: key } }); const r = await api("/settings/test_ai", { body: {} }); st.textContent = `Funciona (${r.model}).`; }
    catch (e) { st.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  $app.querySelector("#tn").onclick = async () => { await api("/notifications/test", { body: {} }); if (isAndroid) window.Android.checkNow(); toast(isAndroid ? "Enviada: debería llegar en unos segundos" : "Creada (las notificaciones llegan en la app del móvil)"); };
  const srv = $app.querySelector("#srv"); srv && (srv.onclick = () => window.Android.openSettings());
  $app.querySelector("#theme").onchange = (e) => { LS.set("theme", e.target.value); applyTheme(); };
});

function applyTheme() {
  const t = LS.get("theme", "auto");
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = t;
}
applyTheme();
render();
