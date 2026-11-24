"""Servidor de OpoTest (Starlette + uvicorn).
    uvicorn app:app --host 0.0.0.0 --port 8790
"""
import json
import mimetypes
import os
import threading
import time
import traceback

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import db
import logic
import sources
import gemini
import prefetch
import extras
import fichas

WEB = os.path.join(db.BASE, "web")
mimetypes.add_type("text/javascript", ".mjs")   # Python 3.11 no lo conoce y los módulos JS lo exigen
VERSION = "1.0.0"


def J(data, status=200):
    return JSONResponse(data, status_code=status)


def err(msg, status=400):
    return J({"error": msg}, status)


def authorized(req: Request):
    tok = db.load_config().get("api_token")
    if not tok:
        return True
    return req.headers.get("x-token") == tok or req.query_params.get("token") == tok


def api(fn):
    """Envuelve los endpoints: auth, JSON y errores legibles."""
    async def wrapper(req: Request):
        if not authorized(req):
            return err("Token incorrecto", 401)
        body = {}
        if req.method in ("POST", "PUT"):
            try:
                body = await req.json()
            except Exception:
                body = {}
        try:
            from starlette.concurrency import run_in_threadpool
            res = await run_in_threadpool(fn, req, body)
            if isinstance(res, Response):
                return res
            return J(res)
        except KeyError as e:
            return err(f"No encontrado: {e}", 404)
        except (ValueError, gemini.GeminiError) as e:
            return err(str(e), 400)
        except Exception as e:
            traceback.print_exc()
            return err(f"Error interno: {e}", 500)
    return wrapper


def qp(req, k, default=None, cast=str):
    v = req.query_params.get(k)
    if v is None or v == "":
        return default
    try:
        return cast(v)
    except Exception:
        return default


# ------------------------------------------------------------- endpoints

def health(req, body):
    return {"ok": True, "version": VERSION, "time": time.strftime("%Y-%m-%d %H:%M:%S")}


def home(req, body):
    return logic.home()


def catalog(req, body):
    return logic.docs_tree()


def doc_info(req, body):
    did = req.path_params["doc"]
    d = db.q1("SELECT * FROM docs WHERE id=?", (did,))
    if not d:
        raise KeyError(did)
    d["files"] = json.loads(d["files"])
    d["indexed"] = db.scalar("SELECT COUNT(*) FROM pages WHERE doc_id=? AND length(text)>0", (did,))
    d["questions"] = db.scalar("SELECT COUNT(*) FROM questions WHERE disabled=0 AND (a1_doc=? OR a2_doc=? OR a2_doc2=?)", (did, did, did))
    root = os.path.join(db.TEMARIO_DIR, d["temario"])
    d["pdf_available"] = [os.path.exists(os.path.join(root, f)) for f in d["files"]]
    d["resumen_available"] = bool(d.get("resumen")) and os.path.exists(os.path.join(root, d["resumen"]))
    return d


def doc_pages(req, body):
    did = req.path_params["doc"]
    a, b = qp(req, "from", 1, int), qp(req, "to", 15, int)
    return {"pages": db.q("SELECT page, text, ocr FROM pages WHERE doc_id=? AND file_idx=0 AND page BETWEEN ? AND ? ORDER BY page",
                          (did, a, b)),
            "total": db.scalar("SELECT pages FROM docs WHERE id=?", (did,)) or 0}


def doc_pdf(req, body):
    did = req.path_params["doc"]
    d = db.q1("SELECT * FROM docs WHERE id=?", (did,))
    if not d:
        raise KeyError(did)
    files = json.loads(d["files"])
    which = req.query_params.get("file", "0")
    rel = d["resumen"] if which == "resumen" else files[int(which)]
    root = os.path.realpath(os.path.join(db.TEMARIO_DIR, d["temario"]))
    path = os.path.realpath(os.path.join(root, rel))
    if not path.startswith(root + os.sep) or not os.path.exists(path):
        return err("El PDF no está en la Raspberry (cópialo con el script del PC).", 404)
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": "inline", "Cache-Control": "max-age=86400"})


def temario_search(req, body):
    text = qp(req, "q", "")
    temario = qp(req, "temario")
    docs = None
    if temario in ("A1", "A2"):
        docs = [r["id"] for r in db.q("SELECT id FROM docs WHERE temario=?", (temario,))]
    if qp(req, "doc"):
        docs = [qp(req, "doc")]
    return {"hits": sources.search_temario(text, docs, qp(req, "limit", 20, int))}


def tests_create(req, body):
    t = logic.create_test(body.get("kind", "normal"), body.get("n", 20), body.get("mode", "practica"),
                          body.get("filters") or {}, body.get("title"), body.get("question_ids"))
    if not t:
        raise ValueError("No hay preguntas con esos filtros")
    return t


def tests_count(req, body):
    return {"count": logic.count_questions(body.get("filters") or {})}


def tests_get(req, body):
    t = logic.get_test(int(req.path_params["tid"]))
    if not t:
        raise KeyError("test")
    return logic.sim_extra(t)


def sim_create(req, body):
    return extras.create_simulacro(body.get("n"), body.get("minutes"))


def sim_list(req, body):
    return {"items": extras.simulacros(), "per_block": extras._split(int(db.load_config().get("sim_questions", 100)), extras._block_weights())}


def quick(req, body):
    t = extras.quick_test(max(1, min(100, int(body.get("n", 10)))), body.get("title") or "5 minutos")
    if not t:
        raise ValueError("No hay preguntas disponibles")
    return t


def mapa(req, body):
    return extras.topic_map(qp(req, "temario"))


def widget_data(req, body):
    return extras.widget()


def fichas_list(req, body):
    return {"items": fichas.due_list(qp(req, "doc"), qp(req, "limit", 40, int), qp(req, "all") == "1"), **fichas.summary()}


def fichas_review(req, body):
    return fichas.review(int(req.path_params["fid"]), bool(body.get("ok")))


def fichas_generate(req, body):
    if not db.load_config().get("gemini_api_key"):
        raise ValueError("Configura primero la API key de Gemini")
    n = fichas.generate_batch(background=False)
    return {"created": n, **fichas.summary()}


def tests_answer(req, body):
    return logic.answer(int(req.path_params["tid"]), int(body["pos"]), body.get("chosen"), body.get("ms"))


def tests_finish(req, body):
    return logic.finish(int(req.path_params["tid"]))


def tests_retry(req, body):
    tid = int(req.path_params["tid"])
    ids = [r["question_id"] for r in db.q("SELECT question_id FROM test_items WHERE test_id=? AND (is_correct=0 OR chosen IS NULL) ORDER BY pos", (tid,))]
    if not ids:
        raise ValueError("Este test no tiene fallos")
    title = db.scalar("SELECT title FROM tests WHERE id=?", (tid,))
    return logic.create_test("falladas", len(ids), body.get("mode", "practica"), {}, f"Fallos de: {title}", ids)


def tests_delete(req, body):
    tid = int(req.path_params["tid"])
    db.run("DELETE FROM test_items WHERE test_id=?", (tid,))
    db.run("DELETE FROM tests WHERE id=?", (tid,))
    return {"ok": True}


def history(req, body):
    return {"tests": logic.history(qp(req, "limit", 50, int), qp(req, "offset", 0, int))}


def failed(req, body):
    return {"items": logic.failed_list(qp(req, "limit", 100, int), qp(req, "offset", 0, int)),
            "due": db.scalar("SELECT COUNT(*) FROM review WHERE mastered=0 AND due<=?", (logic.today(),)),
            "total": db.scalar("SELECT COUNT(*) FROM review WHERE mastered=0")}


def question_get(req, body):
    qid = int(req.path_params["qid"])
    q = db.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not q:
        raise KeyError("pregunta")
    d = logic.public_q(q, True)
    d["titles"] = logic.doc_titles(q)
    d["ready"] = logic.ready_map([qid])[qid]
    d["attempts"] = db.q("SELECT answered_at, chosen, is_correct FROM attempts WHERE question_id=? ORDER BY id DESC LIMIT 20", (qid,))
    d["review"] = db.q1("SELECT * FROM review WHERE question_id=?", (qid,))
    return d


def question_correct(req, body):
    return logic.set_correct(int(req.path_params["qid"]), body.get("letter"))


def question_rate(req, body):
    return logic.rate_question(int(req.path_params["qid"]), body.get("rating"))


def question_disable(req, body):
    logic.disable_question(int(req.path_params["qid"]), body.get("disabled", True))
    return {"ok": True}


def question_sources(req, body):
    return sources.get_source(int(req.path_params["qid"]), req.path_params["which"],
                              qp(req, "chosen"), qp(req, "refresh") == "1")


def stats(req, body):
    return logic.stats()


def gen_start(req, body):
    if not db.load_config().get("gemini_api_key"):
        raise ValueError("Configura primero la API key de Gemini en Ajustes")
    return logic.start_generation(body.get("n", 10), body.get("filters") or {}, "manual")


def gen_get(req, body):
    j = logic.job(int(req.path_params["jid"]))
    if not j:
        raise KeyError("job")
    return j


def gen_list(req, body):
    return {"jobs": db.q("SELECT * FROM gen_jobs ORDER BY id DESC LIMIT 20")}


def notif(req, body):
    since = qp(req, "since", 0, int)
    if since < 0:   # el móvil pide el último id para no mostrar avisos antiguos al instalar
        return {"last_id": db.scalar("SELECT COALESCE(MAX(id),0) FROM notifications"), "items": []}
    return {"items": logic.notifications_since(since)}


def notif_list(req, body):
    return {"items": db.q("SELECT * FROM notifications ORDER BY id DESC LIMIT 50")}


SETTINGS_KEYS = ["gemini_model", "gemini_fallback_models", "daily_goal", "daily_new_questions", "daily_gen_hour",
                 "review_reminder_hour", "goal_reminder_hour", "default_escala", "ai_prefetch_daily", "net_prefetch_daily",
                 "batch_enabled", "batch_max_requests", "batch_model", "batch_net_nightly", "batch_start_hour", "batch_end_hour",
                 "fichas_daily_requests", "sim_questions", "sim_minutes", "target_retention"]


def settings_get(req, body):
    cfg = db.load_config()
    out = {k: cfg.get(k) for k in SETTINGS_KEYS}
    key = cfg.get("gemini_api_key") or ""
    tk = cfg.get("tavily_api_key") or ""
    out["tavily_key_set"] = bool(tk)
    out["tavily_key_hint"] = ("…" + tk[-4:]) if tk else ""
    out["tavily_used"] = sources.tavily_used()
    out["gemini_api_key_set"] = bool(key)
    out["gemini_api_key_hint"] = ("…" + key[-4:]) if key else ""
    out["temario_dir"] = db.TEMARIO_DIR
    out["gen_level"] = logic.gen_level()
    out["gen_level_auto"] = db.kv_get("gen_level_auto", "1") == "1"
    return out


def settings_save(req, body):
    cfg = db.load_config()
    for k in SETTINGS_KEYS:
        if k in body:
            v = body[k]
            if k in ("daily_goal", "daily_new_questions", "daily_gen_hour", "review_reminder_hour", "goal_reminder_hour",
                     "ai_prefetch_daily", "net_prefetch_daily", "batch_max_requests", "batch_net_nightly",
                     "batch_start_hour", "batch_end_hour", "fichas_daily_requests", "sim_questions", "sim_minutes"):
                v = int(v)
            if k == "target_retention":
                v = max(0.75, min(0.97, float(v)))
            if k == "batch_enabled":
                v = v in (True, "1", "true", "si", "sí", 1)
            if k == "gemini_fallback_models" and isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            cfg[k] = v
    if body.get("gemini_api_key"):
        cfg["gemini_api_key"] = body["gemini_api_key"].strip()
    if "tavily_api_key" in body and body["tavily_api_key"] is not None:
        v = body["tavily_api_key"].strip()
        if v == "-":
            cfg["tavily_api_key"] = ""
        elif v:
            cfg["tavily_api_key"] = v
            db.kv_set("search_pause_tavily", 0)
    if "gen_level" in body:
        lv = str(body["gen_level"])
        db.kv_set("gen_level_auto", "1" if lv == "auto" else "0")
        if lv != "auto":
            db.kv_set("gen_level", max(1, min(3, int(lv))))
    db.save_config(cfg)
    return settings_get(req, {})


def settings_test_ai(req, body):
    """Diagnóstico rápido: conexión, validez de la key, modelo disponible y una respuesta de prueba."""
    import urllib.error
    cfg = db.load_config()
    key = (cfg.get("gemini_api_key") or "").strip()
    if not key:
        raise ValueError("Pega primero la API key.")
    notes = []
    try:
        available = gemini.list_models(key)
    except urllib.error.HTTPError as e:
        raise ValueError(gemini._explain_http(e.code, e.read().decode("utf-8", "ignore")))
    except Exception as e:
        raise ValueError(f"La Raspberry no consigue conectar con Google ({getattr(e, 'reason', e)}). "
                         "Comprueba que tiene Internet.")
    best, backups = gemini.pick_models(available)
    current = cfg.get("gemini_model")
    if current not in available and best:
        notes.append(f"El modelo {current} no está disponible en tu cuenta; uso {best}.")
        cfg["gemini_model"] = best
    main = cfg["gemini_model"]
    usable_backups = [m for m in (cfg.get("gemini_fallback_models") or []) if m in available and m != main]
    extra = [m for m in [best] + backups if m and m != main and m not in usable_backups]
    cfg["gemini_fallback_models"] = (usable_backups + extra)[:2]
    db.save_config(cfg)
    txt = gemini.generate("Responde solo con la palabra: funciona", temperature=0, quick=True, max_tokens=20)
    return {"ok": True, "reply": txt[:100], "model": cfg["gemini_model"],
            "fallbacks": cfg["gemini_fallback_models"], "notes": notes}


def diag(req, body):
    """Estado de la Pi y tiempos de las últimas llamadas a la IA."""
    now = time.time()
    out = {"calls": list(reversed(gemini.CALLS)), "model": db.load_config().get("gemini_model"),
           "usage": gemini.usage_today(),
           "blocked": {m: {"why": v["why"], "until": time.strftime("%H:%M", time.localtime(v["until"]))}
                       for m, v in gemini.blocked_models().items()},
           "gen_retry": (time.strftime("%H:%M", time.localtime(float(db.kv_get("gen_retry_at", 0) or 0)))
                         if float(db.kv_get("gen_retry_at", 0) or 0) > now else None)}
    try:
        out["load"] = [round(x, 2) for x in os.getloadavg()]
        out["cpus"] = os.cpu_count()
    except Exception:
        pass
    try:
        out["temp"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
    except Exception:
        pass
    try:
        mem = dict(l.split(":", 1) for l in open("/proc/meminfo"))
        out["mem_free_mb"] = int(mem["MemAvailable"].split()[0]) // 1024
    except Exception:
        pass
    out["prefetch"] = prefetch.status()
    out["search"] = sources.search_status()
    out["night"] = prefetch.night_status()
    out["ocr"] = db.q1("SELECT SUM(status IN ('ocr','procesando')) working, SUM(status='ok') ok, COUNT(*) n FROM docs")
    t = time.time(); db.scalar("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'datos'"); out["db_ms"] = int((time.time() - t) * 1000)
    return out


def notif_test(req, body):
    logic.notify("prueba", "Notificación de prueba", "Si ves esto en el móvil, los avisos funcionan.", "#/")
    return {"ok": True}


async def index(req):
    return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-cache"})


R = lambda path, fn, methods=("GET",): Route(path, api(fn), methods=list(methods))
routes = [
    Route("/", index),
    R("/api/health", health),
    R("/api/home", home),
    R("/api/catalog", catalog),
    R("/api/temario/search", temario_search),
    R("/api/temario/{doc}", doc_info),
    R("/api/temario/{doc}/pages", doc_pages),
    R("/api/temario/{doc}/pdf", doc_pdf),
    R("/api/tests", tests_create, ["POST"]),
    R("/api/tests/count", tests_count, ["POST"]),
    R("/api/tests/{tid:int}", tests_get),
    R("/api/tests/{tid:int}", tests_delete, ["DELETE"]),
    R("/api/tests/{tid:int}/answer", tests_answer, ["POST"]),
    R("/api/tests/{tid:int}/finish", tests_finish, ["POST"]),
    R("/api/tests/{tid:int}/retry", tests_retry, ["POST"]),
    R("/api/history", history),
    R("/api/simulacro", sim_create, ["POST"]),
    R("/api/simulacro", sim_list),
    R("/api/quick", quick, ["POST"]),
    R("/api/mapa", mapa),
    R("/api/widget", widget_data),
    R("/api/fichas", fichas_list),
    R("/api/fichas/generate", fichas_generate, ["POST"]),
    R("/api/fichas/{fid:int}/review", fichas_review, ["POST"]),
    R("/api/failed", failed),
    R("/api/questions/{qid:int}", question_get),
    R("/api/questions/{qid:int}/correct", question_correct, ["POST"]),
    R("/api/questions/{qid:int}/disable", question_disable, ["POST"]),
    R("/api/questions/{qid:int}/rate", question_rate, ["POST"]),
    R("/api/questions/{qid:int}/sources/{which}", question_sources),
    R("/api/stats", stats),
    R("/api/generate", gen_start, ["POST"]),
    R("/api/generate", gen_list),
    R("/api/generate/{jid:int}", gen_get),
    R("/api/notifications", notif),
    R("/api/notifications/all", notif_list),
    R("/api/notifications/test", notif_test, ["POST"]),
    R("/api/diag", diag),
    R("/api/settings", settings_get),
    R("/api/settings", settings_save, ["POST"]),
    R("/api/settings/test_ai", settings_test_ai, ["POST"]),
    Mount("/static", StaticFiles(directory=WEB), name="static"),
]


def _scheduler():
    while True:
        try:
            logic.scheduler_tick()
        except Exception:
            traceback.print_exc()
        time.sleep(60)


def _startup():
    db.init()
    if not db.scalar("SELECT COUNT(*) FROM questions"):
        import importer
        importer.main()
    if os.environ.get("OPOTEST_NO_SCHEDULER") != "1":
        threading.Thread(target=_scheduler, daemon=True).start()
        prefetch.start()


import contextlib


@contextlib.asynccontextmanager
async def lifespan(app):
    _startup()
    yield


app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(GZipMiddleware, minimum_size=1000)])
