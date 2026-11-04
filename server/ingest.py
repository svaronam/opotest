"""Indexa el temario: extrae el texto de cada PDF (OCR si es escaneado) y lo
guarda por páginas en SQLite con búsqueda de texto completo.

    python3 ingest.py            # procesa lo pendiente y termina
    python3 ingest.py --watch    # se queda vigilando por si añades PDFs
    python3 ingest.py --doc A2-IV-02   # reprocesa un tema concreto

Es reanudable: si se corta, sigue por la última página guardada.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import db

MIN_CHARS = 80          # menos letras que esto en una página => se considera escaneada
OCR_DPI = 170


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def tesseract_lang():
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20).stdout
        return "spa" if re.search(r"^spa$", out, re.M) else "eng"
    except Exception:
        return None


def pdf_pages(path):
    out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=120).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def text_layer(path):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                         capture_output=True, timeout=1800).stdout.decode("utf-8", "ignore")
    return out.split("\f")


def letters(s):
    return len(re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", s or ""))


def ocr_page(path, page, lang):
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "p")
        subprocess.run(["pdftoppm", "-r", str(OCR_DPI), "-gray", "-f", str(page), "-l", str(page), "-png", path, base],
                       capture_output=True, timeout=600)
        imgs = [f for f in os.listdir(td) if f.endswith(".png")]
        if not imgs:
            return ""
        r = subprocess.run(["tesseract", os.path.join(td, imgs[0]), "-", "-l", lang, "--psm", "3"],
                           capture_output=True, timeout=900)
        return r.stdout.decode("utf-8", "ignore")


def clean(t):
    t = t.replace("\r", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def save_page(doc_id, fidx, page, text, ocr):
    c = db.conn()
    c.execute("INSERT OR REPLACE INTO pages(doc_id,file_idx,page,text,ocr) VALUES(?,?,?,?,?)",
              (doc_id, fidx, page, text, ocr))
    c.execute("DELETE FROM pages_fts WHERE doc_id=? AND file_idx=? AND page=?", (doc_id, fidx, page))
    if text:
        c.execute("INSERT INTO pages_fts(text,doc_id,file_idx,page) VALUES(?,?,?,?)", (text, doc_id, fidx, page))
    c.commit()


def process_doc(doc, lang, force=False):
    files = json.loads(doc["files"])
    root = os.path.join(db.TEMARIO_DIR, doc["temario"])
    path = os.path.join(root, files[0])
    if not os.path.exists(path):
        db.run("UPDATE docs SET status='sin_pdf' WHERE id=?", (doc["id"],))
        return
    if force:
        db.run("DELETE FROM pages WHERE doc_id=?", (doc["id"],))
        db.run("DELETE FROM pages_fts WHERE doc_id=?", (doc["id"],))
    n = pdf_pages(path)
    db.run("UPDATE docs SET pages=?, status='procesando', error=NULL WHERE id=?", (n, doc["id"]))
    done = {r["page"] for r in db.q("SELECT page FROM pages WHERE doc_id=? AND file_idx=0", (doc["id"],))}
    if len(done) >= n and n:
        db.run("UPDATE docs SET status='ok', progress=100 WHERE id=?", (doc["id"],))
        return
    layer = text_layer(path)
    need_ocr = 0
    for i in range(1, n + 1):
        if i in done:
            continue
        t = layer[i - 1] if i - 1 < len(layer) else ""
        ocr = 0
        if letters(t) < MIN_CHARS:
            if lang:
                need_ocr += 1
                db.run("UPDATE docs SET status='ocr' WHERE id=?", (doc["id"],))
                try:
                    t = ocr_page(path, i, lang)
                    ocr = 1
                except Exception as e:  # una página mala no para el tema
                    log("  error OCR pág", i, e)
                    t = ""
        save_page(doc["id"], 0, i, clean(t), ocr)
        db.run("UPDATE docs SET progress=? WHERE id=?", (int(i * 100 / n), doc["id"]))
        if ocr and i % 10 == 0:
            log(f"  {doc['id']}: OCR {i}/{n}")
    db.run("UPDATE docs SET status='ok', progress=100 WHERE id=?", (doc["id"],))
    log(f"{doc['id']} listo ({n} págs, {need_ocr} con OCR)")


def pending_docs():
    # primero el A1 (texto directo, rápido), luego A2 por bloques; los resúmenes manuscritos no se indexan
    return db.q("""SELECT * FROM docs WHERE status NOT IN ('ok') AND kind IN ('tema','extra')
                   ORDER BY CASE temario WHEN 'A1' THEN 0 ELSE 1 END, kind DESC, bloque, num""")


def run_once(only=None, force=False):
    db.init()
    lang = tesseract_lang()
    if not lang:
        log("AVISO: tesseract no está instalado; las páginas escaneadas quedarán sin texto")
    docs = db.q("SELECT * FROM docs WHERE id=?", (only,)) if only else pending_docs()
    for d in docs:
        try:
            log("Procesando", d["id"], d["title"][:60])
            process_doc(d, lang, force=force)
        except Exception as e:
            db.run("UPDATE docs SET status='error', error=? WHERE id=?", (str(e)[:300], d["id"]))
            log("ERROR", d["id"], e)


if __name__ == "__main__":
    try:
        os.nice(15)
    except Exception:
        pass
    args = sys.argv[1:]
    if "--doc" in args:
        run_once(args[args.index("--doc") + 1], force=True)
    elif "--watch" in args:
        while True:
            db.init()
            db.run("UPDATE docs SET status='pendiente' WHERE status='sin_pdf'")
            run_once()
            time.sleep(600)
    else:
        run_once()
