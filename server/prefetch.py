"""Preparación en segundo plano de las fuentes «IA» e «Internet».

Va dejando guardadas las respuestas de las preguntas que es más probable que te salgan,
para que al pulsar el botón salgan al instante. Trabaja despacio y con tope diario:

  Prioridad (de más a menos):
    1. Preguntas sin responder del test que tienes abierto.
    2. Falladas que tocan repasar hoy o mañana.
    3. Resto de falladas en seguimiento (las más falladas primero).
    4. Preguntas nuevas generadas sin hacer (solo Internet: ya traen explicación).

  Topes (Ajustes): explicaciones de IA al día y búsquedas de Internet al día.
  La IA solo se usa si hay cuota (no se toca si Google ha devuelto límites hace poco).
"""
import datetime as dt
import json
import threading
import time
import traceback

import db
import gemini
import sources
import fichas

IA_GAP = 150          # segundos mínimos entre explicaciones preparadas (unas pocas, repartidas)
IA_GAP_OPEN_TEST = 30  # más rápido si son del test que estás haciendo
NET_GAP = 12          # segundos entre búsquedas en Internet
NET_BACKOFF = 1800    # si el buscador falla, se espera media hora

_state = {"last_ia": 0.0, "last_net": 0.0, "net_backoff_until": 0.0, "running": False}


def net_prefetch_possible(cfg=None):
    """La precarga de Internet solo usa Tavily (con su cupo); sin clave no se precarga para no provocar bloqueos."""
    cfg = cfg or db.load_config()
    if not cfg.get("tavily_api_key") or sources._paused("tavily"):
        return False
    return sources.tavily_used() < int(cfg.get("tavily_monthly", 1000)) - int(cfg.get("tavily_reserve", 300))


def _today():
    return dt.date.today().isoformat()


def done_today(kind):
    return int(db.kv_get(f"pf_{kind}_{_today()}", 0) or 0)


def _inc(kind):
    db.kv_set(f"pf_{kind}_{_today()}", done_today(kind) + 1)


def _candidates(source, limit=30):
    """Preguntas sin esa fuente preparada, en orden de prioridad. Devuelve [(qid, from_open_test)]."""
    have = "NOT EXISTS (SELECT 1 FROM sources_cache s WHERE s.question_id=q.id AND s.source=?)"
    skip_ia = "AND q.origin<>'ia'" if source == "ia" else ""     # las generadas ya traen su explicación
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    out, seen = [], set()

    def add(rows, flag):
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append((r["id"], flag))

    add(db.q(f"""SELECT q.id FROM test_items ti JOIN tests t ON t.id=ti.test_id JOIN questions q ON q.id=ti.question_id
                 WHERE t.finished_at IS NULL AND ti.chosen IS NULL AND t.created_at>=datetime('now','localtime','-2 days')
                 AND {have} {skip_ia} ORDER BY t.id DESC, ti.pos LIMIT ?""", (source, limit)), True)
    if len(out) < limit:
        add(db.q(f"""SELECT q.id FROM review r JOIN questions q ON q.id=r.question_id
                     WHERE r.mastered=0 AND r.due<=? AND q.disabled=0 AND {have} {skip_ia}
                     ORDER BY r.due, r.fails DESC LIMIT ?""", (tomorrow, source, limit)), False)
    if len(out) < limit:
        add(db.q(f"""SELECT q.id FROM review r JOIN questions q ON q.id=r.question_id
                     WHERE r.mastered=0 AND q.disabled=0 AND {have} {skip_ia}
                     ORDER BY r.fails DESC, r.due LIMIT ?""", (source, limit)), False)
    if source == "internet" and len(out) < limit:
        add(db.q(f"""SELECT q.id FROM questions q WHERE q.is_new=1 AND q.disabled=0 AND {have}
                     ORDER BY q.id LIMIT ?""", (source, limit)), False)
    return out[:limit]


def _busy(qid, source):
    if source != "ia":
        return False
    with sources._inflight_lock:
        return qid in sources._inflight


def _do(qid, source):
    """Prepara una fuente. Devuelve True si quedó guardada."""
    if source == "ia":
        with sources._inflight_lock:
            if qid in sources._inflight:
                return False
            ev = sources._inflight[qid] = threading.Event()
        try:
            sources.get_source(qid, "ia", None, _from_prefetch=True)
        finally:
            with sources._inflight_lock:
                sources._inflight.pop(qid, None)
            ev.set()
    else:
        sources.get_source(qid, "internet", _from_prefetch=True)
    return bool(db.scalar("SELECT 1 FROM sources_cache WHERE question_id=? AND source=?", (qid, source)))


def tick():
    cfg = db.load_config()
    now = time.time()

    # ---- Internet: barato, sin cuota de IA; con tope para no molestar al buscador
    net_cap = int(cfg.get("net_prefetch_daily", 80))
    if net_cap > 0 and done_today("net") < net_cap and now >= _state["net_backoff_until"] and now - _state["last_net"] >= NET_GAP \
            and net_prefetch_possible(cfg):
        cands = _candidates("internet", 1)
        if cands:
            qid, _ = cands[0]
            _state["last_net"] = now
            _inc("net")
            try:
                if not _do(qid, "internet"):
                    # sin resultados: se marca para no repetirla en bucle
                    db.run("INSERT OR IGNORE INTO sources_cache(question_id,source,content) VALUES(?,?,?)",
                           (qid, "internet", '{"results": [], "errors": ["sin resultados al preparar"], "query": "", "search_url": ""}'))
            except Exception:
                _state["net_backoff_until"] = now + NET_BACKOFF

    # ---- Fichas de las falladas: una petición (10 fichas) cada 20 min como mucho, con tope diario
    f_cap = int(cfg.get("fichas_daily_requests", 6))
    if cfg.get("gemini_api_key") and f_cap > 0 and fichas.requests_today() < f_cap and now - _state.get("last_fichas", 0) >= 1200 \
            and gemini.quota_ok_for_background() and fichas.pending(1):
        _state["last_fichas"] = now
        try:
            fichas.generate_batch(background=True)
        except gemini.QuotaError:
            _state["last_fichas"] = now + 3600
        except Exception:
            traceback.print_exc()
        return

    # ---- IA: unas pocas al día, repartidas, solo con cuota
    ia_cap = int(cfg.get("ai_prefetch_daily", 15))
    if not cfg.get("gemini_api_key") or ia_cap <= 0 or not gemini.quota_ok_for_background():
        return
    cands = _candidates("ia", 1)
    if not cands:
        return
    qid, open_test = cands[0]
    gap = IA_GAP_OPEN_TEST if open_test else IA_GAP
    if now - _state["last_ia"] < gap or _busy(qid, "ia"):
        return
    _state["last_ia"] = now
    try:
        _do(qid, "ia")
    except gemini.QuotaError:
        _state["last_ia"] = now + 1800          # sin cuota: se deja media hora
    except Exception:
        traceback.print_exc()


def _loop():
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        try:
            night_tick()
        except Exception:
            traceback.print_exc()
        time.sleep(8)


def start():
    if _state["running"]:
        return
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True, name="prefetch").start()


def status():
    cfg = db.load_config()
    return {
        "ia_today": gemini.usage_today().get("_precarga", 0), "ia_cap": int(cfg.get("ai_prefetch_daily", 15)),
        "net_today": done_today("net"), "net_cap": int(cfg.get("net_prefetch_daily", 80)),
        "ia_ready": db.scalar("SELECT COUNT(*) FROM sources_cache WHERE source='ia'") or 0,
        "net_ready": db.scalar("SELECT COUNT(*) FROM sources_cache WHERE source='internet'") or 0,
        "ia_pending": len(_candidates("ia", 200)), "net_pending": len(_candidates("internet", 200)),
    }


# ==================================================================== lote nocturno
"""De madrugada (antes de que se renueve la cuota diaria de Gemini, a las 9:00 en España) aprovecha la cuota
sobrante: explica 10 preguntas por petición con un modelo «lite» y va recorriendo todo el banco.
También hace búsquedas de Internet extra. Orden: falladas → tu escala (A2 por defecto) → de examen → resto."""

BATCH_SIZE = 10
BATCH_GAP = 15          # segundos entre peticiones del lote
NET_NIGHT_GAP = 20

BATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {"explicaciones": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "n": {"type": "INTEGER"},
        "respuesta_ia": {"type": "STRING", "enum": ["a", "b", "c", "d"]},
        "coincide": {"type": "BOOLEAN"},
        "explicacion": {"type": "STRING"},
        "por_que_no": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "letra": {"type": "STRING"}, "motivo": {"type": "STRING"}}, "required": ["letra", "motivo"]}},
        "referencia": {"type": "STRING"},
        "truco": {"type": "STRING"},
    }, "required": ["n", "respuesta_ia", "coincide", "explicacion"]}}},
    "required": ["explicaciones"],
}

_night = {"last": 0.0, "last_net": 0.0, "stop_until": 0.0}


def _in_window(now, cfg):
    a, b = int(cfg.get("batch_start_hour", 1)), int(cfg.get("batch_end_hour", 8))
    h = now.hour
    return (a <= h < b) if a < b else (h >= a or h < b)


def batch_model(cfg):
    m = (cfg.get("batch_model") or "").strip()
    if m:
        return m
    pool = [cfg.get("gemini_model")] + list(cfg.get("gemini_fallback_models") or [])
    lite = [x for x in pool if x and "lite" in x]
    return lite[0] if lite else (pool[0] or "gemini-3.5-flash-lite")


def _bank_order(source, limit):
    """Todo el banco sin esa fuente, en orden de utilidad."""
    cfg = db.load_config()
    esc = cfg.get("default_escala", "A2")
    col = "a1_doc" if esc == "A1" else "a2_doc"
    have = "NOT EXISTS (SELECT 1 FROM sources_cache s WHERE s.question_id=q.id AND s.source=?)"
    skip_ia = "AND q.origin<>'ia'" if source == "ia" else ""
    return [r["id"] for r in db.q(f"""SELECT q.id FROM questions q LEFT JOIN review r ON r.question_id=q.id AND r.mastered=0
        WHERE q.disabled=0 AND {have} {skip_ia}
        ORDER BY (r.question_id IS NOT NULL) DESC, (q.{col} IS NOT NULL OR q.escala=?) DESC, q.is_exam DESC, q.id
        LIMIT ?""", (source, esc, limit))]


def _batch_prompt(rows):
    blocks = []
    for i, q in enumerate(rows):
        corr = sources.effective_correct(q)
        hit = ""
        try:
            h = sources.temario_for_question(q, limit=1)["hits"]
            if h:
                hit = "\n   Temario: " + h[0]["snip"].replace("[[", "").replace("]]", "").replace("{{", "").replace("}}", "")[:450]
        except Exception:
            pass
        opts = "\n".join(f"   {k}) {q[k]}" for k in "abcd" if q.get(k))
        blocks.append(f"[{i}] {q['text']}\n{opts}\n   Correcta según el banco: {corr}\n   Fuente: {q.get('comments') or '-'}{hit}")
    return f"""Eres preparador de oposiciones TIC de la Administración española (A1 CSSTIC, A2 GSI, C1 TAI).
Para CADA pregunta de la lista devuelve un objeto con su número "n" y:
- "respuesta_ia": la opción que consideras correcta; "coincide": si coincide con la del banco.
- "explicacion": máx. 70 palabras, con la norma, artículo o concepto exacto.
- "por_que_no": una frase por cada opción incorrecta. "referencia": norma o fuente. "truco": regla mnemotécnica corta si existe.
Si el banco parece equivocado o la norma ha cambiado, dilo en la explicación.

{chr(10).join(blocks)}"""


def run_batch_request():
    """Una petición del lote: explica hasta 10 preguntas. Devuelve cuántas guardó."""
    cfg = db.load_config()
    ids = _bank_order("ia", BATCH_SIZE)
    if not ids:
        return 0
    rows = [db.q1("SELECT * FROM questions WHERE id=?", (i,)) for i in ids]
    res = gemini.generate(_batch_prompt(rows), schema=BATCH_SCHEMA, temperature=0.2, thinking="minimal",
                          max_tokens=9000, budget=150, call_timeout=120, kind="lote", background=True,
                          models=[batch_model(cfg)])
    saved = 0
    c = db.conn()
    for e in res.get("explicaciones") or []:
        n = e.get("n")
        if not isinstance(n, int) or not (0 <= n < len(rows)) or not e.get("explicacion"):
            continue
        q = rows[n]
        e.pop("n", None)
        e["respuesta_banco"] = sources.effective_correct(q)
        e["lote"] = True
        c.execute("INSERT OR IGNORE INTO sources_cache(question_id,source,content) VALUES(?,?,?)",
                  (q["id"], "ia", json.dumps(e, ensure_ascii=False)))
        saved += 1
    c.commit()
    return saved


def night_tick(now=None):
    now = now or dt.datetime.now()
    cfg = db.load_config()
    if not cfg.get("batch_enabled", True) or not _in_window(now, cfg):
        return
    t = time.time()
    day = now.date().isoformat()

    # Internet extra por la noche
    net_cap = int(cfg.get("batch_net_nightly", 150))
    if net_cap and int(db.kv_get(f"night_net_{day}", 0) or 0) < net_cap and t - _night["last_net"] >= NET_NIGHT_GAP \
            and t >= _state["net_backoff_until"] and net_prefetch_possible(cfg):
        ids = _bank_order("internet", 1)
        if ids:
            _night["last_net"] = t
            db.kv_set(f"night_net_{day}", int(db.kv_get(f"night_net_{day}", 0) or 0) + 1)
            try:
                if not _do(ids[0], "internet"):
                    db.run("INSERT OR IGNORE INTO sources_cache(question_id,source,content) VALUES(?,?,?)",
                           (ids[0], "internet", '{"results": [], "errors": ["sin resultados al preparar"], "query": "", "search_url": ""}'))
            except Exception:
                _state["net_backoff_until"] = t + NET_BACKOFF

    # IA por lotes
    if not cfg.get("gemini_api_key") or t < _night["stop_until"] or t - _night["last"] < BATCH_GAP:
        return
    if batch_model(cfg) in gemini.blocked_models():
        return
    reqs = int(db.kv_get(f"night_req_{day}", 0) or 0)
    if reqs >= int(cfg.get("batch_max_requests", 100)):
        return
    _night["last"] = t
    db.kv_set(f"night_req_{day}", reqs + 1)
    try:
        if fichas.pending(1) and reqs % 3 == 0:        # de noche, una de cada tres peticiones es para fichas
            fichas.generate_batch(background=True)
            return
        n = run_batch_request()
        db.kv_set(f"night_ia_{day}", int(db.kv_get(f"night_ia_{day}", 0) or 0) + n)
    except gemini.QuotaError:
        _night["stop_until"] = t + 3 * 3600      # sin cuota: se acabó por esta noche
    except Exception:
        traceback.print_exc()
        _night["stop_until"] = t + 600


def night_status():
    cfg = db.load_config()
    total_ia = db.scalar("SELECT COUNT(*) FROM questions WHERE disabled=0 AND origin<>'ia'") or 1
    total_net = db.scalar("SELECT COUNT(*) FROM questions WHERE disabled=0") or 1
    ia_ready = db.scalar("""SELECT COUNT(*) FROM sources_cache s JOIN questions q ON q.id=s.question_id
                            WHERE s.source='ia' AND q.origin<>'ia'""") or 0
    net_ready = db.scalar("SELECT COUNT(*) FROM sources_cache WHERE source='internet' AND content NOT LIKE '%\"results\": []%'") or 0
    last = []
    for i in range(1, 8):
        d = (dt.date.today() - dt.timedelta(days=i - 1)).isoformat()
        v = int(db.kv_get(f"night_ia_{d}", 0) or 0)
        if v:
            last.append(v)
    rate = (sum(last) / len(last)) if last else None
    left = total_ia - ia_ready
    return {"enabled": bool(cfg.get("batch_enabled", True)), "model": batch_model(cfg),
            "hours": f"{int(cfg.get('batch_start_hour', 1)):02d}:00–{int(cfg.get('batch_end_hour', 8)):02d}:00",
            "ia_ready": ia_ready, "ia_total": total_ia, "net_ready": net_ready, "net_total": total_net,
            "last_night_ia": int(db.kv_get(f"night_ia_{dt.date.today().isoformat()}", 0) or 0),
            "avg_per_night": round(rate) if rate else None,
            "days_left": (round(left / rate) if rate else None)}
