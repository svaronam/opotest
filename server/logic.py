"""Lógica de OpoTest: tests, repaso, estadísticas, generación con IA y avisos."""
import datetime as dt
import json
import random
import re
import threading
import traceback

import db
import gemini
import importer

INTERVALS = [1, 3, 7, 15, 30]          # días entre repasos según la caja
LETTERS = "abcd"


def today():
    return dt.date.today().isoformat()


def eff(qrow):
    return qrow.get("correct_override") or qrow["correct"]


# ---------------------------------------------------------------- catálogo

_catalog = None


def catalog():
    global _catalog
    if _catalog is None:
        _catalog = importer.load_catalog()
    return _catalog


def docs_tree():
    cat = catalog()
    counts_a1 = {r["a1_doc"]: r["n"] for r in db.q("SELECT a1_doc, COUNT(*) n FROM questions WHERE disabled=0 GROUP BY a1_doc")}
    counts_a2 = {}
    for col in ("a2_doc", "a2_doc2"):
        for r in db.q(f"SELECT {col} d, COUNT(*) n FROM questions WHERE disabled=0 AND {col} IS NOT NULL GROUP BY {col}"):
            counts_a2[r["d"]] = counts_a2.get(r["d"], 0) + r["n"]
    acc = {}
    for r in db.q("""SELECT q.a1_doc d1, q.a2_doc d2, SUM(a.is_correct) ok, COUNT(*) n FROM attempts a
                      JOIN questions q ON q.id=a.question_id GROUP BY q.a1_doc, q.a2_doc"""):
        for d in (r["d1"], r["d2"]):
            if d:
                x = acc.setdefault(d, [0, 0])
                x[0] += r["ok"] or 0
                x[1] += r["n"]
    out = {"A1": [], "A2": []}
    for d in db.q("SELECT id,temario,bloque,num,title,kind,files,resumen,pages,status,progress FROM docs ORDER BY temario, bloque, num"):
        d["files"] = json.loads(d["files"])
        d["questions"] = (counts_a1 if d["temario"] == "A1" else counts_a2).get(d["id"], 0)
        a = acc.get(d["id"])
        d["answered"] = a[1] if a else 0
        d["accuracy"] = round(100 * a[0] / a[1]) if a and a[1] else None
        out[d["temario"]].append(d)
    return {"docs": out, "bloques_a1": cat["bloques_a1"], "bloques_a2": cat["bloques_a2"]}


# ---------------------------------------------------------------- tests

def _where(filters):
    f = filters or {}
    w, a = ["q.disabled=0"], []
    tem = f.get("temario")
    temas = f.get("temas") or []
    bloques = f.get("bloques") or []
    if tem == "A1":
        if temas:
            w.append("q.a1_doc IN (%s)" % ",".join("?" * len(temas))); a += temas
        elif bloques:
            w.append("q.block IN (%s)" % ",".join("?" * len(bloques))); a += bloques
        else:
            w.append("(q.a1_doc IS NOT NULL OR q.block IS NOT NULL)")
    elif tem == "A2":
        if temas:
            ph = ",".join("?" * len(temas))
            w.append(f"(q.a2_doc IN ({ph}) OR q.a2_doc2 IN ({ph}))"); a += temas + temas
        elif bloques:
            w.append("(" + " OR ".join("q.a2_doc LIKE ? OR q.a2_doc2 LIKE ?" for _ in bloques) + ")")
            for b in bloques:
                a += ["A2-%s-%%" % b] * 2
        else:
            w.append("(q.a2_doc IS NOT NULL OR q.a2_doc2 IS NOT NULL)")
    escalas = f.get("escalas") or []
    if escalas:
        w.append("q.escala IN (%s)" % ",".join("?" * len(escalas))); a += escalas
    origen = f.get("origen") or "todas"
    if origen in ("preparatic", "ia"):
        w.append("q.origin=?"); a.append(origen)
    if f.get("solo_examen"):
        w.append("q.is_exam=1")
    if f.get("solo_nuevas"):
        w.append("q.is_new=1")
    if f.get("no_vistas"):
        w.append("NOT EXISTS (SELECT 1 FROM attempts t WHERE t.question_id=q.id)")
    if f.get("solo_falladas"):
        w.append("q.id IN (SELECT question_id FROM review WHERE mastered=0)")
    if f.get("buscar"):
        w.append("q.text LIKE ?"); a.append("%" + f["buscar"] + "%")
    return " AND ".join(w), a


def count_questions(filters):
    w, a = _where(filters)
    return db.scalar(f"SELECT COUNT(*) FROM questions q WHERE {w}", a)


def create_test(kind="normal", n=20, mode="practica", filters=None, title=None, question_ids=None):
    n = max(1, min(int(n or 20), 200))
    filters = filters or {}
    if question_ids is None:
        if kind == "repaso":
            ids = [r["question_id"] for r in db.q(
                "SELECT question_id FROM review WHERE mastered=0 AND due<=? ORDER BY due, box LIMIT ?", (today(), n))]
            title = title or "Repaso de falladas"
        elif kind == "nuevas":
            ids = [r["id"] for r in db.q("SELECT id FROM questions WHERE is_new=1 AND disabled=0 ORDER BY id LIMIT ?", (n,))]
            title = title or "Preguntas nuevas"
        else:
            w, a = _where(filters)
            order = "random()"
            if filters.get("priorizar_no_vistas"):
                order = "(SELECT COUNT(*) FROM attempts t WHERE t.question_id=q.id), random()"
            ids = [r["id"] for r in db.q(f"SELECT q.id FROM questions q WHERE {w} ORDER BY {order} LIMIT ?", a + [n])]
            if kind == "falladas":
                title = title or "Falladas"
    else:
        ids = list(question_ids)[:n]
    if not ids:
        return None
    random.shuffle(ids) if kind != "repaso" else None
    tid = db.run("INSERT INTO tests(kind,mode,title,filters,n) VALUES(?,?,?,?,?)",
                 (kind, mode, title or describe_filters(filters), json.dumps(filters, ensure_ascii=False), len(ids)))
    c = db.conn()
    c.executemany("INSERT INTO test_items(test_id,pos,question_id) VALUES(?,?,?)", [(tid, i, q) for i, q in enumerate(ids)])
    c.commit()
    return get_test(tid)


def describe_filters(f):
    f = f or {}
    parts = []
    if f.get("temario"):
        parts.append("Temario " + f["temario"])
    if f.get("temas"):
        parts.append(f"{len(f['temas'])} tema(s)" if len(f["temas"]) > 1 else f["temas"][0].replace("A1-", "Tema ").replace("A2-", ""))
    elif f.get("bloques"):
        parts.append("Bloque " + ", ".join(f["bloques"]))
    if f.get("escalas") and f.get("escalas") != [f.get("temario")]:
        parts.append("escala " + "/".join(f["escalas"]))
    if f.get("origen") == "ia":
        parts.append("generadas IA")
    if f.get("solo_examen"):
        parts.append("de examen")
    return ", ".join(parts) or "Aleatorio"


def public_q(qrow, reveal=False):
    d = {k: qrow.get(k) for k in ("id", "text", "a", "b", "c", "d", "origin", "block", "a1_doc", "a2_doc", "escala",
                                   "is_exam", "year", "is_new", "rating")}
    d["comments"] = qrow.get("comments") if reveal else None
    if reveal:
        d["correct"] = eff(qrow)
        d["correct_bank"] = qrow["correct"]
        d["overridden"] = bool(qrow.get("correct_override"))
        d["explanation"] = qrow.get("explanation")
        d["exams"] = qrow.get("exams")
    return d


def get_test(tid):
    t = db.q1("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        return None
    t["filters"] = json.loads(t["filters"] or "{}")
    items = db.q("""SELECT ti.pos, ti.chosen, ti.is_correct, q.* FROM test_items ti JOIN questions q ON q.id=ti.question_id
                    WHERE ti.test_id=? ORDER BY ti.pos""", (tid,))
    finished = bool(t["finished_at"])
    out = []
    for it in items:
        reveal = finished or (t["mode"] == "practica" and it["chosen"] is not None)
        d = public_q(it, reveal)
        d["pos"] = it["pos"]
        d["chosen"] = it["chosen"]
        d["is_correct"] = it["is_correct"] if reveal else None
        d["titles"] = doc_titles(it)
        out.append(d)
    t["items"] = out
    return t


_titles = None


def doc_titles(qrow):
    global _titles
    if _titles is None:
        _titles = {d["id"]: d["title"] for d in db.q("SELECT id,title FROM docs")}
    return {k: _titles.get(qrow.get(k)) for k in ("a1_doc", "a2_doc") if qrow.get(k)}


def _record(qid, tid, chosen, ok, ms=None):
    db.run("INSERT INTO attempts(question_id,test_id,chosen,is_correct,ms) VALUES(?,?,?,?,?)", (qid, tid, chosen, ok, ms))
    db.run("UPDATE questions SET is_new=0 WHERE id=? AND is_new=1", (qid,))
    r = db.q1("SELECT * FROM review WHERE question_id=?", (qid,))
    if not ok:
        due = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        if r:
            db.run("UPDATE review SET box=0, due=?, fails=fails+1, last_fail=?, mastered=0 WHERE question_id=?", (due, today(), qid))
        else:
            db.run("INSERT INTO review(question_id,box,due,fails,last_fail) VALUES(?,?,?,?,?)", (qid, 0, due, 1, today()))
    elif r and not r["mastered"] and r["due"] <= today():
        box = r["box"] + 1
        if box >= len(INTERVALS):
            db.run("UPDATE review SET box=?, mastered=1 WHERE question_id=?", (box, qid))
        else:
            due = (dt.date.today() + dt.timedelta(days=INTERVALS[box])).isoformat()
            db.run("UPDATE review SET box=?, due=? WHERE question_id=?", (box, due, qid))


def answer(tid, pos, chosen, ms=None):
    t = db.q1("SELECT * FROM tests WHERE id=?", (tid,))
    it = db.q1("SELECT ti.*, q.correct, q.correct_override FROM test_items ti JOIN questions q ON q.id=ti.question_id WHERE test_id=? AND pos=?", (tid, pos))
    if not t or not it:
        raise KeyError("no existe")
    if t["finished_at"]:
        raise ValueError("El test ya está corregido")
    chosen = (chosen or "").lower() or None
    ok = None if chosen is None else int(chosen == eff(it))
    if t["mode"] == "practica":
        if it["chosen"] is not None:            # ya respondida: no se cambia en modo práctica
            return item_result(tid, pos)
        db.run("UPDATE test_items SET chosen=?, is_correct=?, answered_at=datetime('now','localtime'), ms=? WHERE test_id=? AND pos=?",
               (chosen, ok, ms, tid, pos))
        if chosen is not None:
            _record(it["question_id"], tid, chosen, ok, ms)
        _update_score(tid)
        return item_result(tid, pos)
    db.run("UPDATE test_items SET chosen=?, ms=? WHERE test_id=? AND pos=?", (chosen, ms, tid, pos))
    return {"saved": True}


def item_result(tid, pos):
    it = db.q1("SELECT ti.pos, ti.chosen, ti.is_correct, q.* FROM test_items ti JOIN questions q ON q.id=ti.question_id WHERE test_id=? AND pos=?", (tid, pos))
    d = public_q(it, True)
    d.update(pos=it["pos"], chosen=it["chosen"], is_correct=it["is_correct"], titles=doc_titles(it))
    return d


def _update_score(tid):
    r = db.q1("SELECT SUM(is_correct=1) ok, SUM(is_correct=0) ko, SUM(chosen IS NULL) blank FROM test_items WHERE test_id=?", (tid,))
    ok, ko, blank = r["ok"] or 0, r["ko"] or 0, r["blank"] or 0
    db.run("UPDATE tests SET ok=?, ko=?, blank=?, score=? WHERE id=?", (ok, ko, blank, round(ok - ko / 3, 2), tid))


def finish(tid):
    t = db.q1("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        raise KeyError("no existe")
    if not t["finished_at"]:
        if t["mode"] == "examen":
            for it in db.q("SELECT ti.*, q.correct, q.correct_override FROM test_items ti JOIN questions q ON q.id=ti.question_id WHERE test_id=?", (tid,)):
                if it["chosen"] is None:
                    continue
                ok = int(it["chosen"] == eff(it))
                db.run("UPDATE test_items SET is_correct=? WHERE test_id=? AND pos=?", (ok, tid, it["pos"]))
                _record(it["question_id"], tid, it["chosen"], ok, it["ms"])
        _update_score(tid)
        db.run("UPDATE tests SET finished_at=datetime('now','localtime') WHERE id=?", (tid,))
    return get_test(tid)


def set_correct(qid, letter):
    letter = (letter or "").lower()
    q = db.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not q or letter not in LETTERS or not q.get(letter):
        raise ValueError("Letra no válida")
    db.run("UPDATE questions SET correct_override=? WHERE id=?", (None if letter == q["correct"] else letter, qid))
    # recalcula los intentos de esa pregunta en tests abiertos/cerrados para que el historial cuadre
    db.run("UPDATE test_items SET is_correct=(chosen=?) WHERE question_id=? AND is_correct IS NOT NULL", (letter, qid))
    db.run("UPDATE attempts SET is_correct=(chosen=?) WHERE question_id=?", (letter, qid))
    for r in db.q("SELECT DISTINCT test_id FROM test_items WHERE question_id=?", (qid,)):
        _update_score(r["test_id"])
    db.run("DELETE FROM sources_cache WHERE question_id=? AND source='ia'", (qid,))
    return public_q(db.q1("SELECT * FROM questions WHERE id=?", (qid,)), True)


def rate_question(qid, rating):
    if rating not in ("facil", "bien", None, ""):
        raise ValueError("Valoración no válida")
    db.run("UPDATE questions SET rating=?, rated_at=date('now','localtime') WHERE id=?", (rating or None, qid))
    return {"ok": True, "level": _adapt_level()}


def disable_question(qid, disabled=True):
    db.run("UPDATE questions SET disabled=? WHERE id=?", (1 if disabled else 0, qid))


def history(limit=50, offset=0):
    return db.q("SELECT id,created_at,finished_at,kind,mode,title,n,ok,ko,blank,score FROM tests ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset))


def failed_list(limit=100, offset=0, filters=None):
    w, a = _where(filters or {})
    return db.q(f"""SELECT q.id, q.text, r.fails, r.box, r.due, r.last_fail, q.a1_doc, q.a2_doc, q.escala
                    FROM review r JOIN questions q ON q.id=r.question_id WHERE r.mastered=0 AND {w}
                    ORDER BY r.due, r.fails DESC LIMIT ? OFFSET ?""", a + [limit, offset])


# ---------------------------------------------------------------- inicio / estadísticas

def streak(goal):
    days = {r["day"]: r["n"] for r in db.q("SELECT day, COUNT(*) n FROM attempts GROUP BY day")}
    s, d = 0, dt.date.today()
    if days.get(d.isoformat(), 0) < goal:
        d -= dt.timedelta(days=1)
    while days.get(d.isoformat(), 0) >= goal:
        s += 1
        d -= dt.timedelta(days=1)
    return s


def home():
    cfg = db.load_config()
    goal = int(cfg.get("daily_goal", 50))
    t = today()
    r = db.q1("SELECT COUNT(*) n, SUM(is_correct) ok FROM attempts WHERE day=?", (t,))
    docs = db.q1("""SELECT SUM(status='ok') ok, COUNT(*) n, SUM(status IN ('ocr','procesando')) work,
                    SUM(status='sin_pdf') nopdf FROM docs WHERE kind IN ('tema','extra')""")
    job = db.q1("SELECT * FROM gen_jobs ORDER BY id DESC LIMIT 1")
    return {
        "today": t,
        "answered": r["n"] or 0, "correct": r["ok"] or 0, "goal": goal,
        "today_seq": "".join(str(x["is_correct"]) for x in db.q("SELECT is_correct FROM attempts WHERE day=? ORDER BY id LIMIT 200", (t,))),
        "review_due": db.scalar("SELECT COUNT(*) FROM review WHERE mastered=0 AND due<=?", (t,)),
        "review_total": db.scalar("SELECT COUNT(*) FROM review WHERE mastered=0"),
        "new_questions": db.scalar("SELECT COUNT(*) FROM questions WHERE is_new=1 AND disabled=0"),
        "streak": streak(goal),
        "total_questions": db.scalar("SELECT COUNT(*) FROM questions WHERE disabled=0"),
        "ia_questions": db.scalar("SELECT COUNT(*) FROM questions WHERE origin='ia' AND disabled=0"),
        "open_test": db.q1("SELECT id,title,n FROM tests WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1"),
        "temario": docs, "last_job": job,
        "ai_ready": bool(cfg.get("gemini_api_key")),
    }


def _series(group_expr, label_expr, since):
    return db.q(f"""SELECT {label_expr} AS label, COUNT(*) n, SUM(is_correct) ok, SUM(1-is_correct) ko
                    FROM attempts WHERE day>=? GROUP BY {group_expr} ORDER BY label""", (since,))


def stats():
    d = dt.date.today()
    daily = {r["label"]: r for r in _series("day", "day", (d - dt.timedelta(days=29)).isoformat())}
    daily_list = []
    for i in range(29, -1, -1):
        k = (d - dt.timedelta(days=i)).isoformat()
        r = daily.get(k, {"label": k, "n": 0, "ok": 0, "ko": 0})
        daily_list.append(r)
    weekly = _series("strftime('%Y-%W', day)", "strftime('%Y-%W', day)", (d - dt.timedelta(weeks=12)).isoformat())
    monthly = _series("strftime('%Y-%m', day)", "strftime('%Y-%m', day)", (d.replace(day=1) - dt.timedelta(days=365)).isoformat())
    tot = db.q1("SELECT COUNT(*) n, SUM(is_correct) ok, COUNT(DISTINCT day) days, COUNT(DISTINCT question_id) uq FROM attempts")

    def by(col, temario):
        rows = db.q(f"""SELECT q.{col} AS k, COUNT(*) n, SUM(a.is_correct) ok FROM attempts a JOIN questions q ON q.id=a.question_id
                        WHERE q.{col} IS NOT NULL GROUP BY q.{col} HAVING n>=3""")
        titles = {x["id"]: x for x in db.q("SELECT id,title,num,bloque FROM docs WHERE temario=?", (temario,))}
        out = []
        for r in rows:
            t = titles.get(r["k"], {})
            out.append({"id": r["k"], "title": t.get("title", r["k"]), "num": t.get("num"), "bloque": t.get("bloque"),
                        "n": r["n"], "ok": r["ok"] or 0, "pct": round(100 * (r["ok"] or 0) / r["n"])})
        return out

    temas_a1, temas_a2 = by("a1_doc", "A1"), by("a2_doc", "A2")
    bloques = db.q("""SELECT q.block AS k, COUNT(*) n, SUM(a.is_correct) ok FROM attempts a JOIN questions q ON q.id=a.question_id
                      WHERE q.block IS NOT NULL GROUP BY q.block ORDER BY q.block""")
    bloques_a2 = db.q("""SELECT substr(q.a2_doc,4,instr(substr(q.a2_doc,4),'-')-1) AS k, COUNT(*) n, SUM(a.is_correct) ok
                         FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.a2_doc IS NOT NULL GROUP BY k ORDER BY k""")
    escalas = db.q("""SELECT q.escala AS k, COUNT(*) n, SUM(a.is_correct) ok FROM attempts a JOIN questions q ON q.id=a.question_id GROUP BY k""")
    origen = db.q("""SELECT q.origin AS k, COUNT(*) n, SUM(a.is_correct) ok FROM attempts a JOIN questions q ON q.id=a.question_id GROUP BY k""")
    worst_q = db.q("""SELECT q.id, q.text, COUNT(*) n, SUM(1-a.is_correct) ko FROM attempts a JOIN questions q ON q.id=a.question_id
                      GROUP BY q.id HAVING ko>=2 ORDER BY ko DESC, n DESC LIMIT 15""")
    hours = db.q("""SELECT CAST(strftime('%H', answered_at) AS INT) h, COUNT(*) n, SUM(is_correct) ok FROM attempts
                    WHERE day>=? GROUP BY h ORDER BY h""", ((d - dt.timedelta(days=60)).isoformat(),))
    tests = db.q1("SELECT COUNT(*) n, AVG(score*10.0/n) avg10 FROM tests WHERE finished_at IS NOT NULL AND n>=10")
    cfg = db.load_config()
    goal = int(cfg.get("daily_goal", 50))
    week_days = [x for x in daily_list[-7:]]
    return {
        "daily": daily_list, "weekly": weekly, "monthly": monthly,
        "totals": {"answered": tot["n"] or 0, "correct": tot["ok"] or 0, "days": tot["days"] or 0, "unique": tot["uq"] or 0,
                   "tests": tests["n"] or 0, "avg_score10": round(tests["avg10"], 2) if tests["avg10"] is not None else None,
                   "streak": streak(goal), "goal": goal,
                   "week_answered": sum(x["n"] for x in week_days),
                   "week_goal_days": sum(1 for x in week_days if x["n"] >= goal)},
        "temas_a1": temas_a1, "temas_a2": temas_a2,
        "bloques": bloques, "bloques_a2": bloques_a2, "escalas": escalas, "origen": origen,
        "worst_questions": worst_q, "hours": hours,
    }


# ---------------------------------------------------------------- notificaciones

def notify(kind, title, body, link=None):
    return db.run("INSERT INTO notifications(kind,title,body,link) VALUES(?,?,?,?)", (kind, title, body, link))


def notifications_since(since_id):
    return db.q("SELECT * FROM notifications WHERE id>? ORDER BY id LIMIT 20", (since_id,))


# ---------------------------------------------------------------- generación con IA

GEN_SCHEMA = {
    "type": "OBJECT",
    "properties": {"preguntas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "enunciado": {"type": "STRING"},
        "a": {"type": "STRING"}, "b": {"type": "STRING"}, "c": {"type": "STRING"}, "d": {"type": "STRING"},
        "correcta": {"type": "STRING", "enum": ["a", "b", "c", "d"]},
        "explicacion": {"type": "STRING"},
        "fuente": {"type": "STRING"},
    }, "required": ["enunciado", "a", "b", "c", "d", "correcta", "explicacion"]}}},
    "required": ["preguntas"],
}

ESCALA_TXT = {
    "A1": "Cuerpo Superior de Sistemas y Tecnologías de la Información del Estado (A1)",
    "A2": "Cuerpo de Gestión de Sistemas e Informática de la Administración del Estado (A2, GSI)",
    "C1": "Cuerpo de Técnicos Auxiliares de Informática de la Administración del Estado (C1, TAI)",
}

# Técnicas que hacen difíciles las preguntas de los exámenes reales de la AGE
TECNICAS = """- Detalle literal de la norma: artículo, plazo, mayoría, órgano competente, número exacto (p. ej. "en el plazo de…", "por mayoría de…").
- Distractores "casi correctos": la misma frase cambiando un solo dato (un plazo, un órgano, una capa OSI, un puerto, una versión, un nivel RAID).
- Formulación negativa: "Señale la INCORRECTA", "¿Cuál NO es…?".
- Comparar conceptos que se confunden entre sí (p. ej. ITIL vs COBIT, RAID 5 vs 6, OLAP vs OLTP, TCP vs SCTP, recurso de alzada vs reposición).
- Valores técnicos concretos: puertos, longitudes de clave, cabeceras, formas normales, códigos de estado, comandos y opciones.
- Combinaciones: "¿Cuáles de las siguientes son correctas? I… II… III…" con opciones "Solo I y II", etc.
- Casos aplicados breves en los que hay que razonar qué técnica, norma o comando corresponde."""

NIVELES = {
    1: "Dificultad: como la media del examen real.",
    2: "Dificultad: ALTA. Al menos 3 de cada 5 preguntas deben usar distractores casi correctos o datos literales.",
    3: "Dificultad: MUY ALTA, como las preguntas más difíciles del examen real. Todas con distractores que solo distingue "
       "quien domina el tema; evita cualquier pregunta que se pueda acertar por sentido común o descarte.",
}

REVIEW_SCHEMA = {
    "type": "OBJECT",
    "properties": {"revision": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "n": {"type": "INTEGER"},
        "respuesta": {"type": "STRING", "enum": ["a", "b", "c", "d"]},
        "unica_correcta": {"type": "BOOLEAN"},
        "dificultad": {"type": "INTEGER"},
        "motivo": {"type": "STRING"},
    }, "required": ["n", "respuesta", "unica_correcta", "dificultad"]}}},
    "required": ["revision"],
}


def gen_level():
    """Nivel 1-3. Sube si aciertas las de la IA bastante más que las del banco o las marcas como fáciles."""
    try:
        return max(1, min(3, int(db.kv_get("gen_level", 2))))
    except Exception:
        return 2


def _adapt_level():
    if db.kv_get("gen_level_auto", "1") != "1":
        return gen_level()
    rows ={r["origin"]: r for r in db.q("""SELECT q.origin, COUNT(*) n, AVG(a.is_correct) acc FROM attempts a
            JOIN questions q ON q.id=a.question_id WHERE a.day>=date('now','-30 days') GROUP BY q.origin""")}
    easy = db.scalar("SELECT COUNT(*) FROM questions WHERE origin='ia' AND rating='facil' AND rated_at>=date('now','-14 days')") or 0
    hard = db.scalar("SELECT COUNT(*) FROM questions WHERE origin='ia' AND rating='bien' AND rated_at>=date('now','-14 days')") or 0
    lvl = gen_level()
    ia, bank = rows.get("ia"), rows.get("preparatic")
    if ia and bank and ia["n"] >= 40 and bank["n"] >= 40:
        if ia["acc"] > bank["acc"] + 0.08:
            lvl += 1
        elif ia["acc"] < bank["acc"] - 0.08:
            lvl -= 1
    if easy >= 5 and easy > 2 * hard:
        lvl += 1
    lvl = max(1, min(3, lvl))
    db.kv_set("gen_level", lvl)
    return lvl

_gen_lock = threading.Lock()


def _weakness_weights(docs):
    acc = {}
    for col in ("a1_doc", "a2_doc"):
        for r in db.q(f"""SELECT q.{col} d, COUNT(*) n, SUM(a.is_correct) ok FROM attempts a JOIN questions q ON q.id=a.question_id
                          WHERE q.{col} IS NOT NULL AND a.day>=date('now','-60 days') GROUP BY q.{col}"""):
            acc[r["d"]] = (r["n"], r["ok"] or 0)
    w = []
    for d in docs:
        n, ok = acc.get(d["id"], (0, 0))
        fail = 1 - ok / n if n else 0.5           # sin practicar = peso medio
        w.append(0.25 + fail * 2)                  # los temas que más fallas salen más
    return w


def _doc_context(doc_id, max_chars=7000):
    pages = db.q("SELECT page, text FROM pages WHERE doc_id=? AND length(text)>200 ORDER BY page", (doc_id,))
    if not pages:
        return "", None
    start = random.randrange(len(pages))
    buf, used = [], []
    for p in pages[start:] + pages[:start]:
        if sum(len(x) for x in buf) > max_chars:
            break
        buf.append(p["text"][:3500])
        used.append(p["page"])
    return "\n---\n".join(buf), used


def _related(doc):
    cat = catalog()
    if doc["temario"] == "A1":
        p = doc["num"] if doc["num"] <= 84 else doc["num"] + 1
        return {"a1_doc": doc["id"], "a2_doc": cat["p2a2"].get(str(p)), "block": doc["bloque"]}
    a1 = next((("A1-%03d" % v) for k, v in cat["p2a1"].items() if v and cat["p2a2"].get(k) == doc["id"]), None)
    block = db.scalar("SELECT bloque FROM docs WHERE id=?", (a1,)) if a1 else None
    return {"a1_doc": a1, "a2_doc": doc["id"], "block": block}


def _pick_docs(filters, n_batches):
    f = filters or {}
    tem = f.get("temario")
    if not tem:
        esc = (f.get("escalas") or [db.load_config().get("default_escala", "A2")])[0]
        tem = "A1" if esc == "A1" else "A2"
    if f.get("temas"):
        docs = db.q("SELECT * FROM docs WHERE id IN (%s)" % ",".join("?" * len(f["temas"])), f["temas"])
    else:
        docs = db.q("SELECT * FROM docs WHERE temario=? AND kind='tema'", (tem,))
        if f.get("bloques"):
            docs = [d for d in docs if d["bloque"] in f["bloques"]]
    if not docs:
        return []
    if f.get("temas"):
        return [docs[i % len(docs)] for i in range(n_batches)]
    return random.choices(docs, weights=_weakness_weights(docs), k=n_batches)


def _fmt_q(q):
    opts = "\n".join(f"   {k}) {q[k]}" for k in LETTERS if q.get(k))
    return f"{q['text']}\n{opts}\n   Correcta: {eff(q)}"


def _examples(doc_id, temario, escala, k=8):
    """Preguntas reales de examen del tema (mejor de la misma escala) + tus falladas + las marcadas como fáciles."""
    cond = "q.a1_doc=?" if temario == "A1" else "(q.a2_doc=? OR q.a2_doc2=?)"
    args = (doc_id,) if temario == "A1" else (doc_id, doc_id)
    exam = db.q(f"""SELECT q.* FROM questions q WHERE {cond} AND q.disabled=0 AND q.origin='preparatic' AND q.is_exam=1
                    ORDER BY (q.escala=?) DESC, random() LIMIT ?""", args + (escala, k))
    if len(exam) < k:
        exam += db.q(f"""SELECT q.* FROM questions q WHERE {cond} AND q.disabled=0 AND q.origin='preparatic' AND q.is_exam=0
                         ORDER BY random() LIMIT ?""", args + (k - len(exam),))
    failed = db.q(f"""SELECT q.* FROM questions q JOIN review r ON r.question_id=q.id WHERE {cond} AND r.mastered=0
                      ORDER BY r.fails DESC, random() LIMIT 3""", args)
    easy = db.q(f"""SELECT q.* FROM questions q WHERE {cond} AND q.origin='ia' AND q.rating='facil'
                    ORDER BY q.rated_at DESC LIMIT 3""", args)
    if len(easy) < 2:
        easy += db.q("SELECT * FROM questions WHERE origin='ia' AND rating='facil' ORDER BY rated_at DESC LIMIT ?", (3 - len(easy),))
    recent_ia = db.q(f"SELECT q.text FROM questions q WHERE {cond} AND q.origin='ia' ORDER BY q.id DESC LIMIT 15", args)
    return exam, failed, easy, recent_ia


def _review(cands, doc, escala, exam):
    """Segunda pasada: otra llamada resuelve cada pregunta a ciegas y puntúa su dificultad."""
    ref = "\n\n".join(_fmt_q(q) for q in exam[:4])
    listado = "\n\n".join(
        f"[{i}] {p['enunciado']}\n" + "\n".join(f"   {k}) {p[k]}" for k in LETTERS) for i, p in enumerate(cands))
    prompt = f"""Eres miembro del tribunal de la oposición {ESCALA_TXT.get(escala, ESCALA_TXT['A2'])}.
Tema: {doc['title']}

Resuelve cada pregunta candidata SIN ver la solución propuesta. Para cada una indica:
- "respuesta": la opción correcta según la normativa y la técnica vigentes.
- "unica_correcta": false si hay más de una opción defendible, ninguna correcta o la pregunta es ambigua.
- "dificultad" de 1 a 5 comparada con estas preguntas reales de examen (que valen 3-4):
  1 = se acierta por sentido común o descartando lo absurdo; 2 = definición básica;
  3 = como el examen real; 4 = exige un dato preciso o distinguir conceptos parecidos; 5 = solo la acierta un experto.
- "motivo": una frase.

Preguntas reales de referencia:
{ref or '(no hay)'}

Candidatas:
{listado}"""
    res = gemini.generate(prompt, schema=REVIEW_SCHEMA, temperature=0)
    return {r.get("n"): r for r in (res.get("revision") or [])}


def _gen_batch(doc, escala, per_call, job_id):
    ctx, pages = _doc_context(doc["id"])
    rel = _related(doc)
    if not ctx:
        other = rel["a2_doc"] if doc["temario"] == "A1" else rel["a1_doc"]
        if other:
            ctx, pages = _doc_context(other)
    exam, failed, easy, recent = _examples(doc["id"], doc["temario"], escala)
    level = gen_level()
    min_dif = {1: 3, 2: 3, 3: 4}[level]
    ask = per_call + 3                      # se piden de más porque la revisión descarta las flojas
    prompt = f"""Eres miembro del tribunal que redacta el examen tipo test de la oposición {ESCALA_TXT.get(escala, ESCALA_TXT['A2'])}.
Escribe {ask} preguntas NUEVAS del tema: {doc['title']}

{NIVELES[level]}
Las preguntas deben estar al nivel de las preguntas REALES de examen de abajo (imita su estilo, su precisión y el tipo de distractores),
nunca por debajo. Un opositor que solo tenga una idea general del tema debe fallarlas.

Técnicas que usa el tribunal (combina varias):
{TECNICAS}

Prohibido:
- Preguntas de definición evidente o que se acierten por sentido común o descartando opciones absurdas.
- Distractores de otro ámbito, inventados a simple vista, o más cortos/largos que la correcta de forma llamativa.
- "Todas las anteriores" / "Ninguna de las anteriores", salvo en preguntas de combinación.
- Repetir o parafrasear las preguntas existentes listadas abajo.

Requisitos:
- 4 opciones (a, b, c, d) con una única correcta indiscutible según la normativa y la técnica vigentes en España.
- Basa los datos en el texto del temario cuando exista. Varía la letra correcta.
- "explicacion": por qué es correcta y en qué falla el distractor más tentador (2-3 frases). "fuente": norma, artículo o apartado.

Preguntas REALES de examen de este tema (referencia de nivel y estilo):
{chr(10).join(_fmt_q(q) for q in exam) or '(no hay; usa el nivel habitual de los exámenes de la AGE)'}
{('''
Preguntas que este opositor ha FALLADO (genera al menos una que trabaje el mismo concepto desde otro ángulo):
''' + chr(10).join(_fmt_q(q) for q in failed)) if failed else ''}
{('''
Preguntas generadas antes que el opositor marcó como DEMASIADO FÁCILES (no hagas nada parecido):
''' + chr(10).join(_fmt_q(q) for q in easy)) if easy else ''}
{('''
Ya generadas de este tema (no repetir):
''' + chr(10).join('- ' + r['text'][:160] for r in recent)) if recent else ''}

Texto del temario:
\"\"\"{ctx[:7500] if ctx else '(no disponible: usa tu conocimiento del temario oficial)'}\"\"\""""
    res = gemini.generate(prompt, schema=GEN_SCHEMA, temperature=0.8, max_tokens=12000)
    cands = []
    for p in res.get("preguntas") or []:
        opts = [str(p.get(k, "")).strip() for k in LETTERS]
        if not p.get("enunciado") or not all(opts) or p.get("correcta") not in LETTERS or len(set(map(importer.norm, opts))) < 4:
            continue
        p.update(dict(zip(LETTERS, opts)))
        cands.append(p)
    if not cands:
        return 0
    try:
        rev = _review(cands, doc, escala, exam)
    except Exception:
        rev = None                           # si falla la revisión, se guardan sin filtrar antes que perderlas
    keep = []
    for i, p in enumerate(cands):
        r = (rev or {}).get(i)
        if rev is not None:
            if not r or not r.get("unica_correcta") or r.get("respuesta") != p["correcta"]:
                continue                     # el revisor no llega a la misma solución: pregunta dudosa
            if int(r.get("dificultad") or 0) < min_dif:
                continue                     # demasiado fácil
            p["_dif"] = int(r["dificultad"])
        keep.append(p)
    keep.sort(key=lambda p: -p.get("_dif", 0))
    saved = 0
    for p in keep[:per_call]:
        opts = [p[k] for k in LETTERS]
        h = importer.qhash(p["enunciado"], opts)
        src = p.get("fuente") or ""
        if pages:
            src = (src + " · " if src else "") + f"Temario págs. {min(pages)}-{max(pages)}"
        cur = db.conn().execute(
            """INSERT OR IGNORE INTO questions(origin,text,a,b,c,d,correct,explanation,comments,year,block,a1_doc,a2_doc,
               escala,is_new,gen_job,hash,difficulty) VALUES('ia',?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
            (p["enunciado"].strip(), *opts, p["correcta"], p.get("explicacion"), "Generada por IA · " + src,
             str(dt.date.today().year), rel["block"], rel["a1_doc"], rel["a2_doc"], escala, job_id, h, p.get("_dif")))
        saved += cur.rowcount
    db.conn().commit()
    return saved


def start_generation(n, filters=None, trigger="manual"):
    n = max(1, min(int(n), 200))
    jid = db.run("INSERT INTO gen_jobs(trigger,requested,filters,status) VALUES(?,?,?,'en_cola')",
                 (trigger, n, json.dumps(filters or {}, ensure_ascii=False)))
    threading.Thread(target=_run_job, args=(jid, n, filters or {}, trigger), daemon=True).start()
    return db.q1("SELECT * FROM gen_jobs WHERE id=?", (jid,))


def _run_job(jid, n, filters, trigger):
    with _gen_lock:
        db.run("UPDATE gen_jobs SET status='generando' WHERE id=?", (jid,))
        per_call = 5
        escala = (filters.get("escalas") or [None])[0]
        default_esc = db.load_config().get("default_escala", "A2")
        _adapt_level()
        # la revisión descarta parte de lo generado: se preparan más lotes de los justos
        batches = _pick_docs(filters, (n + per_call - 1) // per_call * 2 + 2)
        made, errors = 0, []
        for doc in batches:
            if made >= n:
                break
            esc = escala or ("A1" if doc["temario"] == "A1" else (default_esc if default_esc in ("A2", "C1") else "A2"))
            try:
                made += _gen_batch(doc, esc, min(per_call, n - made), jid)
                db.run("UPDATE gen_jobs SET generated=? WHERE id=?", (made, jid))
            except Exception as e:
                errors.append(str(e)[:300])
                traceback.print_exc()
                if "API key" in str(e) or "HTTP 403" in str(e) or "HTTP 401" in str(e):
                    break
        status = "ok" if made else "error"
        db.run("UPDATE gen_jobs SET status=?, generated=?, error=?, finished_at=datetime('now','localtime') WHERE id=?",
               (status, made, "\n".join(errors[:3]) or None, jid))
        if made:
            notify("nuevas", f"{made} preguntas nuevas", "Ya tienes preguntas nuevas generadas para hacer.", "#/test/nuevas")
        elif trigger == "diario":
            notify("error", "No se pudieron generar preguntas", (errors[0] if errors else "Error desconocido")[:200], "#/ajustes")


def job(jid):
    return db.q1("SELECT * FROM gen_jobs WHERE id=?", (jid,))


# ---------------------------------------------------------------- tareas programadas

def scheduler_tick(now=None):
    """Se llama cada minuto desde el servidor."""
    now = now or dt.datetime.now()
    cfg = db.load_config()
    t = now.date().isoformat()
    if now.hour >= int(cfg.get("daily_gen_hour", 7)) and db.kv_get("gen_day") != t:
        db.kv_set("gen_day", t)
        if cfg.get("gemini_api_key") and int(cfg.get("daily_new_questions", 20)) > 0:
            start_generation(int(cfg.get("daily_new_questions", 20)), {}, "diario")
    if now.hour >= int(cfg.get("review_reminder_hour", 9)) and db.kv_get("rev_day") != t:
        db.kv_set("rev_day", t)
        due = db.scalar("SELECT COUNT(*) FROM review WHERE mastered=0 AND due<=?", (t,))
        if due:
            notify("repaso", f"Tienes {due} falladas por repasar", "Repásalas hoy para que no se te olviden.", "#/test/repaso")
    if now.hour >= int(cfg.get("goal_reminder_hour", 20)) and db.kv_get("goal_day") != t:
        db.kv_set("goal_day", t)
        goal = int(cfg.get("daily_goal", 50))
        done = db.scalar("SELECT COUNT(*) FROM attempts WHERE day=?", (t,)) or 0
        if done < goal:
            notify("objetivo", f"Te faltan {goal - done} preguntas", f"Llevas {done} de {goal} del mínimo diario.", "#/")
