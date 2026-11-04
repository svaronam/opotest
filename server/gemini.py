"""Cliente mínimo de la API de Gemini (sin dependencias externas)."""
import json
import time
import urllib.error
import urllib.request

import db

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(Exception):
    pass


def _post(model, key, body, timeout=120):
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def generate(prompt, schema=None, temperature=0.7, system=None, max_tokens=8192):
    """Devuelve el texto (o el JSON ya parseado si se pasa schema)."""
    cfg = db.load_config()
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        raise GeminiError("Falta la API key de Gemini (Ajustes → IA).")
    gen_cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if schema:
        gen_cfg["responseMimeType"] = "application/json"
        gen_cfg["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    models = [cfg.get("gemini_model") or "gemini-3.8-flash"] + list(cfg.get("gemini_fallback_models") or [])
    last = None
    for model in models:
        for attempt in range(3):
            try:
                res = _post(model, key, body)
                cands = res.get("candidates") or []
                if not cands:
                    raise GeminiError("Respuesta vacía de Gemini: %s" % json.dumps(res)[:300])
                parts = cands[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if schema:
                    return _parse_json(text)
                return text
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:400]
                last = GeminiError(f"{model}: HTTP {e.code} {detail}")
                if e.code in (429, 500, 503):
                    time.sleep(8 * (attempt + 1))
                    continue
                if e.code in (400, 404):   # modelo inexistente o petición no soportada → siguiente modelo
                    break
                raise last
            except (urllib.error.URLError, TimeoutError) as e:
                last = GeminiError(f"{model}: sin conexión ({e})")
                time.sleep(5)
            except ValueError as e:
                last = GeminiError(f"{model}: JSON no válido ({e})")
                break
    raise last or GeminiError("No se pudo contactar con Gemini")


def _parse_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("\n") + 1:] if "\n" in t else t
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [0])
    return json.loads(t[start:])
