"""Fichas de conceptos: la IA convierte cada pregunta fallada en una ficha corta con el dato a recordar.
Se generan en lotes de 10 (una petición) en segundo plano y se repasan como tarjetas con FSRS."""
import datetime as dt
import json

import db
import gemini
import logic
import srs

BATCH = 10

SCHEMA = {
    "type": "OBJECT",
    "properties": {"fichas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "n": {"type": "INTEGER"},
        "concepto": {"type": "STRING"},
        "ficha": {"type": "STRING"},
    }, "required": ["n", "concepto", "ficha"]}}},
    "required": ["fichas"],
}


def pending(limit=BATCH):
    """Falladas sin ficha, las que más cuestan primero."""
    return db.q("""SELECT q.* FROM review r JOIN questions q ON q.id=r.question_id
                   WHERE q.disabled=0 AND NOT EXISTS (SELECT 1 FROM fichas f WHERE f.question_id=q.id)
                   ORDER BY r.mastered, COALESCE(r.lapses, r.fails) DESC, r.due LIMIT ?""", (limit,))


def _prompt(rows):
    blocks = []
    for i, q in enumerate(rows):
        corr = logic.eff(q)
        expl = ""
        c = db.scalar("SELECT content FROM sources_cache WHERE question_id=? AND source='ia'", (q["id"],))
        if c:
            try:
                expl = "\n   Explicación: " + json.loads(c).get("explicacion", "")[:400]
            except Exception:
                pass
        if q.get("explanation"):
            expl = "\n   Explicación: " + q["explanation"][:400]
        opts = "\n".join(f"   {k}) {q[k]}" for k in "abcd" if q.get(k))
        blocks.append(f"[{i}] {q['text']}\n{opts}\n   Correcta: {corr}) {q.get(corr)}{expl}")
    return f"""Eres preparador de oposiciones TIC de la Administración española (A2 GSI). Un opositor ha fallado estas preguntas.
Para CADA una crea una ficha de estudio para memorizar, con su número "n":
- "concepto": el concepto que se pregunta, en 2-8 palabras (p. ej. "RAID 6: capacidad útil").
- "ficha": el dato exacto a recordar en 1-2 frases (máx. 35 palabras), con la cifra, artículo, sigla o diferencia clave.
  Si hay un distractor típico, añade «No confundir con …». Nada de introducciones ni frases vacías.
Usa la respuesta correcta indicada. Si la normativa ha cambiado, refleja la vigente.

{chr(10).join(blocks)}"""


def generate_batch(background=True):
    """Una petición: crea hasta 10 fichas. Devuelve cuántas guardó."""
    rows = pending(BATCH)
    if not rows:
        return 0
    res = gemini.generate(_prompt(rows), schema=SCHEMA, temperature=0.3, thinking="minimal", max_tokens=6000,
                          budget=150 if background else 80, call_timeout=90, kind="fichas", background=background)
    saved = 0
    c = db.conn()
    for f in res.get("fichas") or []:
        n = f.get("n")
        if not isinstance(n, int) or not 0 <= n < len(rows) or not f.get("ficha"):
            continue
        q = rows[n]
        c.execute("""INSERT OR IGNORE INTO fichas(question_id,doc_id,concepto,texto,due) VALUES(?,?,?,?,?)""",
                  (q["id"], q.get("a2_doc") or q.get("a1_doc"), f.get("concepto", "")[:120], f["ficha"][:400], logic.today()))
        saved += 1
    c.commit()
    db.kv_set("fichas_req_" + logic.today(), int(db.kv_get("fichas_req_" + logic.today(), 0) or 0) + 1)
    return saved


def requests_today():
    return int(db.kv_get("fichas_req_" + logic.today(), 0) or 0)


def due_list(doc=None, limit=40, all_=False):
    sql = """SELECT f.*, d.title doc_title, d.temario, d.bloque, d.num FROM fichas f LEFT JOIN docs d ON d.id=f.doc_id"""
    w, a = [], []
    if not all_:
        w.append("f.due<=?")
        a.append(logic.today())
    if doc:
        w.append("f.doc_id=?")
        a.append(doc)
    if w:
        sql += " WHERE " + " AND ".join(w)
    sql += " ORDER BY f.due, f.stability LIMIT ?"
    return db.q(sql, a + [limit])


def review(fid, ok):
    f = db.q1("SELECT * FROM fichas WHERE id=?", (fid,))
    if not f:
        raise KeyError("ficha")
    st = srs.schedule(f, bool(ok), retention=float(db.load_config().get("target_retention", 0.9)))
    db.run("""UPDATE fichas SET stability=?, difficulty=?, last_review=?, due=?, reps=reps+1, lapses=lapses+? WHERE id=?""",
           (st["stability"], st["difficulty"], st["last_review"], st["due"], 0 if ok else 1, fid))
    return {"due": st["due"], "interval": st["interval"]}


def summary():
    by = db.q("""SELECT f.doc_id, d.title, d.temario, d.bloque, d.num, COUNT(*) n, SUM(f.due<=?) due FROM fichas f
                 LEFT JOIN docs d ON d.id=f.doc_id GROUP BY f.doc_id ORDER BY d.temario, d.bloque, d.num""", (logic.today(),))
    return {"total": db.scalar("SELECT COUNT(*) FROM fichas") or 0,
            "due": db.scalar("SELECT COUNT(*) FROM fichas WHERE due<=?", (logic.today(),)) or 0,
            "pending": len(pending(500)), "requests_today": requests_today(),
            "cap": int(db.load_config().get("fichas_daily_requests", 6)), "by_doc": by}
