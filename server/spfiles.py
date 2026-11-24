"""Carpeta de supuestos prácticos (temario/SP): la registra como documentos y extrae el texto de los
archivos que no son PDF (Word, PowerPoint, texto). Los PDF siguen el camino normal de ingest (con OCR).

Clasificación por ruta y nombre:
  sp-real      enunciados reales del tribunal (EXAMENES REALES, SUPUESTOS ANTIGUOS, INAP 2019…)
  sp-enun      enunciados de academias y simulacros
  sp-sol       soluciones, esquemas y propuestas de solución
  sp-feedback  correcciones del profesor a tus simulacros
  sp-teoria    apuntes, guías y plantillas de las sesiones
  sp-otro      el resto
"""
import hashlib
import json
import os
import re
import unicodedata
import zipfile

import db

SP = "SP"
TEXT_EXT = {".docx", ".pptx", ".ppsx", ".txt"}
OK_EXT = TEXT_EXT | {".pdf"}
SKIP_DIRS = ("video", "grabacion")         # vídeos y grabaciones no se indexan
PAGE_CHARS = 3500


def root():
    return os.path.join(db.TEMARIO_DIR, SP)


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def bloque_for(rel):
    p = fold(rel)
    if re.search(r"\bbiv\b|bloque[ _-]*iv\b|bloque[ _-]*4\b|\bbl4\b|-biv|biv-|_biv", p):
        return "IV"
    if re.search(r"\biii\b|\bbiii\b|bloque[ _-]*iii\b|bloque[ _-]*3\b|\bbl3\b|-biii|biii-|_biii", p):
        return "III"
    return ""


def kind_for(rel):
    p = fold(rel)
    name = fold(os.path.basename(rel))
    if "chat" in name or "conversaciones" in name or "leeme" in name or "log gsi" in name:
        return "sp-otro"
    if "feedback" in name or "correccion" in name:
        return "sp-feedback"
    if any(k in name for k in ("solucion", "esquema", "posible", "propuesta", "resuelto", "soluciones")):
        return "sp-sol"
    if "examenes reales" in p or "supuestos antiguos" in p or "inap 2019" in p:
        return "sp-real"
    if p.startswith("sesiones teoria"):
        return "sp-teoria"
    if any(k in name for k in ("enunciado", "supuesto", "simulacro", "examen", "ejer")) or "supuesto" in p:
        return "sp-enun"
    return "sp-otro"


def doc_id(rel):
    return "SP-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]


def _extract_zips(base):
    """Descomprime cada .zip junto a él (carpeta «nombre__zip») una sola vez."""
    for dp, dns, fns in os.walk(base):
        for fn in fns:
            if not fn.lower().endswith(".zip"):
                continue
            dest = os.path.join(dp, fn[:-4] + "__zip")
            if os.path.isdir(dest):
                continue
            try:
                with zipfile.ZipFile(os.path.join(dp, fn)) as z:
                    real = os.path.realpath(dest)
                    for m in z.infolist():
                        name = m.filename
                        if m.flag_bits & 0x800 == 0:          # nombres de Windows antiguos
                            try:
                                name = name.encode("cp437").decode("cp850")
                            except Exception:
                                pass
                        target = os.path.realpath(os.path.join(dest, name))
                        if not target.startswith(real + os.sep) or name.endswith("/"):
                            continue
                        ext = os.path.splitext(name)[1].lower()
                        if ext not in OK_EXT and ext != ".zip":
                            continue
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with z.open(m) as src, open(target, "wb") as out:
                            out.write(src.read())
            except Exception as e:
                os.makedirs(dest, exist_ok=True)
                print("zip ilegible", fn, e)


def scan():
    """Registra en `docs` los archivos útiles de la carpeta SP. Devuelve cuántos hay."""
    base = root()
    if not os.path.isdir(base):
        return 0
    _extract_zips(base)
    seen = 0
    c = db.conn()
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if not any(k in fold(d) for k in SKIP_DIRS)]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in OK_EXT or fn.startswith("~$"):
                continue
            full = os.path.join(dp, fn)
            if os.path.getsize(full) < 200:
                continue
            rel = os.path.relpath(full, base)
            title = os.path.splitext(fn)[0].strip(" _-")
            parent = os.path.basename(os.path.dirname(rel)).replace("__zip", "")
            c.execute("""INSERT INTO docs(id,temario,bloque,num,title,kind,files,resumen) VALUES(?,?,?,?,?,?,?,NULL)
                         ON CONFLICT(id) DO UPDATE SET bloque=excluded.bloque, title=excluded.title, kind=excluded.kind""",
                      (doc_id(rel), SP, bloque_for(rel), None, f"{title} · {parent}" if parent and parent != "." else title,
                       kind_for(rel), json.dumps([rel], ensure_ascii=False)))
            seen += 1
    c.commit()
    return seen


# ------------------------------------------------------------------ texto de Word / PowerPoint / txt

def _xml_text(xml, para_tag):
    xml = re.sub(rf"</{para_tag}>", "\n", xml)
    xml = re.sub(r"<w:tab/>|<a:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>|<a:br/>", "\n", xml)
    t = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        t = t.replace(a, b)
    return t


def file_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        raw = open(path, "rb").read()
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
    with zipfile.ZipFile(path) as z:
        if ext == ".docx":
            parts = [n for n in z.namelist() if re.match(r"word/(document|footnotes|endnotes)\.xml$", n)]
            return "\n".join(_xml_text(z.read(n).decode("utf-8", "ignore"), "w:p") for n in parts)
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        return "\n\n".join(f"[Diapositiva {i + 1}]\n" + _xml_text(z.read(n).decode("utf-8", "ignore"), "a:p")
                           for i, n in enumerate(slides))


def split_pages(text):
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r", "")).strip()
    pages, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) > PAGE_CHARS and cur:
            pages.append(cur)
            cur = ""
        cur += (("\n\n" if cur else "") + para)
    if cur:
        pages.append(cur)
    return pages or [""]
