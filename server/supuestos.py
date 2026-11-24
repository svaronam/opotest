"""Supuesto práctico del GSI (segundo ejercicio).

- Catálogo: la IA extrae los supuestos de tus PDF (exámenes reales, academias, simulacros) y los guarda
  con su bloque y sus preguntas. También puede crear supuestos nuevos con ese estilo.
- Intento: 180 minutos, respuestas por escrito y fotos de lo hecho a mano (diagramas).
- Corrección con los criterios oficiales del INAP (técnica 30, análisis 10, sistemática 5, expresión 5),
  apoyada en la solución de la academia si existe, en tus apuntes y en lo que ya te corrigió tu profesor.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import random
import re
import threading
import traceback

import db
import gemini
import logic
import sources
import spfiles

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sp_cases (
  id INTEGER PRIMARY KEY, bloque TEXT, origin TEXT, title TEXT, year TEXT,
  enunciado TEXT, preguntas TEXT, source_doc TEXT, solution_docs TEXT DEFAULT '[]',
  hash TEXT UNIQUE, created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS sp_attempts (
  id INTEGER PRIMARY KEY, case_id INTEGER, started_at TEXT, finished_at TEXT, time_limit INTEGER,
  answers TEXT DEFAULT '{}', images TEXT DEFAULT '{}', status TEXT DEFAULT 'abierto',
  result TEXT, score REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS sp_extracted (doc_id TEXT PRIMARY KEY, n INTEGER, at TEXT DEFAULT (datetime('now','localtime')));
"""

CRITERIOS = """Criterios oficiales del segundo ejercicio del GSI (INAP), sobre 50 puntos:
 a) Aplicación de los conocimientos técnicos a las situaciones prácticas: 0 a 30 puntos.
 b) Capacidad de análisis: 0 a 10 puntos.
 c) Sistemática: 0 a 5 puntos.
 d) Capacidad de expresión escrita: 0 a 5 puntos.
Se necesitan 25 puntos para aprobar. Lo corrige la Comisión Permanente de Selección de forma anónima."""

BLOQUES = {"III": "Bloque III · Desarrollo de sistemas", "IV": "Bloque IV · Sistemas y comunicaciones"}


def img_dir(aid):
    d = os.path.join(db.DATA_DIR, "sp_img", str(int(aid)))
    os.makedirs(d, exist_ok=True)
    return d


def init():
    c = db.conn()
    c.executescript(SCHEMA_SQL)
    c.commit()


def _hash(text):
    return hashlib.sha1(re.sub(r"\W+", "", spfiles.fold(text))[:600].encode()).hexdigest()


def doc_text(doc_id, max_chars=20000):
    out, n = [], 0
    for r in db.q("SELECT page, text FROM pages WHERE doc_id=? AND file_idx=0 ORDER BY page", (doc_id,)):
        t = (r["text"] or "").strip()
        if not t:
            continue
        out.append(t)
        n += len(t)
        if n >= max_chars:
            break
    return "\n\n".join(out)[:max_chars]


def _sp_docs(kinds, bloque=None):
    sql = f"SELECT * FROM docs WHERE temario='SP' AND kind IN ({','.join('?' * len(kinds))})"
    args = list(kinds)
    if bloque:
        sql += " AND (bloque=? OR bloque='')"
        args.append(bloque)
    return db.q(sql, args)


def _rel(d):
    try:
        return json.loads(d["files"])[0]
    except Exception:
        return ""


def _solutions_for(source, bloque):
    """Soluciones de la misma carpeta (o de sus subcarpetas) que el enunciado."""
    folder = os.path.dirname(_rel(source))
    if not folder:
        return []
    out = []
    for d in _sp_docs(["sp-sol"]):
        r = _rel(d)
        if (r.startswith(folder + os.sep) or os.path.dirname(r) == folder) and (not bloque or d["bloque"] in ("", bloque)):
            out.append(d["id"])
    return out[:4]


# ------------------------------------------------------------------ catálogo (extracción con IA)

EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {"supuestos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "bloque": {"type": "STRING", "enum": ["III", "IV", "otro"]},
        "titulo": {"type": "STRING"},
        "anio": {"type": "STRING"},
        "enunciado": {"type": "STRING"},
        "preguntas": {"type": "ARRAY", "items": {"type": "STRING"}},
    }, "required": ["bloque", "titulo", "enunciado", "preguntas"]}}},
    "required": ["supuestos"],
}


def pending_extract(bloque=None):
    done = {r["doc_id"] for r in db.q("SELECT doc_id FROM sp_extracted")}
    docs = [d for d in _sp_docs(["sp-real", "sp-enun"]) if d["id"] not in done and d["status"] == "ok"]
    pref = bloque or db.load_config().get("sp_bloque", "III")
    docs.sort(key=lambda d: (d["bloque"] not in (pref, ""), d["kind"] != "sp-real", d["bloque"] != pref))
    return docs


def extract_doc(doc, background=True):
    text = doc_text(doc["id"], 30000)
    if len(text) < 300:
        db.run("INSERT OR REPLACE INTO sp_extracted(doc_id,n) VALUES(?,0)", (doc["id"],))
        return 0
    prompt = f"""Este texto viene de un documento de preparación del segundo ejercicio (supuesto práctico) de la oposición
GSI de la Administración General del Estado. Archivo: «{_rel(doc)}».

Extrae CADA supuesto práctico cuyo ENUNCIADO aparezca en el texto:
- "enunciado": el caso completo tal cual (contexto, requisitos, datos), sin resumir ni inventar. Sin las preguntas.
  El texto puede venir de un escaneo: corrige solo los errores evidentes de OCR (tildes, letras cambiadas, palabras partidas).
- "preguntas": la lista de cuestiones que se piden, una por elemento, literales (con sus subapartados dentro del mismo texto).
- "bloque": "III" si es de desarrollo de sistemas (casos de uso, E-R, secuencia, arquitectura, planificación, FCE…),
  "IV" si es de sistemas y comunicaciones (CPD, redes, direccionamiento, seguridad de infraestructura…), "otro" si no encaja.
- "titulo": nombre corto del caso (organismo o sistema). "anio": año o convocatoria si se sabe.
Si el documento es solo una solución, apuntes o teoría, o el texto está demasiado roto, devuelve "supuestos": [].

TEXTO:
{text}"""
    res = gemini.generate(prompt, schema=EXTRACT_SCHEMA, temperature=0.1, thinking="low", max_tokens=16000,
                          budget=200 if background else 120, call_timeout=150, kind="supuesto-catalogo", background=background)
    n = 0
    for s in res.get("supuestos") or []:
        preg = [p.strip() for p in s.get("preguntas") or [] if p and p.strip()]
        if s.get("bloque") not in ("III", "IV") or len(s.get("enunciado", "")) < 200 or not preg:
            continue
        h = _hash(s["enunciado"])
        origin = "real" if doc["kind"] == "sp-real" else "academia"
        cur = db.conn().execute(
            """INSERT OR IGNORE INTO sp_cases(bloque,origin,title,year,enunciado,preguntas,source_doc,solution_docs,hash)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (s["bloque"], origin, s.get("titulo", "")[:120], s.get("anio", "")[:20], s["enunciado"].strip(),
             json.dumps(preg, ensure_ascii=False), doc["id"], json.dumps(_solutions_for(doc, s["bloque"])), h))
        n += cur.rowcount
    db.conn().commit()
    db.run("INSERT OR REPLACE INTO sp_extracted(doc_id,n) VALUES(?,?)", (doc["id"], n))
    return n


def extract_some(k=1, background=True):
    total = 0
    for d in pending_extract()[:k]:
        try:
            total += extract_doc(d, background)
        except gemini.QuotaError:
            raise
        except Exception as e:
            traceback.print_exc()
            db.run("INSERT OR REPLACE INTO sp_extracted(doc_id,n) VALUES(?,-1)", (d["id"],))
    if total:
        db.kv_set("sp_extract_day_" + logic.today(), int(db.kv_get("sp_extract_day_" + logic.today(), 0) or 0) + total)
    return total


# ------------------------------------------------------------------ supuestos nuevos con IA

GEN_SCHEMA = {
    "type": "OBJECT",
    "properties": {"titulo": {"type": "STRING"}, "enunciado": {"type": "STRING"},
                   "preguntas": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["titulo", "enunciado", "preguntas"],
}


def _case(cid):
    c = db.q1("SELECT * FROM sp_cases WHERE id=?", (cid,))
    if c:
        c["preguntas"] = json.loads(c["preguntas"] or "[]")
        c["solution_docs"] = json.loads(c["solution_docs"] or "[]")
    return c


def generate_case(bloque="III"):
    real = db.q("SELECT * FROM sp_cases WHERE bloque=? AND origin IN ('real','academia') ORDER BY random() LIMIT 8", (bloque,))
    model = real[0] if real else None
    lines = "\n".join(f"- {r['title']} ({r['year'] or 's/f'}): " + " | ".join(json.loads(r["preguntas"])[:6]) for r in real)
    used = [r["title"] for r in db.q("SELECT title FROM sp_cases WHERE origin='ia' ORDER BY id DESC LIMIT 15")]
    prompt = f"""Eres miembro de la Comisión Permanente de Selección del INAP y redactas el segundo ejercicio del GSI
(ingreso libre), {BLOQUES.get(bloque, bloque)}.

Crea un supuesto práctico NUEVO y realista para un organismo de la Administración General del Estado:
- Enunciado de 300-600 palabras: organismo, necesidad, actores, flujos, volumen de usuarios, plazos, restricciones
  normativas (Ley 39/2015, ENS, RGPD, accesibilidad, servicios comunes y compartidos de la AGE…) y datos concretos que
  permitan razonar las respuestas. Termina con la frase habitual sobre las suposiciones justificadas.
- Exactamente 5 preguntas como las del tribunal para este bloque.
{"Bloque III: casos de uso con actores, diagrama E-R, diagrama de secuencia, arquitectura lógica (paquetes), factores críticos de éxito, planificación (Gantt/PERT, estimación), solución de movilidad, medidas concretas del ENS, interoperabilidad, pruebas…" if bloque == "III" else "Bloque IV: diseño de CPD, red LAN/WAN, direccionamiento IP y subredes, alta disponibilidad, virtualización, almacenamiento y copias, seguridad perimetral, categorización ENS, nube…"}
- No repitas estos casos ya creados: {", ".join(used) or "ninguno"}.

Preguntas de supuestos reales para que copies el estilo:
{lines or "(aún no hay catálogo)"}

{"Enunciado real de referencia (solo estilo y extensión, NO lo copies):" + chr(10) + model["enunciado"][:3500] if model else ""}"""
    res = gemini.generate(prompt, schema=GEN_SCHEMA, temperature=0.9, thinking="low", max_tokens=8000,
                          budget=150, call_timeout=120, kind="supuesto-nuevo")
    preg = [p for p in res.get("preguntas") or [] if p.strip()][:6]
    if len(res.get("enunciado", "")) < 200 or len(preg) < 3:
        raise ValueError("La IA no devolvió un supuesto completo; inténtalo otra vez")
    cid = db.run("""INSERT INTO sp_cases(bloque,origin,title,year,enunciado,preguntas,hash) VALUES(?,?,?,?,?,?,?)""",
                 (bloque, "ia", res.get("titulo", "Supuesto")[:120], str(dt.date.today().year), res["enunciado"].strip(),
                  json.dumps(preg, ensure_ascii=False), _hash(res["enunciado"])))
    return _case(cid)


# ------------------------------------------------------------------ intentos

def _attempt(aid):
    a = db.q1("SELECT * FROM sp_attempts WHERE id=?", (aid,))
    if not a:
        return None
    for k in ("answers", "images"):
        a[k] = json.loads(a[k] or "{}")
    a["result"] = json.loads(a["result"]) if a.get("result") else None
    if a["status"] == "abierto" and a["time_limit"]:
        start = dt.datetime.fromisoformat(a["started_at"])
        a["time_left"] = int(a["time_limit"] - (dt.datetime.now() - start).total_seconds())
    return a


def start(case_id):
    if not _case(case_id):
        raise KeyError("supuesto")
    mins = int(db.load_config().get("sp_minutes", 180))
    aid = db.run("INSERT INTO sp_attempts(case_id,started_at,time_limit) VALUES(?,datetime('now','localtime'),?)",
                 (case_id, mins * 60))
    return get(aid)


def get(aid):
    a = _attempt(aid)
    if not a:
        raise KeyError("intento")
    if a["status"] == "abierto" and a.get("time_left") is not None and a["time_left"] < -60:
        finish(aid)
        a = _attempt(aid)
    a["case"] = _case(a["case_id"])
    if a["case"]:
        a["case"]["solutions"] = [{"id": d, "title": db.scalar("SELECT title FROM docs WHERE id=?", (d,))} for d in a["case"]["solution_docs"]]
    return a


def save(aid, answers):
    a = _attempt(aid)
    if not a or a["status"] != "abierto":
        raise ValueError("Este supuesto ya está entregado")
    cur = a["answers"]
    for k, v in (answers or {}).items():
        cur[str(int(k))] = str(v)[:30000]
    db.run("UPDATE sp_attempts SET answers=? WHERE id=?", (json.dumps(cur, ensure_ascii=False), aid))
    return {"saved": True}


def add_image(aid, n, data_b64):
    a = _attempt(aid)
    if not a or a["status"] != "abierto":
        raise ValueError("Este supuesto ya está entregado")
    raw = base64.b64decode(data_b64.split(",", 1)[-1])
    if len(raw) > 6_000_000:
        raise ValueError("La foto es demasiado grande")
    imgs = a["images"]
    lst = imgs.setdefault(str(int(n)), [])
    if len(lst) >= 6:
        raise ValueError("Máximo 6 fotos por pregunta")
    name = f"{int(n)}_{len(lst)}_{int(dt.datetime.now().timestamp())}.jpg"
    open(os.path.join(img_dir(aid), name), "wb").write(raw)
    lst.append(name)
    db.run("UPDATE sp_attempts SET images=? WHERE id=?", (json.dumps(imgs), aid))
    return {"name": name, "images": imgs}


def del_image(aid, n, name):
    a = _attempt(aid)
    imgs = a["images"]
    lst = imgs.get(str(int(n)), [])
    if name in lst:
        lst.remove(name)
        try:
            os.remove(os.path.join(img_dir(aid), os.path.basename(name)))
        except OSError:
            pass
    db.run("UPDATE sp_attempts SET images=? WHERE id=?", (json.dumps(imgs), aid))
    return {"images": imgs}


def image_path(aid, name):
    p = os.path.join(img_dir(aid), os.path.basename(name))
    if not os.path.exists(p):
        raise KeyError("foto")
    return p


def finish(aid):
    a = _attempt(aid)
    if not a:
        raise KeyError("intento")
    if a["status"] in ("abierto", "error"):
        db.run("UPDATE sp_attempts SET status='corrigiendo', finished_at=COALESCE(finished_at, datetime('now','localtime')), error=NULL WHERE id=?", (aid,))
        threading.Thread(target=_correct_safe, args=(aid,), daemon=True).start()
    return get(aid)


def _correct_safe(aid):
    try:
        correct(aid)
    except Exception as e:
        traceback.print_exc()
        db.run("UPDATE sp_attempts SET status='error', error=? WHERE id=?", (str(e)[:400], aid))


CORRECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "puntuacion": {"type": "OBJECT", "properties": {
            "tecnica": {"type": "NUMBER"}, "analisis": {"type": "NUMBER"},
            "sistematica": {"type": "NUMBER"}, "expresion": {"type": "NUMBER"}},
            "required": ["tecnica", "analisis", "sistematica", "expresion"]},
        "resumen": {"type": "STRING"},
        "por_pregunta": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "n": {"type": "INTEGER"}, "nota": {"type": "NUMBER"}, "valoracion": {"type": "STRING"},
            "bien": {"type": "ARRAY", "items": {"type": "STRING"}},
            "falta": {"type": "ARRAY", "items": {"type": "STRING"}},
            "errores": {"type": "ARRAY", "items": {"type": "STRING"}},
            "solucion_modelo": {"type": "STRING"},
            "refs": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["n", "nota", "valoracion", "falta", "solucion_modelo"]}},
        "consejos": {"type": "ARRAY", "items": {"type": "STRING"}},
        "conceptos": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "concepto": {"type": "STRING"}, "ficha": {"type": "STRING"}}, "required": ["concepto", "ficha"]}},
    },
    "required": ["puntuacion", "resumen", "por_pregunta", "conceptos"],
}


def _refs_for(case, k_per=3):
    """Fragmentos de tus apuntes de la academia (y del temario A2) para cada pregunta."""
    sp_ids = [d["id"] for d in db.q("SELECT id FROM docs WHERE temario='SP' AND kind IN ('sp-teoria','sp-sol') AND status='ok'")]
    a2_ids = [d["id"] for d in db.q("SELECT id FROM docs WHERE temario='A2' AND bloque=?", (case["bloque"],))]
    refs, seen = [], set()
    for p in case["preguntas"]:
        for pool, k in ((sp_ids, k_per), (a2_ids, 1)):
            if not pool:
                continue
            for h in sources.search_temario(p[:400], pool, k):
                key = (h["doc_id"], h["page"])
                if key in seen:
                    continue
                seen.add(key)
                refs.append({"ref": f"R{len(refs) + 1}", "doc_id": h["doc_id"], "page": h["page"], "title": h.get("title", ""),
                             "snip": re.sub(r"\[\[|\]\]", "", h.get("snip", ""))})
    return refs[:18]


def correct(aid):
    a = _attempt(aid)
    case = _case(a["case_id"])
    cfg = db.load_config()
    answers, imgs, images = a["answers"], a["images"], []
    blocks = []
    for i, p in enumerate(case["preguntas"], 1):
        txt = (answers.get(str(i)) or "").strip()
        fotos = imgs.get(str(i)) or []
        for name in fotos:
            try:
                images.append(("image/jpeg", open(os.path.join(img_dir(aid), name), "rb").read()))
            except OSError:
                pass
        blocks.append(f"### Pregunta {i}: {p}\nRespuesta escrita:\n{txt or '(sin texto)'}\n"
                      + (f"Fotos de esta pregunta: {len(fotos)} (imágenes adjuntas, en orden)\n" if fotos else ""))
    solution = "\n\n".join(doc_text(d, 9000) for d in case["solution_docs"])[:16000]
    feedback = "\n\n".join(doc_text(d["id"], 3000) for d in _sp_docs(["sp-feedback"]))[:6000]
    refs = _refs_for(case)
    ref_txt = "\n".join(f"[{r['ref']}] {r['title']} (pág. {r['page']}): {r['snip']}" for r in refs)
    prompt = f"""Eres miembro de la Comisión Permanente de Selección del INAP corrigiendo el segundo ejercicio del GSI.
Corrige con rigor, como el tribunal: ni regalar puntos ni hundir al opositor. Sé concreto y técnico.

{CRITERIOS}

SUPUESTO ({BLOQUES.get(case['bloque'], case['bloque'])}): {case['title']}
{case['enunciado']}

RESPUESTAS DEL OPOSITOR (las imágenes adjuntas son sus diagramas y respuestas a mano, en el orden indicado):
{chr(10).join(blocks)}

{"SOLUCIÓN DE REFERENCIA DE UNA ACADEMIA (orientativa, no es la oficial):" + chr(10) + solution if solution else "No hay solución de referencia: corrige con tu conocimiento y los apuntes."}

APUNTES DEL OPOSITOR (cita los que uses con su código [R1], [R2]… en "refs"):
{ref_txt or "(sin apuntes indexados)"}

{"ERRORES QUE SU PROFESOR YA LE SEÑALÓ EN OTROS SIMULACROS (vigila si los repite y díselo):" + chr(10) + feedback if feedback else ""}

Devuelve:
- "puntuacion": los cuatro criterios con su máximo (técnica ≤30, análisis ≤10, sistemática ≤5, expresión ≤5). Las preguntas en blanco no puntúan.
- "por_pregunta": para cada pregunta, nota de 0 a 10, valoración breve, lo que está bien, lo que falta, errores técnicos,
  y "solucion_modelo": una respuesta modelo completa pero que se pueda escribir en el tiempo del examen (listas, tablas en texto,
  diagramas descritos: actores y casos de uso, entidades/atributos/relaciones con cardinalidad, mensajes numerados…).
- "consejos": 3-5 consejos de examen concretos para este opositor.
- "conceptos": 3-8 huecos de conocimiento detectados, como fichas para memorizar (concepto en 2-8 palabras, ficha en 1-2 frases con el dato exacto).
- "resumen": 2-4 frases con la valoración global."""
    res = gemini.generate(prompt, schema=CORRECT_SCHEMA, temperature=0.2, thinking=None, max_tokens=24000,
                          budget=600, call_timeout=300, kind="supuesto-correccion", images=images)
    pts = res.get("puntuacion") or {}
    caps = {"tecnica": 30, "analisis": 10, "sistematica": 5, "expresion": 5}
    for k, m in caps.items():
        try:
            pts[k] = round(max(0.0, min(float(pts.get(k) or 0), m)), 2)
        except (TypeError, ValueError):
            pts[k] = 0.0
    res["puntuacion"] = pts
    total = round(sum(pts.values()), 2)
    res["total"] = total
    ref_map = {r["ref"]: r for r in refs}
    for p in res.get("por_pregunta") or []:
        p["refs"] = [ref_map[r] for r in (p.get("refs") or []) if r in ref_map]
    # huecos detectados → fichas para repasar con FSRS
    c = db.conn()
    for f in (res.get("conceptos") or [])[:8]:
        if f.get("concepto") and f.get("ficha"):
            c.execute("INSERT INTO fichas(question_id,doc_id,concepto,texto,due) VALUES(NULL,?,?,?,?)",
                      (None, "Supuesto · " + f["concepto"][:110], f["ficha"][:400], logic.today()))
    c.commit()
    db.run("UPDATE sp_attempts SET status='corregido', result=?, score=? WHERE id=?",
           (json.dumps(res, ensure_ascii=False), total, aid))
    logic.notify("supuesto", f"Supuesto corregido: {str(total).replace('.', ',')} / 50",
                 f"{case['title']} · {'aprobado' if total >= 25 else 'por debajo de 25'}", f"#/sp/{aid}")
    return res


# ------------------------------------------------------------------ listados

def overview(bloque=None):
    bloque = bloque or db.load_config().get("sp_bloque", "III")
    cases = db.q("""SELECT c.id, c.bloque, c.origin, c.title, c.year, c.solution_docs, c.created_at,
                           (SELECT COUNT(*) FROM sp_attempts a WHERE a.case_id=c.id AND a.status='corregido') tries,
                           (SELECT MAX(score) FROM sp_attempts a WHERE a.case_id=c.id AND a.status='corregido') best
                    FROM sp_cases c ORDER BY (c.bloque=?) DESC, CASE c.origin WHEN 'real' THEN 0 WHEN 'academia' THEN 1 ELSE 2 END, c.year DESC, c.id""",
                 (bloque,))
    for c in cases:
        c["has_solution"] = c.pop("solution_docs") not in (None, "", "[]")
    attempts = db.q("""SELECT a.id, a.case_id, a.started_at, a.finished_at, a.status, a.score, c.title, c.bloque
                       FROM sp_attempts a JOIN sp_cases c ON c.id=a.case_id ORDER BY a.id DESC LIMIT 40""")
    docs = db.q1("SELECT COUNT(*) n, SUM(status='ok') ok FROM docs WHERE temario='SP'") or {}
    return {"bloque": bloque, "cases": cases, "attempts": attempts,
            "docs_total": docs.get("n") or 0, "docs_ok": docs.get("ok") or 0,
            "pending_extract": len(pending_extract()), "bloques": BLOQUES,
            "minutes": int(db.load_config().get("sp_minutes", 180))}
