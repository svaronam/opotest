"""Las tres fuentes para revisar una pregunta: temario indexado, Internet e IA."""
import html
import math
import threading
import time
import json
import re
import unicodedata
import urllib.error
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

UA_BROWSER = "Mozilla/5.0 (X11; Linux aarch64; rv:128.0) Gecko/20100101 Firefox/128.0"
# Wikimedia pide un User-Agent que identifique la app y un contacto; con uno genérico devuelve 429
UA_WIKI = "OpoTest/1.1 (app personal de estudio; https://github.com/svaronam) python-urllib"
UA = UA_BROWSER


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


# ------------------------------------------------------------------ búsqueda de la respuesta en el temario

NEGATIVE = re.compile(r"\b(no|incorrect[ao]s?|falsa?s?|excepto|salvo|err[oó]ne[ao]s?)\b", re.I)
WINDOW = 420          # caracteres de cada fragmento


def _fold_char(ch):
    """Quita tildes conservando la longitud (para poder recortar el texto original por posiciones)."""
    d = unicodedata.normalize("NFD", ch)
    return (d[0] if d else ch).lower()


def _fold(text):
    return "".join(_fold_char(c) for c in text)


def _stem(w):
    """Raíz aproximada en español: 'estructurado' -> 'estructura', 'modelos' -> 'model'."""
    w = re.sub(r"[^a-z0-9]", "", _ascii(w))
    if len(w) <= 4 or w.isdigit():
        return w
    for suf in ("aciones", "ación", "acion", "amente", "mente", "idades", "idad", "ados", "idos", "ado", "ido",
                "ales", "es", "os", "as", "al", "o", "a", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: len(w) - len(suf)]
    return w


SHORT_OK = re.compile(r"^(?:[ivxlcdm]{1,5}|\d{1,4}|[a-z]?\d+[a-z]?)$")   # VI, 53, 3FN, 802…


def _terms(text, limit=12, short=False):
    out = []
    for k in keywords(text, limit):
        s = _stem(k)
        if len(s) >= 3 and s not in out:
            out.append(s)
    if short:   # en la respuesta los números romanos, cifras y siglas cortas son lo más importante
        for w in re.findall(r"[A-Za-z0-9]+", text or ""):
            lw = w.lower()
            if (SHORT_OK.match(lw) or (w.isupper() and 2 <= len(w) <= 3)) and lw not in out and lw not in STOP:
                out.append(lw)
    return out


_df_cache = {}


def _idf(term):
    """Cuanto más rara es una palabra en el temario, más pesa."""
    if term not in _df_cache:
        n = db.scalar("SELECT COUNT(*) FROM pages") or 1
        q = f'"{term}"' if len(term) < 4 else f"{term}*"
        try:
            df = db.scalar("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?", (q,)) or 0
        except Exception:
            df = 0
        _df_cache[term] = max(0.35, min(2.5, math.log((n + 1) / (df + 1)) / 3))
    return _df_cache[term]


def _weighted_terms(qrow):
    corr = effective_correct(qrow)
    negative = bool(NEGATIVE.search(qrow["text"]))
    w = {}

    def add(text, weight, limit=12, short=False):
        for t in _terms(text, limit, short):
            w[t] = max(w.get(t, 0), weight * _idf(t))

    add(qrow["text"], 1.0, 14)
    for k in "abcd":
        if qrow.get(k) and k != corr:
            # en preguntas negativas las demás opciones SÍ están en el temario y ayudan a encontrar el párrafo
            add(qrow[k], 1.5 if negative else 0.3, 6, short=negative)
    add(qrow.get(corr) or "", 4.0, 8, short=True)
    return w, corr, negative


def _term_re(t):
    if len(t) < 4 or SHORT_OK.match(t):
        return r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
    return r"(?<![a-z0-9])" + re.escape(t) + r"[a-z0-9]*"


def _best_window(text, weights, answer_terms):
    """Busca en la página la ventana con más peso, preferiblemente la que contiene la respuesta."""
    folded = _fold(text)
    occ = []        # (posición, término)
    for t in weights:
        for m in re.finditer(_term_re(t), folded):
            occ.append((m.start(), m.end(), t))
    if not occ:
        return None
    occ.sort()
    best = None
    anchors = [o for o in occ if o[2] in answer_terms] or occ
    for a_start, a_end, _ in anchors:
        lo = max(0, a_start - WINDOW // 2)
        hi = min(len(text), lo + WINDOW)
        lo = max(0, hi - WINDOW)
        found = {t for s, e, t in occ if s >= lo and e <= hi}
        score = sum(weights[t] for t in found)
        if best is None or score > best[0]:
            best = (score, lo, hi, found)
    score, lo, hi, found = best
    # ajusta a límites de palabra y de línea para que el fragmento se lea bien
    lo0, hi0 = lo, hi
    while lo > 0 and text[lo - 1] not in "\n." and lo > lo0 - 120:
        lo -= 1
    while hi < len(text) and text[hi] != "\n" and hi < hi0 + 120:
        hi += 1
    frag = text[lo:hi]
    # marca: {{respuesta}} y [[resto de términos]]
    ffold = folded[lo:hi]
    spans = []
    for t in found:
        for m in re.finditer(_term_re(t), ffold):
            spans.append((m.start(), m.end(), t in answer_terms))
    spans.sort()
    out, pos = [], 0
    for s, e, is_ans in spans:
        if s < pos:
            continue
        out.append(frag[pos:s])
        out.append(("{{%s}}" if is_ans else "[[%s]]") % frag[s:e])
        pos = e
    out.append(frag[pos:])
    snip = "".join(out).strip()
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    has_answer = any(t in answer_terms for t in found)
    total_ans = sum(weights.get(t, 0) for t in answer_terms) or 1
    coverage = sum(weights.get(t, 0) for t in found if t in answer_terms) / total_ans
    return {"snip": prefix + snip + suffix, "wscore": score, "has_answer": has_answer, "coverage": coverage}


def temario_for_question(qrow, limit=3):
    weights, corr, negative = _weighted_terms(qrow)
    answer_terms = set(_terms(qrow.get(corr) or "", 8, short=True)) if not negative else set()
    if negative:
        # en "¿cuál NO es…?" el párrafo útil es el que enumera las correctas (las otras opciones)
        answer_terms = {t for k in "abcd" if qrow.get(k) and k != corr for t in _terms(qrow[k], 6, short=True)}
    if not weights:
        return {"hits": [], "indexed_pages": db.scalar("SELECT COUNT(*) FROM pages") or 0}
    related = [d for d in (qrow.get("a1_doc"), qrow.get("a2_doc"), qrow.get("a2_doc2")) if d]
    prefix_q = " OR ".join((f'"{t}"' if len(t) < 4 else f"{t}*") for t in weights if re.fullmatch(r"[a-z0-9]+", t))
    cand = []
    for scope in ([related] if related else []) + [None]:
        sql = "SELECT doc_id, file_idx, page, bm25(pages_fts) AS bm FROM pages_fts WHERE pages_fts MATCH ?"
        args = [prefix_q]
        if scope:
            sql += " AND doc_id IN (%s)" % ",".join("?" * len(scope))
            args += scope
        sql += " ORDER BY bm LIMIT 40"
        try:
            cand += [dict(r, related=bool(scope)) for r in db.q(sql, args)]
        except Exception:
            pass
        if len(cand) >= 15:
            break
    seen, scored = set(), []
    for c in cand:
        key = (c["doc_id"], c["page"])
        if key in seen:
            continue
        seen.add(key)
        text = db.scalar("SELECT text FROM pages WHERE doc_id=? AND file_idx=? AND page=?", (c["doc_id"], c["file_idx"], c["page"]))
        if not text:
            continue
        win = _best_window(text, weights, answer_terms)
        if not win:
            continue
        total = win["wscore"] + 4 * win["coverage"] + (1.5 if c["related"] else 0) - 0.05 * c["bm"]
        scored.append((total, c, win))
    scored.sort(key=lambda x: -x[0])
    titles = {d["id"]: d for d in db.q("SELECT id, title, temario, bloque, num FROM docs")}
    hits, per_doc = [], {}
    for total, c, win in scored:
        if per_doc.get(c["doc_id"], 0) >= 2:      # variedad: como mucho 2 páginas del mismo tema
            continue
        per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
        d = titles.get(c["doc_id"], {})
        hits.append({"doc_id": c["doc_id"], "file_idx": c["file_idx"], "page": c["page"], "snip": win["snip"],
                     "has_answer": win["coverage"] >= 0.6, "title": d.get("title", c["doc_id"]), "temario": d.get("temario"),
                     "num": d.get("num"), "bloque": d.get("bloque")})
        if len(hits) >= limit:
            break
    return {"hits": hits, "indexed_pages": db.scalar("SELECT COUNT(*) FROM pages") or 0, "negative": negative}


class SearchError(Exception):
    pass


def _get(url, data=None, timeout=15, headers=None):
    h = {"User-Agent": UA_BROWSER, "Accept-Language": "es-ES,es;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def _strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# --- pausas por buscador (si uno nos limita, se deja descansar en vez de insistir)

def _paused(engine):
    try:
        return float(db.kv_get(f"search_pause_{engine}", 0) or 0) > time.time()
    except Exception:
        return False


def _pause(engine, secs, why=""):
    db.kv_set(f"search_pause_{engine}", time.time() + secs)
    db.kv_set(f"search_pause_why_{engine}", why)


def search_status():
    out = {}
    for e in ("tavily", "duckduckgo", "wikipedia"):
        until = float(db.kv_get(f"search_pause_{e}", 0) or 0)
        out[e] = {"paused_until": time.strftime("%H:%M", time.localtime(until)) if until > time.time() else None,
                  "why": db.kv_get(f"search_pause_why_{e}", "")}
    out["tavily_month"] = tavily_used()
    out["tavily_key"] = bool(db.load_config().get("tavily_api_key"))
    return out


# --- Tavily: API de búsqueda con 1.000 consultas gratis al mes (sin tarjeta)

def tavily_used():
    return int(db.kv_get("tavily_" + time.strftime("%Y-%m"), 0) or 0)


def tavily(query, n=5):
    key = (db.load_config().get("tavily_api_key") or "").strip()
    if not key:
        raise SearchError("sin clave")
    body = json.dumps({"query": query, "search_depth": "basic", "max_results": n, "include_answer": False}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    db.kv_set("tavily_" + time.strftime("%Y-%m"), tavily_used() + 1)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (429, 432, 433):
            _pause("tavily", 6 * 3600, "límite de consultas alcanzado")
        elif e.code in (401, 403):
            _pause("tavily", 24 * 3600, "la clave de Tavily no es válida")
        raise SearchError(f"Tavily HTTP {e.code}")
    return [{"title": x.get("title") or x.get("url"), "url": x.get("url"), "snippet": (x.get("content") or "")[:500],
             "engine": "Tavily"} for x in data.get("results", [])[:n] if x.get("url")]


# --- DuckDuckGo (versión HTML): sin clave, pero bloquea si detecta muchas consultas automáticas

def ddg(query, n=5):
    status, page = _get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "es-es"}))
    if status == 202 or "anomaly" in page[:20000] or "challenge-form" in page:
        _pause("duckduckgo", 4 * 3600, "DuckDuckGo ha bloqueado temporalmente las búsquedas automáticas")
        raise SearchError("DuckDuckGo bloquea las búsquedas automáticas ahora mismo")
    res = []
    for block in re.split(r'<div class="result results_links', page)[1:]:
        if "result--ad" in block[:200]:
            continue
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        href = html.unescape(a.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/y.js" in href:
            continue
        res.append({"title": _strip(a.group(2)), "url": href, "snippet": _strip(sn.group(1) if sn else ""), "engine": "DuckDuckGo"})
        if len(res) >= n:
            break
    return res


# --- Wikipedia: búsqueda y resumen en UNA sola petición

def wikipedia(query, n=2):
    url = "https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", "formatversion": 2, "generator": "search", "gsrsearch": query,
         "gsrlimit": n, "prop": "extracts|info", "exintro": 1, "explaintext": 1, "exchars": 600, "inprop": "url",
         "maxlag": 5})
    try:
        _, body = _get(url, headers={"User-Agent": UA_WIKI, "Api-User-Agent": UA_WIKI})
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry = int(e.headers.get("Retry-After") or 600)
            _pause("wikipedia", max(retry, 300), "Wikipedia pide esperar (demasiadas consultas)")
        raise SearchError(f"Wikipedia HTTP {e.code}")
    pages = sorted(json.loads(body).get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    return [{"title": p["title"] + " — Wikipedia", "url": p.get("fullurl") or "https://es.wikipedia.org/wiki/" +
             urllib.parse.quote(p["title"].replace(" ", "_")), "snippet": (p.get("extract") or "")[:600], "engine": "Wikipedia"}
            for p in pages]


GENERIC = set("""considerar considerarse mayoria solucion soluciones problema problemas permite permiten siguiente siguientes uso usos
usar usarse utilizar utiliza utilizan conjunto especifico especifica especificos generar genera distintas distintos diferentes
opciones opcion dispone disponer ofrecer ofrece caso casos encarga encargar puede pueden debe deben dicha dicho cual cuales cierto
cierta ciertas ciertos tipo tipos forma formas manera parte partes cada mismo misma mismas mismos tambien aunque entre sobre
segun hace hacer tiene tienen tener realizar realiza permite indique senale afirmacion afirmaciones verdadera falsa correcta
incorrecta respecto referente relacion relativo relativa principal principales general generales importante nombre denomina
denominada denominado llama llamado llamada existe existen sistema sistemas solo unicamente siempre nunca correcto incorrecto
posible posibles nueva nuevo nuevos nuevas mayor menor numero aplicacion gestion""".split())


def _ranked_terms(text, n):
    """Las palabras más distintivas primero (siglas y términos técnicos; fuera las genéricas)."""
    acr = [w.lower() for w in re.findall(r"\b[A-Z][A-Z0-9]{1,8}\b", text or "")]
    words = [w for w in keywords(text, 24) if w not in GENERIC]
    words = list(dict.fromkeys(acr + words))
    try:
        words.sort(key=lambda w: (w not in acr, -_idf(_stem(w))))
    except Exception:
        pass
    return words[:n]


def _answer_core(ans):
    """Lo esencial de la respuesta: siglas y términos técnicos ('TLB: Translation Lookaside Buffer.' -> 'TLB Translation Lookaside Buffer')."""
    if re.search(r"\b(todas|ninguna|ambas|anteriores|mencionadas|correctas|incorrectas|verdaderas|falsas)\b", ans or "", re.I) \
            or re.fullmatch(r"\s*(s[ií]|no|verdadero|falso)\.?\s*", ans or "", re.I):
        return ""                      # respuesta genérica: no sirve para buscar
    a = re.sub(r"[.;:,()\[\]\"']", " ", ans or "")
    words = [w for w in a.split() if w]
    acr = [w for w in words if re.fullmatch(r"[A-Z0-9][A-Z0-9/\-.]{1,9}", w)]
    rest = [w for w in keywords(ans, 8) if w.upper() not in acr]
    return " ".join(list(dict.fromkeys(acr + rest))[:5])


def build_queries(qrow):
    corr = effective_correct(qrow)
    ans = qrow.get(corr) or ""
    neg = bool(NEGATIVE.search(qrow["text"]))
    q_terms = _ranked_terms(qrow["text"], 6)
    a_core = "" if neg else _answer_core(ans)
    main = " ".join(dict.fromkeys(q_terms + ([] if neg else a_core.lower().split()[:3])))
    short = " ".join(q_terms[:4])
    return main, short, a_core, q_terms


def _relevant(res, ans_terms, q_terms):
    """Descarta resultados sin relación: deben mencionar la respuesta, o al menos 2 palabras clave de la pregunta."""
    out = []
    for r in res:
        blob = _ascii((r.get("title") or "") + " " + (r.get("snippet") or ""))
        hit = lambda m: re.search(r"(?<![a-z0-9])" + re.escape(_stem(m) if len(m) > 5 else m), blob)
        if any(hit(m) for m in ans_terms) or sum(1 for m in q_terms if hit(m)) >= 2:
            out.append(r)
    return out


def internet_for_question(qrow, background=False):
    """background=True (precarga): solo fuentes que toleran consultas automáticas (Tavily dentro de su cupo y Wikipedia)."""
    main, short, a_core, q_terms = build_queries(qrow)
    ans_terms = [_ascii(w) for w in a_core.split() if len(w) >= 3]
    q_keys = [_ascii(w) for w in q_terms[:5]]
    results, errors, used, notes = [], [], [], []
    cfg = db.load_config()
    # 1) Tavily, si hay clave y cupo
    t_cap = int(cfg.get("tavily_monthly", 1000))
    t_reserve = int(cfg.get("tavily_reserve", 300))          # siempre se guardan unas cuantas para ti
    if not cfg.get("tavily_api_key"):
        notes.append("sin clave de Tavily")
    elif _paused("tavily"):
        notes.append(db.kv_get("search_pause_why_tavily", "Tavily en pausa"))
    elif tavily_used() >= (t_cap - t_reserve if background else t_cap):
        notes.append("cupo mensual de Tavily agotado")
    else:
        try:
            results += tavily(main, 5)
            used.append("Tavily")
        except Exception as e:
            errors.append(str(e))
    # 2) DuckDuckGo: solo cuando lo pides tú y si no está bloqueado
    if not background and len(results) < 3:
        if _paused("duckduckgo"):
            notes.append("DuckDuckGo en pausa por bloqueo")
        else:
            try:
                r = ddg(main, 5) or ddg(short, 5)
                results += r
                used.append("DuckDuckGo")
            except Exception as e:
                errors.append(str(e))
    # 3) Wikipedia: primero la respuesta, luego la pregunta; solo resultados que mencionen las palabras clave
    if _paused("wikipedia"):
        notes.append("Wikipedia pide esperar")
    else:
        wiki = []
        tries = [q for q in (a_core, " ".join(a_core.split()[:2] + q_terms[:1]), short, " ".join(q_terms[:3]),
                             " ".join(q_terms[:2])) if q.strip()]
        try:
            for q in dict.fromkeys(tries):
                wiki = _relevant(wikipedia(q, 3), ans_terms, q_keys)
                if wiki:
                    break
            if wiki:
                results += wiki[:2]
                used.append("Wikipedia")
        except Exception as e:
            errors.append(str(e))
    seen, uniq = set(), []
    for r in results:
        k = (r.get("url") or "").split("#")[0]
        if k and k not in seen:
            seen.add(k)
            uniq.append(r)
    google_q = qrow["text"][:250] + " " + (qrow.get(effective_correct(qrow)) or "")[:80]
    return {"query": main, "results": uniq, "errors": errors, "engines": used, "notes": notes,
            "paused": [n for n in notes if "pausa" in n or "esperar" in n],
            "search_url": "https://www.google.com/search?hl=es&q=" + urllib.parse.quote(google_q),
            "wiki_url": "https://es.wikipedia.org/w/index.php?search=" + urllib.parse.quote(a_core or short)}


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


def ia_for_question(qrow, chosen=None, background=False):
    corr = effective_correct(qrow)
    t0 = time.time()
    tem = temario_for_question(qrow)["hits"][:3]
    gemini._log("búsqueda temario", "-", time.time() - t0, True)
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
    res = gemini.generate(prompt, schema=IA_SCHEMA, temperature=0.2, thinking="low", max_tokens=1500,
                          budget=200 if background else 70, call_timeout=45,
                          kind="precarga" if background else "explicación", background=background)
    res["respuesta_banco"] = corr
    return res


_inflight = {}
_inflight_lock = threading.Lock()


def prefetch_ia(qid, chosen=None):
    """Lanza la explicación de la IA en segundo plano (al fallar una pregunta), para que esté lista al pulsar «IA»."""
    if not (db.load_config().get("gemini_api_key")) or not gemini.quota_ok_for_background():
        return
    if db.scalar("SELECT 1 FROM sources_cache WHERE question_id=? AND source='ia'", (qid,)):
        return
    with _inflight_lock:
        if qid in _inflight:
            return
        ev = _inflight[qid] = threading.Event()

    def run():
        try:
            get_source(qid, "ia", chosen, _from_prefetch=True)
        except Exception:
            pass
        finally:
            with _inflight_lock:
                _inflight.pop(qid, None)
            ev.set()
    threading.Thread(target=run, daemon=True).start()


def prefetch_many(items, limit=10):
    """Modo examen: prepara las explicaciones de los fallos de una en una (sin saturar la cuota)."""
    if not db.load_config().get("gemini_api_key"):
        return

    def run():
        for qid, chosen in items[:limit]:
            if not gemini.quota_ok_for_background():
                break
            if db.scalar("SELECT 1 FROM sources_cache WHERE question_id=? AND source='ia'", (qid,)):
                continue
            with _inflight_lock:
                if qid in _inflight:
                    continue
                ev = _inflight[qid] = threading.Event()
            try:
                get_source(qid, "ia", chosen, _from_prefetch=True)
            except Exception:
                break                     # cuota agotada o sin conexión: no se insiste
            finally:
                with _inflight_lock:
                    _inflight.pop(qid, None)
                ev.set()
    threading.Thread(target=run, daemon=True).start()


def get_source(qid, which, chosen=None, refresh=False, _from_prefetch=False):
    qrow = db.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not qrow:
        raise KeyError("pregunta no encontrada")
    if which == "temario":       # el índice crece mientras avanza el OCR: no se cachea
        return temario_for_question(qrow)
    if which == "ia" and not refresh and not _from_prefetch:
        with _inflight_lock:
            ev = _inflight.get(qid)
        if ev:
            ev.wait(80)                       # ya se está generando: se espera a esa respuesta
    if not refresh:
        c = db.scalar("SELECT content FROM sources_cache WHERE question_id=? AND source=?", (qid, which))
        if c:
            out = json.loads(c)
            if not (which == "internet" and not out.get("results")):   # una búsqueda vacía se repite al pedirla
                out["cached"] = True
                return out
    if which == "internet":
        out = internet_for_question(qrow, background=_from_prefetch)
        if not out["results"]:
            return out
    elif which == "ia":
        out = ia_for_question(qrow, chosen, background=_from_prefetch)
    else:
        raise KeyError(which)
    db.run("INSERT OR REPLACE INTO sources_cache(question_id,source,content) VALUES(?,?,?)",
           (qid, which, json.dumps(out, ensure_ascii=False)))
    return out
