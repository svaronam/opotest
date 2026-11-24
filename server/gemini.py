"""Cliente mínimo de la API de Gemini (sin dependencias externas), con gestión de la cuota gratuita.

- Distingue el límite por minuto del límite por día (lo dice Google en el error 429).
- Si un modelo agota su cuota diaria, no se le vuelve a llamar hasta que se renueve (medianoche de California).
- Las peticiones en segundo plano (generación diaria, precarga) van espaciadas y ceden el paso a las tuyas.
- Cuenta las peticiones de cada día para mostrarlas en Ajustes → Diagnóstico.
"""
import datetime as dt
import base64
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request

import db

BASE = "https://generativelanguage.googleapis.com/v1beta"
API = BASE + "/models/{model}:generateContent"

BACKGROUND_GAP = 13          # segundos mínimos entre peticiones de fondo (≤ 5 por minuto)


class GeminiError(Exception):
    pass


class QuotaError(GeminiError):
    pass


def _post(model, key, body, timeout):
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ------------------------------------------------------------------ cuota

_lock = threading.Lock()
_interactive = 0             # peticiones tuyas en curso: las de fondo esperan
_last_call = 0.0


def _today():
    return dt.date.today().isoformat()


def _next_reset():
    """La cuota diaria gratuita se renueva a medianoche, hora del Pacífico."""
    try:
        from zoneinfo import ZoneInfo
        pt = ZoneInfo("America/Los_Angeles")
        now = dt.datetime.now(pt)
        nxt = (now + dt.timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        return nxt.timestamp()
    except Exception:
        return time.time() + 6 * 3600


def _blocked():
    try:
        return json.loads(db.kv_get("gemini_blocked", "{}"))
    except Exception:
        return {}


def _block(model, until, why):
    b = _blocked()
    b[model] = {"until": until, "why": why}
    db.kv_set("gemini_blocked", json.dumps(b))


def blocked_models():
    now = time.time()
    return {m: v for m, v in _blocked().items() if v["until"] > now}


def _count(model, kind):
    key = "gemini_calls_" + _today()
    try:
        c = json.loads(db.kv_get(key, "{}"))
    except Exception:
        c = {}
    c[model] = c.get(model, 0) + 1
    c["_" + kind] = c.get("_" + kind, 0) + 1
    db.kv_set(key, json.dumps(c))


def usage_today():
    try:
        return json.loads(db.kv_get("gemini_calls_" + _today(), "{}"))
    except Exception:
        return {}


def quota_ok_for_background():
    """¿Conviene gastar cuota en algo no pedido (precarga)? No si el modelo principal está bloqueado o hubo 429 hace poco."""
    cfg = db.load_config()
    main = cfg.get("gemini_model")
    if main in blocked_models():
        return False
    recent = [c for c in CALLS[-6:] if "429" in (c.get("note") or "") and time.time() - c.get("ts", 0) < 600]
    if recent:
        return False
    cap = int(cfg.get("ai_prefetch_daily", 15))
    return usage_today().get("_precarga", 0) < cap


def _quota_info(detail):
    """De un 429 de Google saca si es por minuto o por día, el límite y cuánto esperar."""
    scope = "day" if re.search(r"PerDay", detail) else ("minute" if re.search(r"PerMinute", detail) else None)
    if not scope and re.search(r"per\s*day|daily", detail, re.I):
        scope = "day"
    lim = re.search(r'"quotaValue":\s*"(\d+)"', detail) or re.search(r"limit:\s*(\d+)", detail)
    retry = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', detail) or re.search(r"retry in (\d+(?:\.\d+)?)s", detail)
    return scope, (int(lim.group(1)) if lim else None), (float(retry.group(1)) if retry else None)


def _wait_turn(background):
    """Las peticiones de fondo esperan su turno; las tuyas pasan directamente."""
    global _last_call, _interactive
    if not background:
        with _lock:
            _interactive += 1
            _last_call = time.time()
        return
    while True:
        with _lock:
            gap = time.time() - _last_call
            if _interactive == 0 and gap >= BACKGROUND_GAP:
                _last_call = time.time()
                return
        time.sleep(1.5)


def _done_turn(background):
    global _interactive
    if not background:
        with _lock:
            _interactive = max(0, _interactive - 1)


# ------------------------------------------------------------------ mensajes

def _explain_http(code, detail, model=None):
    d = detail.lower()
    if code == 400 and ("api key not valid" in d or "api_key_invalid" in d):
        return "La API key no es válida. Cópiala de nuevo desde AI Studio."
    if code in (401, 403):
        return "Google rechaza la API key (sin permiso). Revisa que esté bien copiada y que la API esté activa en tu proyecto."
    if code == 404:
        return "Ese modelo no existe o no está disponible para tu cuenta."
    if code == 429:
        scope, lim, retry = _quota_info(detail)
        if lim == 0:
            return "este modelo no tiene cuota gratuita en tu cuenta"
        if scope == "day":
            return f"cuota diaria gratuita agotada{f' ({lim} peticiones/día)' if lim else ''}"
        if scope == "minute":
            return f"demasiadas peticiones seguidas{f' (máx. {lim}/min)' if lim else ''}"
        return "cuota agotada por ahora"
    if code in (500, 503):
        return "Gemini está saturado en este momento"
    m = re.search(r'"message":\s*"([^"]+)"', detail)
    return m.group(1) if m else detail[:200]


def list_models(key, timeout=15):
    """Modelos que esta API key puede usar para generar texto."""
    req = urllib.request.Request(BASE + "/models?pageSize=200", headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    out = []
    for m in data.get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(m["name"].split("/", 1)[-1])
    return out


def _ver(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0


def pick_models(available):
    """Elige el mejor 'flash' de texto disponible y dos de reserva."""
    bad = re.compile(r"live|tts|image|audio|embed|transcribe|translate|thinking|customtools|exp|preview|-\d{3,}$")
    flash = [m for m in available if m.startswith("gemini-") and "flash" in m and not bad.search(m)]
    if not flash:   # si solo hay preview o similares, se aceptan
        flash = [m for m in available if m.startswith("gemini-") and "flash" in m and not re.search(r"live|tts|image|audio|embed", m)]
    full = sorted([m for m in flash if "lite" not in m], key=_ver, reverse=True)
    lite = sorted([m for m in flash if "lite" in m], key=_ver, reverse=True)
    ordered = full + lite
    return (ordered[0] if ordered else None), ordered[1:3]


_NO_THINKING_CFG = set()     # modelos que rechazan thinkingConfig: se recuerda para no repetir el error


def _thinking_cfg(model, level):
    """Gemini 3 usa thinkingLevel; los 2.5 usaban thinkingBudget."""
    if not level or model in _NO_THINKING_CFG:
        return None
    if re.search(r"gemini-2\.", model):
        return {"thinkingBudget": {"minimal": 0, "low": 512, "medium": 2048}.get(level, 1024)}
    return {"thinkingLevel": level}


CALLS = []          # últimas llamadas, para el diagnóstico de Ajustes


def _log(kind, model, secs, ok, note=""):
    CALLS.append({"when": time.strftime("%H:%M:%S"), "ts": time.time(), "kind": kind, "model": model,
                  "secs": round(secs, 1), "ok": ok, "note": note[:200]})
    del CALLS[:-20]


def _fmt_until(ts):
    return time.strftime("%H:%M", time.localtime(ts))


# ------------------------------------------------------------------ llamada principal

def generate(prompt, schema=None, temperature=0.7, system=None, max_tokens=8192, quick=False, thinking=None,
             budget=None, call_timeout=None, kind="otro", background=False, models=None, images=None):
    """Devuelve el texto (o el JSON ya parseado si se pasa schema).
    quick: un intento por modelo y espera corta (prueba de Ajustes).
    thinking: 'minimal' | 'low' | 'medium' | None. Menos razonamiento = respuesta más rápida.
    background: petición no pedida por ti (generación, precarga): va espaciada y no reintenta agresivamente."""
    cfg = db.load_config()
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        raise GeminiError("Falta la API key de Gemini (Ajustes → IA).")
    gen_cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if schema:
        gen_cfg["responseMimeType"] = "application/json"
        gen_cfg["responseSchema"] = schema
    parts = [{"text": prompt}]
    for mime, data in images or []:          # fotos (p. ej. respuestas a mano del supuesto práctico)
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen_cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    models = list(models or []) or ([cfg.get("gemini_model") or "gemini-3.8-flash"] + list(cfg.get("gemini_fallback_models") or []))
    timeout = call_timeout or (25 if quick else 90)
    limit = budget or (40 if quick else 300)
    started = time.time()
    errors, all_quota = [], True
    blocked = blocked_models()
    for model in models:
        if model in blocked:
            errors.append(f"{model}: {blocked[model]['why']} (hasta las {_fmt_until(blocked[model]['until'])})")
            continue
        for attempt in range(2):
            left = limit - (time.time() - started)
            if left < 8:
                break
            tcfg = _thinking_cfg(model, thinking)
            if tcfg:
                body["generationConfig"]["thinkingConfig"] = tcfg
            else:
                body["generationConfig"].pop("thinkingConfig", None)
            _wait_turn(background)
            t0 = time.time()
            try:
                _count(model, kind)
                res = _post(model, key, body, min(timeout, left))
                cands = res.get("candidates") or []
                _log(kind, model, time.time() - t0, bool(cands), "" if cands else "respuesta vacía")
                if not cands:
                    reason = (res.get("promptFeedback") or {}).get("blockReason", "sin contenido")
                    raise GeminiError(f"{model}: respuesta vacía ({reason})")
                parts = cands[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                return _parse_json(text) if schema else text
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:4000]
                if e.code == 400 and tcfg and "thinking" in detail.lower() and attempt == 0:
                    _NO_THINKING_CFG.add(model)          # el modelo no admite ese ajuste: se repite sin él
                    _log(kind, model, time.time() - t0, False, "no admite thinkingConfig, se repite sin él")
                    continue
                msg = _explain_http(e.code, detail, model)
                _log(kind, model, time.time() - t0, False, f"HTTP {e.code} {msg}")
                if msg.startswith(("La API key", "Google rechaza")):
                    raise GeminiError(msg)          # problema de la key: no tiene sentido seguir
                if e.code == 429:
                    scope, lim, retry = _quota_info(detail)
                    if lim == 0 or scope == "day":
                        until = _next_reset() if scope == "day" else time.time() + 7 * 86400
                        _block(model, until, msg)
                        errors.append(f"{model}: {msg} (vuelve a las {_fmt_until(until)})")
                        break                       # siguiente modelo
                    wait = min(retry or 20, 60)
                    if scope == "minute" or retry:
                        _block(model, time.time() + wait, msg)
                    if not background and attempt == 0 and left - wait > 15 and wait <= 25:
                        time.sleep(wait)            # límite por minuto: se espera lo que pide Google y se repite
                        continue
                    errors.append(f"{model}: {msg}")
                    break
                all_quota = False
                if e.code in (500, 503) and attempt == 0 and left > 20:
                    time.sleep(3 if not background else 20)
                    continue
                errors.append(f"{model}: {msg}")
                break
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                all_quota = False
                reason = getattr(e, "reason", e)
                _log(kind, model, time.time() - t0, False, f"sin respuesta ({reason})")
                if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
                    errors.append(f"{model}: no respondió en {int(time.time() - t0)} s")
                    break                               # se prueba el modelo de reserva si queda tiempo
                raise GeminiError(f"La Raspberry no consigue conectar con Google ({reason}). "
                                  "Comprueba que tiene Internet: curl -I https://generativelanguage.googleapis.com")
            except ValueError as e:
                all_quota = False
                errors.append(f"{model}: respuesta no válida ({e})")
                break
            finally:
                _done_turn(background)
    if not errors:
        errors.append(f"sin respuesta en {int(time.time() - started)} s")
    if all_quota and errors:
        raise QuotaError("Sin cuota de Gemini ahora mismo: " + " · ".join(errors))
    raise GeminiError("Gemini no ha respondido: " + " · ".join(errors))


def _parse_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("\n") + 1:] if "\n" in t else t
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [0])
    return json.loads(t[start:])
