"""Servidor de OpoTest (Starlette + uvicorn).
    uvicorn app:app --host 0.0.0.0 --port 8790
"""
import json
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

WEB = os.path.join(db.BASE, "web")
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
    return t


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
                 "review_reminder_hour", "goal_reminder_hour", "default_escala"]


def settings_get(req, body):
    cfg = db.load_config()
    out = {k: cfg.get(k) for k in SETTINGS_KEYS}
    key = cfg.get("gemini_api_key") or ""
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
            if k in ("daily_goal", "daily_new_questions", "daily_gen_hour", "review_reminder_hour", "goal_reminder_hour"):
                v = int(v)
            if k == "gemini_fallback_models" and isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            cfg[k] = v
    if body.get("gemini_api_key"):
        cfg["gemini_api_key"] = body["gemini_api_key"].strip()
    if "gen_level" in body:
        lv = str(body["gen_level"])
        db.kv_set("gen_level_auto", "1" if lv == "auto" else "0")
        if lv != "auto":
            db.kv_set("gen_level", max(1, min(3, int(lv))))
    db.save_config(cfg)
    return settings_get(req, {})


def settings_test_ai(req, body):
    txt = gemini.generate("Responde solo con la palabra: funciona", temperature=0)
    return {"ok": True, "reply": txt[:100], "model": db.load_config().get("gemini_model")}


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


import contextlib


@contextlib.asynccontextmanager
async def lifespan(app):
    _startup()
    yield


app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(GZipMiddleware, minimum_size=1000)])
