"""Las tres fuentes para revisar una pregunta: temario indexado, Internet e IA."""
import html
import json
import re
import unicodedata
import urllib.parse
import urllib.request

import db
import gemini

STOP = set("""de la que el en y a los del se las por un para con no una su al lo como mas pero sus le ya o este si porque esta
entre cuando muy sin sobre tambien me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante
ellos e esto antes algunos unos yo otro otras otra tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas
algo nosotros mi mis tu te ti tus ellas nosotras vosotros os mio mia mios mias tuyo tuya suyo suya nuestro nuestra vuestro
vuestra esos esas estoy estas esta estamos estan sera son ser es fue han ha he hace puede pueden siguiente siguientes cuales
correcta correcto incorrecta incorrecto afirmacion afirmaciones indique senale señale respecto segun dicho dicha ninguna
todas anteriores opcion respuesta verdadera falsa cierto cierta mediante través traves articulo""".split())

UA = "Mozilla/5.0 (X11; Linux aarch64) OpoTest/1.0"


def _ascii(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def keywords(text, limit=14):
    out, seen = [], set()
    for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9][\wÁÉÍÓÚÜÑáéíóúüñ./-]*", text or ""):
        w2 = _ascii(w).strip("./-")
        if len(w2) < 3 or w2 in STOP or w2.isdigit() and len(w2) < 2:
            continue
        if w2 in seen:
            continue
        seen.add(w2)
        out.append(w2)
    return out[:limit]


def effective_correct(qrow):
    return qrow.get("correct_override") or qrow["correct"]


def fts_query(terms):
    safe = [re.sub(r"[^a-z0-9]", "", t) for t in terms]
    safe = [t for t in safe if len(t) >= 3]
    return " OR ".join(f'"{t}"' for t in safe)


def search_temario(text, docs=None, limit=4):
    terms = keywords(text, 18)
    if not terms:
        return []
    qry = fts_query(terms)
    if not qry:
        return []
    sql = """SELECT doc_id, file_idx, page, snippet(pages_fts, 0, '[[', ']]', '…', 48) AS snip, bm25(pages_fts) AS score
             FROM pages_fts WHERE pages_fts MATCH ?"""
    args = [qry]
    if docs:
        sql += " AND doc_id IN (%s)" % ",".join("?" * len(docs))
        args += list(docs)
    sql += " ORDER BY score LIMIT ?"
    args.append(limit)
    try:
        rows = db.q(sql, args)
    except Exception:
        return []
    titles = {d["id"]: d for d in db.q("SELECT id, title, temario, bloque, num FROM docs")}
    for r in rows:
        d = titles.get(r["doc_id"], {})
        r["title"] = d.get("title", r["doc_id"])
        r["temario"] = d.get("temario")
        r["num"] = d.get("num")
        r["bloque"] = d.get("bloque")
    return rows


def temario_for_question(qrow):
    ans = qrow.get(effective_correct(qrow)) or ""
    text = f"{qrow['text']} {ans}"
    related = [d for d in (qrow.get("a1_doc"), qrow.get("a2_doc"), qrow.get("a2_doc2")) if d]
    hits = search_temario(text, related, 3) if related else []
    if len(hits) < 3:
        seen = {(h["doc_id"], h["page"]) for h in hits}
        for h in search_temario(text, None, 5):
            if (h["doc_id"], h["page"]) not in seen:
                hits.append(h)
            if len(hits) >= 4:
                break
    return {"hits": hits, "indexed_pages": db.scalar("SELECT COUNT(*) FROM pages") or 0}


def _get(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def ddg(query, n=5):
    body = urllib.parse.urlencode({"q": query, "kl": "es-es"}).encode()
    page = _get("https://html.duckduckgo.com/html/", data=body)
    res = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'(?:class="result__snippet"[^>]*>(.*?)</a>)?', page, re.S):
        href = html.unescape(m.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
        if "duckduckgo.com/y.js" in href:
            continue
        res.append({"title": _strip(m.group(2)), "url": href, "snippet": _strip(m.group(3))})
        if len(res) >= n:
            break
    return res


def wikipedia(query, n=2):
    url = "https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": n, "utf8": 1})
    data = json.loads(_get(url))
    out = []
    for s in data.get("query", {}).get("search", []):
        title = s["title"]
        try:
            summ = json.loads(_get("https://es.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)))
            extract = summ.get("extract", "")
            link = summ.get("content_urls", {}).get("desktop", {}).get("page")
        except Exception:
            extract, link = _strip(s.get("snippet")), None
        out.append({"title": title + " — Wikipedia", "url": link or "https://es.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                    "snippet": extract[:600]})
    return out


def internet_for_question(qrow):
    ans = qrow.get(effective_correct(qrow)) or ""
    base = " ".join(keywords(qrow["text"], 9))
    q_full = f"{base} {' '.join(keywords(ans, 5))}".strip()
    results, errors = [], []
    try:
        results += ddg(q_full, 5)
    except Exception as e:
        errors.append(f"Buscador: {e}")
    try:
        results += wikipedia(base, 2)
    except Exception as e:
        errors.append(f"Wikipedia: {e}")
    return {"query": q_full, "results": results, "errors": errors,
            "search_url": "https://duckduckgo.com/?q=" + urllib.parse.quote(qrow["text"][:300])}


IA_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "respuesta_ia": {"type": "STRING", "enum": ["a", "b", "c", "d"]},
        "coincide": {"type": "BOOLEAN"},
        "explicacion": {"type": "STRING"},
        "por_que_no": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "letra": {"type": "STRING"}, "motivo": {"type": "STRING"}}, "required": ["letra", "motivo"]}},
        "referencia": {"type": "STRING"},
        "truco": {"type": "STRING"},
    },
    "required": ["respuesta_ia", "coincide", "explicacion"],
}


def ia_for_question(qrow, chosen=None):
    corr = effective_correct(qrow)
    tem = temario_for_question(qrow)["hits"][:3]
    ctx = "\n\n".join(f"[{h['title']} · pág. {h['page']}]\n{h['snip'].replace('[[', '').replace(']]', '')}" for h in tem)
    opts = "\n".join(f"{k}) {qrow.get(k)}" for k in "abcd" if qrow.get(k))
    prompt = f"""Eres preparador de oposiciones TIC de la Administración española (cuerpos A1 CSSTIC, A2 GSI y C1 TAI).
Explica esta pregunta tipo test a un opositor.

Pregunta: {qrow['text']}
{opts}

Respuesta marcada como correcta en el banco: {corr}
{('El opositor respondió: ' + chosen) if chosen and chosen != corr else ''}
Fuente/comentario del banco: {qrow.get('comments') or '-'}

Fragmentos del temario que pueden ayudar:
{ctx or '(no hay fragmentos)'}

Indica qué opción crees correcta tú (respuesta_ia) y si coincide con la del banco. En "explicacion" (máx. 120 palabras)
razona la respuesta con la norma, artículo o concepto exacto. En "por_que_no" explica brevemente por qué fallan las otras.
En "referencia" cita la norma o fuente (p. ej. "Art. 53 Ley 39/2015"). En "truco" da una regla mnemotécnica corta si existe.
Si el banco parece estar equivocado o la normativa ha cambiado, dilo claramente."""
    res = gemini.generate(prompt, schema=IA_SCHEMA, temperature=0.2)
    res["respuesta_banco"] = corr
    return res


def get_source(qid, which, chosen=None, refresh=False):
    qrow = db.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not qrow:
        raise KeyError("pregunta no encontrada")
    if which == "temario":       # el índice crece mientras avanza el OCR: no se cachea
        return temario_for_question(qrow)
    if not refresh:
        c = db.scalar("SELECT content FROM sources_cache WHERE question_id=? AND source=?", (qid, which))
        if c:
            out = json.loads(c)
            out["cached"] = True
            return out
    if which == "internet":
        out = internet_for_question(qrow)
        if not out["results"]:
            return out
    elif which == "ia":
        out = ia_for_question(qrow, chosen)
    else:
        raise KeyError(which)
    db.run("INSERT OR REPLACE INTO sources_cache(question_id,source,content) VALUES(?,?,?)",
           (qid, which, json.dumps(out, ensure_ascii=False)))
    return out
