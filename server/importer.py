"""Carga el catálogo de temas y las preguntas de PreparaTIC en la base de datos.
Se puede ejecutar varias veces: no duplica nada.
    python3 importer.py
"""
import hashlib
import json
import os
import re
import unicodedata

import db

DATA = os.path.join(db.BASE, "data")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def qhash(text, answers):
    return hashlib.sha1((norm(text) + "|" + "|".join(sorted(norm(a) for a in answers))).encode()).hexdigest()


def escala_de(comment, is_exam):
    """Deduce la escala del examen de origen. Las preguntas propias de PreparaTIC
    están hechas para el Cuerpo Superior (A1)."""
    m = (comment or "").upper()
    if not is_exam:
        return "A1"
    if re.search(r"\bC1\b|AUXILIAR|\bTAI\b|OPERADOR", m):
        return "C1"
    if re.search(r"\bA2\b|\bGSI\b|GESTI[OÓ]N DE SISTEMAS|GESTI[OÓ]N DE INFORM", m):
        return "A2"
    return "A1"


# Temas del A2 que comparten contenido con otro: por tema PreparaTIC o por palabras clave
A2_SECOND_TOPIC = {59: "A2-IV-01", 60: "A2-IV-01", 61: "A2-IV-01", 62: "A2-IV-01", 63: "A2-IV-02", 64: "A2-IV-02",
                   118: "A2-IV-09", 117: "A2-IV-09", 97: "A2-II-07", 132: "A2-II-07"}
A2_KEYWORDS = [
    (r"docker|kubernetes|contenedor|microservicio|openshift|podman|\bhelm\b|\bk8s\b|service mesh|istio", "A2-II-07"),
    (r"\bsnmp\b|\bmib\b|\bnetflow\b|\brmon\b|monitorizaci[oó]n de (la )?red", "A2-IV-09"),
    (r"\bdba\b|administrador de (la )?base|tablespace|backup de (la )?base|oracle rman|\brman\b", "A2-IV-02"),
    (r"\bsystemd\b|\bcron(tab)?\b|\bchmod\b|active directory|\bgpo\b|powershell|\bsudo\b|\bfstab\b", "A2-IV-01"),
]


def second_a2(topic, text, primary):
    for rx, doc in A2_KEYWORDS:
        if doc != primary and re.search(rx, text, re.I):
            return doc
    d = A2_SECOND_TOPIC.get(topic)
    return d if d != primary else None


def load_catalog():
    return json.load(open(os.path.join(DATA, "catalogo.json"), encoding="utf-8"))


def import_docs(cat):
    for d in cat["docs"]:
        db.run(
            """INSERT INTO docs(id,temario,bloque,num,title,kind,files,resumen)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET temario=excluded.temario,bloque=excluded.bloque,num=excluded.num,
               title=excluded.title,kind=excluded.kind,files=excluded.files,resumen=excluded.resumen""",
            (d["id"], d["temario"], d["bloque"], d["num"], d["title"], d["kind"],
             json.dumps(d["files"], ensure_ascii=False), d.get("resumen")),
        )


def import_preparatic(cat):
    path = os.path.join(DATA, "preguntas_preparatic.json")
    if not os.path.exists(path):
        # El banco de preguntas no se distribuye con el repositorio (no es contenido propio).
        print(f"No encuentro {path}: se omite la importación del banco de preguntas.")
        return 0
    data = json.load(open(path, encoding="utf-8"))
    p2a1, p2a2 = cat["p2a1"], cat["p2a2"]
    c = db.conn()
    n_new = 0
    for r in data["rows"]:
        ext_id, block, topic, text, answers, comments, year, is_exam, exams, _tp = r
        ans = {a[0]: a[1] for a in answers}
        correct = [a[0] for a in answers if a[2]]
        if len(ans) < 2 or not correct:
            continue
        h = qhash(text, ans.values())
        a1n = p2a1.get(str(topic))
        cur = c.execute(
            """INSERT OR IGNORE INTO questions(origin,ext_id,text,a,b,c,d,correct,comments,year,is_exam,exams,
               block,ptopic,a1_doc,a2_doc,escala,hash) VALUES('preparatic',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ext_id, text, ans.get("a"), ans.get("b"), ans.get("c"), ans.get("d"), correct[0], comments, year,
             1 if is_exam else 0, "; ".join(exams), block, int(topic) if str(topic).isdigit() else None,
             ("A1-%03d" % a1n) if a1n else None, p2a2.get(str(topic)), escala_de(comments, is_exam), h),
        )
        n_new += cur.rowcount
    c.commit()
    # (re)calcula la segunda equivalencia para todo el banco
    rows = db.q("SELECT id, ptopic, text, a, b, c, d, a2_doc FROM questions WHERE origin='preparatic'")
    c.executemany("UPDATE questions SET a2_doc2=? WHERE id=?",
                  [(second_a2(r["ptopic"], " ".join(filter(None, (r["text"], r["a"], r["b"], r["c"], r["d"]))), r["a2_doc"]), r["id"]) for r in rows])
    c.commit()
    return n_new


def main():
    db.init()
    cat = load_catalog()
    import_docs(cat)
    n = import_preparatic(cat)
    total = db.scalar("SELECT COUNT(*) FROM questions")
    print(f"Temas: {db.scalar('SELECT COUNT(*) FROM docs')} · preguntas nuevas importadas: {n} · total: {total}")
    for row in db.q("SELECT escala, COUNT(*) n FROM questions GROUP BY escala"):
        print("  escala", row["escala"], row["n"])


if __name__ == "__main__":
    main()
