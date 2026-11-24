"""Simulacro de examen, mapa de temas y modo «5 minutos»."""
import datetime as dt
import json
import random

import db
import logic

ROMAN = ["I", "II", "III", "IV"]


# ------------------------------------------------------------------ mapa de temas

def _temario_for(escala=None):
    escala = escala or db.load_config().get("default_escala", "A2")
    return "A1" if escala == "A1" else "A2"


def topic_map(temario=None):
    """Por tema: dominio (acierto suavizado), días sin practicar y prioridad de estudio."""
    temario = temario or _temario_for()
    docs = db.q("SELECT id, bloque, num, title FROM docs WHERE temario=? AND kind='tema' ORDER BY bloque, num", (temario,))
    if temario == "A1":
        rows = db.q("""SELECT q.a1_doc d, COUNT(*) n, SUM(a.is_correct) ok, MAX(a.day) last FROM attempts a
                       JOIN questions q ON q.id=a.question_id WHERE q.a1_doc IS NOT NULL
                       AND a.day>=date('now','-120 days') GROUP BY q.a1_doc""")
        avail = {r["d"]: r["n"] for r in db.q("SELECT a1_doc d, COUNT(*) n FROM questions WHERE disabled=0 GROUP BY a1_doc")}
    else:
        rows = []
        for col in ("a2_doc", "a2_doc2"):
            rows += db.q(f"""SELECT q.{col} d, COUNT(*) n, SUM(a.is_correct) ok, MAX(a.day) last FROM attempts a
                             JOIN questions q ON q.id=a.question_id WHERE q.{col} IS NOT NULL
                             AND a.day>=date('now','-120 days') GROUP BY q.{col}""")
        avail = {}
        for col in ("a2_doc", "a2_doc2"):
            for r in db.q(f"SELECT {col} d, COUNT(*) n FROM questions WHERE disabled=0 AND {col} IS NOT NULL GROUP BY {col}"):
                avail[r["d"]] = avail.get(r["d"], 0) + r["n"]
    st = {}
    for r in rows:
        x = st.setdefault(r["d"], {"n": 0, "ok": 0, "last": None})
        x["n"] += r["n"]
        x["ok"] += r["ok"] or 0
        x["last"] = max(filter(None, [x["last"], r["last"]])) if (x["last"] or r["last"]) else None
    due = {}
    col = "a1_doc" if temario == "A1" else "a2_doc"
    for r in db.q(f"""SELECT q.{col} d, COUNT(*) n FROM review r JOIN questions q ON q.id=r.question_id
                      WHERE r.mastered=0 AND r.due<=? GROUP BY q.{col}""", (logic.today(),)):
        due[r["d"]] = r["n"]
    today = dt.date.today()
    out = []
    for d in docs:
        x = st.get(d["id"], {"n": 0, "ok": 0, "last": None})
        n, ok = x["n"], x["ok"]
        acc = (ok + 2) / (n + 4)                       # suavizado: con pocas respuestas no se fía del todo
        days = (today - dt.date.fromisoformat(x["last"])).days if x["last"] else None
        if n < 5:
            level = "nuevo"
        elif acc >= 0.85 and n >= 25:
            level = "dominado"
        elif acc >= 0.7:
            level = "bien"
        elif acc >= 0.5:
            level = "flojo"
        else:
            level = "mal"
        stale = days is not None and days > 14
        prio = (1 - acc) + (0.6 if n < 5 else 0) + (min(days, 45) / 45 * 0.5 if days else 0)
        out.append({"id": d["id"], "bloque": d["bloque"], "num": d["num"], "title": d["title"], "answered": n,
                    "accuracy": round(100 * ok / n) if n else None, "level": level, "days": days, "stale": stale,
                    "due": due.get(d["id"], 0), "available": avail.get(d["id"], 0), "priority": round(prio, 3)})
    return {"temario": temario, "topics": out,
            "summary": {lvl: sum(1 for t in out if t["level"] == lvl) for lvl in ("dominado", "bien", "flojo", "mal", "nuevo")}}


def weak_topics(k=6, temario=None):
    m = topic_map(temario)["topics"]
    return [t for t in sorted(m, key=lambda t: -t["priority"]) if t["available"]][:k]


# ------------------------------------------------------------------ modo 5 minutos

def quick_test(n=10, title="5 minutos"):
    """Mezcla: falladas que tocan hoy + preguntas de los temas más débiles u olvidados."""
    ids = [r["question_id"] for r in db.q(
        "SELECT question_id FROM review WHERE mastered=0 AND due<=? ORDER BY due, stability LIMIT ?", (logic.today(), max(2, n * 4 // 10)))]
    temario = _temario_for()
    col = "a1_doc" if temario == "A1" else "a2_doc"
    topics = weak_topics(8, temario)
    i = 0
    while len(ids) < n and topics and i < n * 3:
        t = topics[i % len(topics)]
        cond = "q.a1_doc=?" if temario == "A1" else "(q.a2_doc=? OR q.a2_doc2=?)"
        args = (t["id"],) if temario == "A1" else (t["id"], t["id"])
        r = db.q1(f"""SELECT q.id FROM questions q WHERE {cond} AND q.disabled=0 AND q.id NOT IN ({",".join("?" * len(ids)) or "0"})
                      ORDER BY (SELECT COUNT(*) FROM attempts a WHERE a.question_id=q.id), random() LIMIT 1""",
                  args + tuple(ids))
        if r:
            ids.append(r["id"])
        i += 1
    if len(ids) < n:
        ids += [r["id"] for r in db.q(f"SELECT id FROM questions WHERE disabled=0 AND {col} IS NOT NULL ORDER BY random() LIMIT ?",
                                      (n - len(ids),))]
    return logic.create_test("rapido5" if n <= 10 else "rapido", n, "practica", {}, title, ids[:n])


# ------------------------------------------------------------------ simulacro GSI

def _block_weights():
    """Reparto de preguntas por bloque, proporcional al número de temas del programa del A2."""
    rows = db.q("SELECT bloque, COUNT(*) n FROM docs WHERE temario='A2' AND kind='tema' GROUP BY bloque")
    return {r["bloque"]: r["n"] for r in rows if r["bloque"] in ROMAN}


def _split(total, weights):
    s = sum(weights.values()) or 1
    raw = {k: total * v / s for k, v in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out.values())]:
        out[k] += 1
    return out


def create_simulacro(n=None, minutes=None):
    cfg = db.load_config()
    n = int(n or cfg.get("sim_questions", 100))
    minutes = int(minutes or cfg.get("sim_minutes", 90))
    per = _split(n, _block_weights())
    ids, blocks = [], []
    for b in ROMAN:
        k = per.get(b, 0)
        if not k:
            continue
        like = f"A2-{b}-%"
        rows = db.q("""SELECT q.id FROM questions q WHERE q.disabled=0 AND (q.a2_doc LIKE ? OR q.a2_doc2 LIKE ?)
                       AND q.id NOT IN (SELECT ti.question_id FROM test_items ti JOIN tests t ON t.id=ti.test_id
                                        WHERE t.kind='simulacro' AND t.created_at>=datetime('now','-30 days'))
                       ORDER BY q.is_exam DESC, (q.escala='A2') DESC,
                                (SELECT COUNT(*) FROM attempts a WHERE a.question_id=q.id), random()
                       LIMIT ?""", (like, like, k * 3))
        pool = [r["id"] for r in rows if r["id"] not in ids]
        pick = pool[:k * 2]
        random.shuffle(pick)
        ids += pick[:k]
        blocks += [b] * len(pick[:k])
    if len(ids) < n:
        ids += [r["id"] for r in db.q(f"""SELECT id FROM questions WHERE disabled=0 AND a2_doc IS NOT NULL
            AND id NOT IN ({",".join("?" * len(ids)) or "0"}) ORDER BY random() LIMIT ?""", tuple(ids) + (n - len(ids),))]
    num = (db.scalar("SELECT COUNT(*) FROM tests WHERE kind='simulacro'") or 0) + 1
    # el orden por bloques imita al examen real; se crea sin barajar
    tid = db.run("INSERT INTO tests(kind,mode,title,filters,n,time_limit,started_at,meta) VALUES(?,?,?,?,?,?,datetime('now','localtime'),?)",
                 ("simulacro", "examen", f"Simulacro GSI n.º {num}", "{}", len(ids), minutes * 60,
                  json.dumps({"per_block": per, "blocks": blocks}, ensure_ascii=False)))
    c = db.conn()
    c.executemany("INSERT INTO test_items(test_id,pos,question_id) VALUES(?,?,?)", [(tid, i, q) for i, q in enumerate(ids)])
    c.commit()
    return logic.get_test(tid)


def simulacro_breakdown(tid):
    items = db.q("""SELECT ti.pos, ti.chosen, ti.is_correct, q.a2_doc, q.a2_doc2 FROM test_items ti JOIN questions q ON q.id=ti.question_id
                    WHERE ti.test_id=?""", (tid,))
    try:
        blocks = json.loads(db.scalar("SELECT meta FROM tests WHERE id=?", (tid,)) or "{}").get("blocks") or []
    except Exception:
        blocks = []
    out = {b: {"ok": 0, "ko": 0, "blank": 0} for b in ROMAN}
    for it in items:
        doc = it["a2_doc"] or it["a2_doc2"] or ""
        b = blocks[it["pos"]] if it["pos"] < len(blocks) else (doc.split("-")[1] if doc.count("-") >= 2 else None)
        if b not in out:
            continue
        k = "blank" if it["chosen"] is None else ("ok" if it["is_correct"] == 1 else "ko")
        out[b][k] += 1
    for b, v in out.items():
        v["score"] = round(v["ok"] - v["ko"] / 3, 2)
    return out


def simulacros():
    rows = db.q("""SELECT id, created_at, finished_at, n, ok, ko, blank, score, time_limit, started_at FROM tests
                   WHERE kind='simulacro' ORDER BY id DESC LIMIT 30""")
    for r in rows:
        r["nota10"] = round(max(0, r["score"] or 0) * 10 / r["n"], 2) if r["finished_at"] and r["n"] else None
    return rows


def time_left(t):
    """Segundos que quedan de un test con tiempo, o None."""
    if not t.get("time_limit") or not t.get("started_at"):
        return None
    start = dt.datetime.fromisoformat(t["started_at"])
    return int(t["time_limit"] - (dt.datetime.now() - start).total_seconds())


def widget():
    h = logic.home()
    return {"answered": h["answered"], "goal": h["goal"], "review_due": h["review_due"], "new": h["new_questions"],
            "streak": h["streak"], "fichas_due": db.scalar("SELECT COUNT(*) FROM fichas WHERE due<=?", (logic.today(),)) or 0,
            "open_test": bool(h.get("open_test"))}
