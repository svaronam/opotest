"""Repaso espaciado con FSRS (el algoritmo de Anki, versión 4.5).

Cada pregunta fallada al menos una vez tiene:
  - estabilidad (S): días que tardarías en bajar al 90 % de probabilidad de acordarte,
  - dificultad (D): de 1 a 10, sube cada vez que la fallas.
Al responder se recalculan y se programa el siguiente repaso para cuando la probabilidad
de acordarte baje a la retención objetivo (90 % por defecto). Las que dominas vuelven cada
vez más tarde; las que se te resisten, antes.
"""
import datetime as dt
import math

import db

W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474, 0.1367,
     1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
DECAY = -0.5
FACTOR = 19 / 81
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
MASTERED_DAYS = 120          # con esta estabilidad se da por dominada y sale de la cola
MAX_INTERVAL = 365


def _clamp_d(d):
    return min(10.0, max(1.0, d))


def init_difficulty(g):
    return _clamp_d(W[4] - (g - 3) * W[5])


def init_stability(g):
    return max(0.1, W[g - 1])


def retrievability(elapsed_days, s):
    return (1 + FACTOR * max(0.0, elapsed_days) / max(s, 0.01)) ** DECAY


def next_interval(s, retention=0.9):
    days = s / FACTOR * (retention ** (1 / DECAY) - 1)
    return max(1, min(MAX_INTERVAL, round(days)))


def next_difficulty(d, g):
    d2 = d - W[6] * (g - 3)
    return _clamp_d(W[7] * init_difficulty(GOOD) + (1 - W[7]) * d2)


def stability_success(d, s, r, g):
    hard = W[15] if g == HARD else 1
    easy = W[16] if g == EASY else 1
    return s * (math.exp(W[8]) * (11 - d) * s ** (-W[9]) * (math.exp(W[10] * (1 - r)) - 1) * hard * easy + 1)


def stability_fail(d, s, r):
    return min(s, W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r)))


def schedule(state, ok, today=None, confident=True, retention=0.9):
    """state: dict con stability, difficulty, last_review (o None si es nueva). Devuelve el nuevo estado."""
    today = today or dt.date.today()
    g = (GOOD if confident else HARD) if ok else AGAIN
    s, d, last = state.get("stability"), state.get("difficulty"), state.get("last_review")
    if not s or not d or not last:
        s, d = init_stability(g), init_difficulty(g)
    else:
        elapsed = (today - dt.date.fromisoformat(last)).days
        r = retrievability(elapsed, s)
        d_new = next_difficulty(d, g)
        if g == AGAIN:
            s = stability_fail(d, s, r)
        elif elapsed == 0:
            s = s * (1 + 0.1 * (g - 2))          # repetida el mismo día: apenas cuenta
        else:
            s = stability_success(d, s, r, g)
        d = d_new
    interval = 1 if g == AGAIN else next_interval(s, retention)
    return {"stability": round(s, 3), "difficulty": round(d, 3), "last_review": today.isoformat(),
            "due": (today + dt.timedelta(days=interval)).isoformat(), "interval": interval,
            "mastered": 1 if (ok and s >= MASTERED_DAYS) else 0}


def migrate():
    """Las falladas del sistema antiguo (cajas 1-3-7-15-30) pasan a FSRS conservando su próximo repaso."""
    c = db.conn()
    cols = [r[1] for r in c.execute("PRAGMA table_info(review)")]
    for col, typ in (("stability", "REAL"), ("difficulty", "REAL"), ("last_review", "TEXT"), ("reps", "INTEGER DEFAULT 0"),
                     ("lapses", "INTEGER DEFAULT 0")):
        if col not in cols:
            c.execute(f"ALTER TABLE review ADD COLUMN {col} {typ}")
    old = [1, 3, 7, 15, 30]
    for r in c.execute("SELECT question_id, box, fails, last_fail FROM review WHERE stability IS NULL").fetchall():
        box = min(r[1] or 0, len(old) - 1)
        c.execute("UPDATE review SET stability=?, difficulty=?, last_review=?, lapses=? WHERE question_id=?",
                  (float(old[box]), _clamp_d(5 + 0.7 * (r[2] or 1)), r[3] or dt.date.today().isoformat(), r[2] or 1, r[0]))
    c.commit()


def review_update(qid, ok, confident=True):
    """Se llama al responder. Las acertadas a la primera no entran en repaso; las falladas sí, y desde entonces siguen FSRS."""
    retention = float(db.load_config().get("target_retention", 0.9))
    r = db.q1("SELECT * FROM review WHERE question_id=?", (qid,))
    if not r:
        if ok:
            return None
        st = schedule({}, False, retention=retention)
        db.run("""INSERT INTO review(question_id,box,due,fails,last_fail,mastered,stability,difficulty,last_review,reps,lapses)
                  VALUES(?,?,?,?,?,0,?,?,?,1,1)""",
               (qid, 0, st["due"], 1, st["last_review"], st["stability"], st["difficulty"], st["last_review"]))
        return st
    if r["mastered"] and ok:
        return None
    st = schedule(r, ok, confident=confident, retention=retention)
    db.run("""UPDATE review SET due=?, stability=?, difficulty=?, last_review=?, mastered=?, reps=COALESCE(reps,0)+1,
              lapses=COALESCE(lapses,0)+?, fails=fails+?, last_fail=CASE WHEN ? THEN last_fail ELSE ? END WHERE question_id=?""",
           (st["due"], st["stability"], st["difficulty"], st["last_review"], st["mastered"],
            0 if ok else 1, 0 if ok else 1, 1 if ok else 0, st["last_review"], qid))
    return st
