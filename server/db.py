"""Base de datos SQLite de OpoTest."""
import os
import sqlite3
import threading
import json

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("OPOTEST_DATA", os.path.join(BASE, "var"))
DB_PATH = os.path.join(DATA_DIR, "opotest.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TEMARIO_DIR = os.environ.get("OPOTEST_TEMARIO", os.path.join(os.path.dirname(BASE), "temario"))
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model": "gemini-3.8-flash",
    "gemini_fallback_models": ["gemini-3.6-flash", "gemini-3.5-flash-lite"],
    "daily_goal": 50,             # mínimo diario de preguntas
    "daily_new_questions": 20,    # preguntas nuevas generadas cada día
    "daily_gen_hour": 7,          # hora de la generación diaria
    "review_reminder_hour": 9,    # aviso de falladas pendientes
    "goal_reminder_hour": 20,     # aviso si no se ha llegado al mínimo
    "default_escala": "A2",
    "api_token": "",              # opcional: si se define, la app debe enviarlo
    "timezone": "Europe/Madrid",
}

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY,
  origin TEXT NOT NULL,            -- preparatic | ia
  ext_id TEXT,
  text TEXT NOT NULL,
  a TEXT, b TEXT, c TEXT, d TEXT,
  correct TEXT NOT NULL,           -- a|b|c|d (del banco)
  correct_override TEXT,           -- corrección marcada por el usuario
  explanation TEXT,
  comments TEXT,
  year TEXT,
  is_exam INTEGER DEFAULT 0,
  exams TEXT,
  block TEXT,                      -- subbloque A1..B4 (numeración PreparaTIC/ASTIC)
  ptopic INTEGER,                  -- tema PreparaTIC
  a1_doc TEXT,                     -- p.ej. A1-063
  a2_doc TEXT,                     -- p.ej. A2-II-05
  a2_doc2 TEXT,                    -- segundo tema del A2 con el que también encaja
  escala TEXT,                     -- A1 | A2 | C1
  created_at TEXT DEFAULT (datetime('now','localtime')),
  is_new INTEGER DEFAULT 0,
  gen_job INTEGER,
  hash TEXT UNIQUE,
  disabled INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS q_a1 ON questions(a1_doc);
CREATE INDEX IF NOT EXISTS q_a2 ON questions(a2_doc);
CREATE INDEX IF NOT EXISTS q_block ON questions(block);
CREATE INDEX IF NOT EXISTS q_new ON questions(is_new);

CREATE TABLE IF NOT EXISTS tests (
  id INTEGER PRIMARY KEY,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  finished_at TEXT,
  kind TEXT,                       -- normal | repaso | nuevas | falladas
  mode TEXT,                       -- practica | examen
  title TEXT,
  filters TEXT,
  n INTEGER,
  ok INTEGER DEFAULT 0, ko INTEGER DEFAULT 0, blank INTEGER DEFAULT 0,
  score REAL
);
CREATE TABLE IF NOT EXISTS test_items (
  test_id INTEGER, pos INTEGER, question_id INTEGER,
  chosen TEXT, is_correct INTEGER, answered_at TEXT, ms INTEGER,
  PRIMARY KEY (test_id, pos)
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY,
  question_id INTEGER, test_id INTEGER, chosen TEXT, is_correct INTEGER,
  answered_at TEXT DEFAULT (datetime('now','localtime')),
  day TEXT DEFAULT (date('now','localtime')),
  ms INTEGER
);
CREATE INDEX IF NOT EXISTS att_day ON attempts(day);
CREATE INDEX IF NOT EXISTS att_q ON attempts(question_id);

CREATE TABLE IF NOT EXISTS review (
  question_id INTEGER PRIMARY KEY,
  box INTEGER DEFAULT 0,           -- caja Leitner 0..5
  due TEXT,                        -- fecha de próximo repaso
  fails INTEGER DEFAULT 0,
  last_fail TEXT,
  mastered INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rev_due ON review(due);

CREATE TABLE IF NOT EXISTS docs (
  id TEXT PRIMARY KEY, temario TEXT, bloque TEXT, num INTEGER, title TEXT,
  kind TEXT, files TEXT, resumen TEXT,
  pages INTEGER DEFAULT 0, status TEXT DEFAULT 'pendiente', progress INTEGER DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS pages (
  doc_id TEXT, file_idx INTEGER, page INTEGER, text TEXT, ocr INTEGER DEFAULT 0,
  PRIMARY KEY (doc_id, file_idx, page)
);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
  text, doc_id UNINDEXED, file_idx UNINDEXED, page UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS sources_cache (
  question_id INTEGER, source TEXT, content TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  PRIMARY KEY (question_id, source)
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  kind TEXT, title TEXT, body TEXT, link TEXT
);
CREATE TABLE IF NOT EXISTS gen_jobs (
  id INTEGER PRIMARY KEY,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  finished_at TEXT,
  trigger TEXT,                    -- diario | manual
  requested INTEGER, generated INTEGER DEFAULT 0,
  status TEXT DEFAULT 'en_cola', error TEXT, filters TEXT
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

_local = threading.local()


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    cols = [r[1] for r in c.execute("PRAGMA table_info(questions)")]
    if "a2_doc2" not in cols:
        c.execute("ALTER TABLE questions ADD COLUMN a2_doc2 TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS q_a2b ON questions(a2_doc2)")
    for col, typ in (("rating", "TEXT"), ("rated_at", "TEXT"), ("difficulty", "INTEGER")):
        if col not in cols:
            c.execute(f"ALTER TABLE questions ADD COLUMN {col} {typ}")
    c.commit()


def q(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def scalar(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return r[0] if r else None


def run(sql, args=()):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def kv_get(k, default=None):
    v = scalar("SELECT v FROM kv WHERE k=?", (k,))
    return v if v is not None else default


def kv_set(k, v):
    run("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
