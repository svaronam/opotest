"""Repaso de leyes por artículos (A1 y A2).

La Raspberry descarga el texto consolidado de cada norma desde la API de datos abiertos del BOE, lo divide
en artículos y la IA crea preguntas literales (plazos, órganos, cifras, excepciones) citando el artículo.
"""
import datetime as dt
import json
import random
import re
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET

import db
import gemini
import importer
import logic

API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/texto"
UA = "OpoTest/1.1 (estudio personal; Raspberry Pi)"

# id BOE, nombre corto, título, temarios, palabras para enlazarla con los temas
LAWS = [
    ("BOE-A-1978-31229", "CE", "Constitución Española", ["A1", "A2"], ["Constitución"]),
    ("BOE-A-2015-10565", "Ley 39/2015", "Procedimiento Administrativo Común de las AAPP", ["A1", "A2"], ["39/2015", "procedimiento administrativo"]),
    ("BOE-A-2015-10566", "Ley 40/2015", "Régimen Jurídico del Sector Público", ["A1", "A2"], ["40/2015", "régimen jurídico"]),
    ("BOE-A-1997-25336", "Ley 50/1997", "Ley del Gobierno", ["A1", "A2"], ["Gobierno"]),
    ("BOE-A-2015-11719", "TREBEP", "Estatuto Básico del Empleado Público (RDL 5/2015)", ["A1", "A2"], ["empleado público", "función pública"]),
    ("BOE-A-2003-21614", "Ley 47/2003", "General Presupuestaria", ["A1", "A2"], ["presupuest"]),
    ("BOE-A-2017-12902", "LCSP", "Contratos del Sector Público (Ley 9/2017)", ["A1", "A2"], ["contrat"]),
    ("BOE-A-2013-12887", "Ley 19/2013", "Transparencia, acceso a la información pública y buen gobierno", ["A1", "A2"], ["transparencia"]),
    ("BOE-A-2018-16673", "LOPDGDD", "Protección de Datos Personales y garantía de los derechos digitales (LO 3/2018)", ["A1", "A2"], ["protección de datos"]),
    ("DOUE-L-2016-80807", "RGPD", "Reglamento General de Protección de Datos (UE 2016/679)", ["A1", "A2"], ["protección de datos", "RGPD"]),
    ("BOE-A-2022-7191", "ENS", "Esquema Nacional de Seguridad (RD 311/2022)", ["A1", "A2"], ["Esquema Nacional de Seguridad", "seguridad"]),
    ("BOE-A-2010-1331", "ENI", "Esquema Nacional de Interoperabilidad (RD 4/2010)", ["A1", "A2"], ["interoperabilidad"]),
    ("BOE-A-2021-5032", "RD 203/2021", "Reglamento de actuación y funcionamiento del sector público por medios electrónicos", ["A1", "A2"], ["electrónic", "administración electrónica"]),
    ("BOE-A-2018-12699", "RD 1112/2018", "Accesibilidad de sitios web y apps móviles del sector público", ["A1", "A2"], ["accesibilidad"]),
    ("BOE-A-2020-14046", "Ley 6/2020", "Servicios electrónicos de confianza", ["A1", "A2"], ["firma electrónica", "confianza"]),
    ("BOE-A-2007-19814", "Ley 37/2007", "Reutilización de la información del sector público", ["A1", "A2"], ["reutilización", "datos abiertos"]),
    ("BOE-A-2007-6115", "LO 3/2007", "Igualdad efectiva de mujeres y hombres", ["A1", "A2"], ["igualdad"]),
    ("BOE-A-2004-21760", "LO 1/2004", "Medidas de Protección Integral contra la Violencia de Género", ["A1", "A2"], ["violencia de género"]),
    ("BOE-A-2013-12632", "RDL 1/2013", "Derechos de las personas con discapacidad y su inclusión social", ["A1", "A2"], ["discapacidad"]),
    ("BOE-A-2006-21990", "Ley 39/2006", "Autonomía personal y atención a la dependencia", ["A1", "A2"], ["dependencia"]),
    ("BOE-A-2022-10757", "Ley 11/2022", "General de Telecomunicaciones", ["A1", "A2"], ["telecomunicaciones"]),
    ("BOE-A-2002-13758", "LSSI", "Servicios de la sociedad de la información y comercio electrónico (Ley 34/2002)", ["A1"], ["comercio electrónico", "sociedad de la información"]),
    ("BOE-A-1996-8930", "LPI", "Propiedad Intelectual (RDL 1/1996)", ["A1"], ["propiedad intelectual"]),
]
BY_ID = {x[0]: x for x in LAWS}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS laws (
  id TEXT PRIMARY KEY, short TEXT, title TEXT, temarios TEXT, status TEXT DEFAULT 'pendiente',
  n_articles INTEGER DEFAULT 0, fetched_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS law_articles (
  law_id TEXT, idx INTEGER, num TEXT, titulo TEXT, texto TEXT, nq INTEGER DEFAULT 0,
  PRIMARY KEY (law_id, idx)
);
"""


def init():
    c = db.conn()
    c.executescript(SCHEMA_SQL)
    cols = {r[1] for r in c.execute("PRAGMA table_info(questions)")}
    if "law_id" not in cols:
        c.execute("ALTER TABLE questions ADD COLUMN law_id TEXT")
        c.execute("ALTER TABLE questions ADD COLUMN law_art TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS q_law ON questions(law_id)")
    for lid, short, title, tems, _kw in LAWS:
        c.execute("""INSERT INTO laws(id,short,title,temarios) VALUES(?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET short=excluded.short, title=excluded.title, temarios=excluded.temarios""",
                  (lid, short, title, ",".join(tems)))
    c.commit()


# ------------------------------------------------------------------ descarga y troceo

def _text(el):
    """Texto de una <version> sin las notas de modificación (blockquote)."""
    out = []
    for ch in el:
        if ch.tag == "blockquote":
            continue
        t = "".join(ch.itertext()).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    arts = []
    for b in root.iter("bloque"):
        if b.get("tipo") != "precepto":
            continue
        vers = b.findall("version")
        if not vers:
            continue
        v = max(vers, key=lambda x: (x.get("fecha_vigencia") or x.get("fecha_publicacion") or ""))
        txt = _text(v)
        titulo = (b.get("titulo") or "").strip()
        if not txt or re.search(r"\((Derogad[oa]|Sin contenido|Suprimid[oa])\)", txt[:200]):
            continue
        lines = txt.split("\n")
        head = lines[0]
        body = "\n".join(lines[1:]).strip() or head
        m = re.match(r"(Artículo|Disposición)\s+([^.]+)\.?\s*(.*)", head)
        name = (m.group(3).strip() if m and m.group(3) else "")
        arts.append({"num": titulo or (m.group(1) + " " + m.group(2) if m else head[:40]), "titulo": name[:200], "texto": body})
    return arts


def fetch(law_id):
    req = urllib.request.Request(API.format(id=law_id), headers={"Accept": "application/xml", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    arts = parse(data)
    if not arts:
        raise ValueError("el BOE no devolvió artículos")
    c = db.conn()
    old = {r["num"]: r["nq"] for r in db.q("SELECT num, nq FROM law_articles WHERE law_id=?", (law_id,))}
    c.execute("DELETE FROM law_articles WHERE law_id=?", (law_id,))
    c.executemany("INSERT INTO law_articles(law_id,idx,num,titulo,texto,nq) VALUES(?,?,?,?,?,?)",
                  [(law_id, i, a["num"], a["titulo"], a["texto"], old.get(a["num"], 0)) for i, a in enumerate(arts)])
    c.execute("UPDATE laws SET status='ok', n_articles=?, fetched_at=datetime('now','localtime'), error=NULL WHERE id=?",
              (len(arts), law_id))
    c.commit()
    return len(arts)


def fetch_pending(k=1):
    """Descarga las que faltan (y refresca cada 60 días)."""
    rows = db.q("""SELECT id FROM laws WHERE status!='ok' AND (error IS NULL OR fetched_at IS NULL OR fetched_at < datetime('now','-1 day'))
                   UNION SELECT id FROM laws WHERE status='ok' AND fetched_at < datetime('now','-60 days') LIMIT ?""", (k,))
    for r in rows:
        try:
            n = fetch(r["id"])
            print("ley descargada", r["id"], n, "artículos", flush=True)
        except Exception as e:
            db.run("UPDATE laws SET status='error', error=?, fetched_at=datetime('now','localtime') WHERE id=?", (str(e)[:300], r["id"]))
        time.sleep(2)
    return len(rows)


# ------------------------------------------------------------------ preguntas

Q_SCHEMA = {
    "type": "OBJECT",
    "properties": {"preguntas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "art": {"type": "INTEGER"}, "texto": {"type": "STRING"},
        "a": {"type": "STRING"}, "b": {"type": "STRING"}, "c": {"type": "STRING"}, "d": {"type": "STRING"},
        "correcta": {"type": "STRING", "enum": ["a", "b", "c", "d"]},
        "cita": {"type": "STRING"}, "explicacion": {"type": "STRING"},
    }, "required": ["art", "texto", "a", "b", "c", "d", "correcta", "cita"]}}},
    "required": ["preguntas"],
}

DENSE = re.compile(r"\b(\d+|días?|meses|años|plazo|hábiles|naturales|mayoría|órgano|competen|Consejo|Ministr|Director|"
                   r"excepto|salvo|en ningún caso|silencio|recurso|nulidad|anulab)\w*", re.I)


def _pick_articles(law_id, k=8):
    rows = db.q("SELECT * FROM law_articles WHERE law_id=? AND length(texto) > 120", (law_id,))
    if not rows:
        return []
    for r in rows:
        r["_w"] = (1 + len(DENSE.findall(r["texto"][:3000]))) / (1 + 3 * r["nq"])
    out = []
    pool = rows[:]
    while pool and len(out) < k:
        r = random.choices(pool, weights=[x["_w"] for x in pool], k=1)[0]
        out.append(r)
        pool.remove(r)
    return out


def _docs_for(law, temario):
    kws = BY_ID.get(law["id"], (None, None, None, None, []))[4]
    docs = db.q("SELECT id, title FROM docs WHERE temario=? AND kind='tema'", (temario,))
    for kw in kws:
        for d in docs:
            if kw.lower() in (d["title"] or "").lower():
                return d["id"]
    return None


def next_law(temario=None):
    """La ley con menos preguntas en proporción a sus artículos (de tu escala primero)."""
    esc = temario or db.load_config().get("default_escala", "A2")
    tem = "A1" if esc == "A1" else "A2"
    rows = db.q("""SELECT l.*, (SELECT COUNT(*) FROM questions q WHERE q.law_id=l.id) nq FROM laws l
                   WHERE l.status='ok' AND l.n_articles>0""")
    rows = [r for r in rows if tem in (r["temarios"] or "")] or rows
    if not rows:
        return None
    return min(rows, key=lambda r: r["nq"] / max(1, r["n_articles"]) + random.random() * 0.02)


def generate(law_id=None, n=8, background=True, temario=None):
    law = db.q1("SELECT * FROM laws WHERE id=?", (law_id,)) if law_id else next_law(temario)
    if not law or law["status"] != "ok":
        raise ValueError("Esa ley aún no está descargada")
    arts = _pick_articles(law["id"], n)
    if not arts:
        return 0
    blocks = "\n\n".join(f"[{i}] {a['num']}{(' · ' + a['titulo']) if a['titulo'] else ''}\n{a['texto'][:2500]}"
                         for i, a in enumerate(arts))
    prompt = f"""Eres miembro del tribunal de las oposiciones TIC de la AGE (A1 y A2). Crea UNA pregunta tipo test por cada
artículo de la norma «{law['short']} · {law['title']}» (texto consolidado vigente). Para cada una:
- "art": el número [n] del artículo. Pregunta sobre un dato LITERAL del artículo: plazo, cifra, órgano competente,
  mayoría, requisito, excepción o enumeración. Nada de preguntas de opinión ni de otros artículos.
- 4 opciones con UNA sola correcta. Distractores verosímiles: plazos o cifras cercanas, órgano parecido, cambiar
  «hábiles» por «naturales», «podrá» por «deberá», añadir o quitar un elemento de una lista.
- "cita": la frase exacta del artículo que justifica la respuesta. "explicacion": 1 frase.
- Varía la posición de la correcta.

ARTÍCULOS:
{blocks}"""
    res = gemini.generate(prompt, schema=Q_SCHEMA, temperature=0.5, thinking="low", max_tokens=9000,
                          budget=150 if background else 90, call_timeout=120, kind="leyes", background=background)
    c = db.conn()
    saved = 0
    tems = (law["temarios"] or "").split(",")
    a1 = _docs_for(law, "A1") if "A1" in tems else None
    a2 = _docs_for(law, "A2") if "A2" in tems else None
    esc = "A2" if "A2" in tems else "A1"
    for p in res.get("preguntas") or []:
        i = p.get("art")
        if not isinstance(i, int) or not 0 <= i < len(arts) or not all(p.get(k) for k in "abcd"):
            continue
        art = arts[i]
        cita = (p.get("cita") or "").strip()
        expl = ((p.get("explicacion") or "").strip() + (f"\n«{cita}»" if cita else "")).strip()
        h = importer.qhash(p["texto"], [p[k] for k in "abcd"])
        cur = c.execute(
            """INSERT OR IGNORE INTO questions(origin,text,a,b,c,d,correct,comments,explanation,is_exam,escala,a1_doc,a2_doc,
               is_new,law_id,law_art,hash) VALUES('ia',?,?,?,?,?,?,?,?,0,?,?,?,1,?,?,?)""",
            (p["texto"].strip(), p["a"], p["b"], p["c"], p["d"], p["correcta"], f"Generada por IA · {law['short']}, {art['num'].lower()}",
             expl, esc, a1, a2, law["id"], art["num"], h))
        if cur.rowcount:
            saved += 1
            c.execute("UPDATE law_articles SET nq=nq+1 WHERE law_id=? AND idx=?", (law["id"], art["idx"]))
    c.commit()
    db.kv_set("leyes_req_" + logic.today(), int(db.kv_get("leyes_req_" + logic.today(), 0) or 0) + 1)
    return saved


def requests_today():
    return int(db.kv_get("leyes_req_" + logic.today(), 0) or 0)


# ------------------------------------------------------------------ consultas

def overview(temario=None):
    rows = db.q("""SELECT l.*, (SELECT COUNT(*) FROM questions q WHERE q.law_id=l.id AND q.disabled=0) nq,
                          (SELECT COUNT(*) FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.law_id=l.id) answered,
                          (SELECT SUM(a.is_correct) FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.law_id=l.id) ok
                   FROM laws l ORDER BY rowid""")
    if temario in ("A1", "A2"):
        rows = [r for r in rows if temario in (r["temarios"] or "")]
    for r in rows:
        r["accuracy"] = round(100 * (r["ok"] or 0) / r["answered"]) if r["answered"] else None
    cfg = db.load_config()
    return {"laws": rows, "requests_today": requests_today(), "cap": int(cfg.get("leyes_daily_requests", 4))}


def articles(law_id, q=None):
    law = db.q1("SELECT * FROM laws WHERE id=?", (law_id,))
    if not law:
        raise KeyError("ley")
    rows = db.q("SELECT idx, num, titulo, texto, nq FROM law_articles WHERE law_id=? ORDER BY idx", (law_id,))
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["texto"].lower() or ql in (r["titulo"] or "").lower() or ql in r["num"].lower()]
    return {"law": law, "articles": rows}
