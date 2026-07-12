"""
Diski Logue — Storage Layer
SQLite persistence for teams, matches (history), predictions, and results.
This is the backbone of the continuous-learning loop: every prediction is
stored, then reconciled against the actual result once the match is played.
"""
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "diski_logue.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    competition TEXT,
    elo         REAL DEFAULT 1500.0
);

CREATE TABLE IF NOT EXISTS matches (
    match_id     TEXT PRIMARY KEY,
    competition  TEXT,
    date         TEXT,
    home_team_id TEXT,
    away_team_id TEXT,
    home_goals   INTEGER,
    away_goals   INTEGER,
    status       TEXT           -- SCHEDULED | FINISHED
);

CREATE TABLE IF NOT EXISTS predictions (
    match_id       TEXT PRIMARY KEY,
    created_at     TEXT,
    payload_json   TEXT,        -- full prediction object (probabilities, scorelines, markets, explanation)
    actual_home    INTEGER,
    actual_away    INTEGER,
    outcome_correct INTEGER,    -- 1/0/NULL until match is scored
    brier_score    REAL
);

CREATE TABLE IF NOT EXISTS scorers (
    team_id     TEXT,
    player_name TEXT,
    goals       INTEGER,
    PRIMARY KEY (team_id, player_name)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_team(team_id, name, competition, elo=1500.0):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO teams (team_id, name, competition, elo)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_id) DO UPDATE SET name=excluded.name,
                    competition=excluded.competition""",
            (team_id, name, competition, elo),
        )


def get_team_elo(team_id, default=1500.0):
    with get_conn() as conn:
        row = conn.execute("SELECT elo FROM teams WHERE team_id=?", (team_id,)).fetchone()
        return row["elo"] if row else default


def set_team_elo(team_id, elo):
    with get_conn() as conn:
        conn.execute("UPDATE teams SET elo=? WHERE team_id=?", (elo, team_id))


def upsert_match(match_id, competition, date, home_id, away_id,
                  home_goals=None, away_goals=None, status="SCHEDULED"):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO matches (match_id, competition, date, home_team_id,
                    away_team_id, home_goals, away_goals, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(match_id) DO UPDATE SET
                    home_goals=excluded.home_goals,
                    away_goals=excluded.away_goals,
                    status=excluded.status""",
            (match_id, competition, date, home_id, away_id, home_goals, away_goals, status),
        )


def get_team_recent_matches(team_id, limit=10):
    """Finished matches involving this team, most recent first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM matches
               WHERE (home_team_id=? OR away_team_id=?) AND status='FINISHED'
               ORDER BY date DESC LIMIT ?""",
            (team_id, team_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_head_to_head(home_id, away_id, limit=10):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM matches
               WHERE status='FINISHED' AND
                     ((home_team_id=? AND away_team_id=?) OR
                      (home_team_id=? AND away_team_id=?))
               ORDER BY date DESC LIMIT ?""",
            (home_id, away_id, away_id, home_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def save_prediction(match_id, payload: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO predictions (match_id, created_at, payload_json)
               VALUES (?, datetime('now'), ?)
               ON CONFLICT(match_id) DO UPDATE SET payload_json=excluded.payload_json,
                    created_at=datetime('now')""",
            (match_id, json.dumps(payload)),
        )


def record_result_and_score(match_id, actual_home, actual_away):
    """Reconcile a stored prediction with the real result. Computes:
       - outcome_correct (did we call W/D/L right?)
       - brier_score (probability calibration error on the outcome)
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json FROM predictions WHERE match_id=?", (match_id,)
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        probs = payload["outcome_probabilities"]  # {home, draw, away}

        if actual_home > actual_away:
            actual_outcome = "home"
        elif actual_home < actual_away:
            actual_outcome = "away"
        else:
            actual_outcome = "draw"

        predicted_outcome = max(probs, key=probs.get)
        outcome_correct = int(predicted_outcome == actual_outcome)

        # Brier score across the 3-way outcome vector (0 = perfect, 2 = worst)
        targets = {"home": 0.0, "draw": 0.0, "away": 0.0}
        targets[actual_outcome] = 1.0
        brier = sum((probs[k] - targets[k]) ** 2 for k in targets)

        conn.execute(
            """UPDATE predictions SET actual_home=?, actual_away=?,
                    outcome_correct=?, brier_score=? WHERE match_id=?""",
            (actual_home, actual_away, outcome_correct, brier, match_id),
        )
        return {"outcome_correct": bool(outcome_correct), "brier_score": brier}


def dashboard_stats():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT outcome_correct, brier_score FROM predictions
               WHERE outcome_correct IS NOT NULL"""
        ).fetchall()
        n = len(rows)
        if n == 0:
            return {"n_scored_predictions": 0}
        acc = sum(r["outcome_correct"] for r in rows) / n
        avg_brier = sum(r["brier_score"] for r in rows) / n
        return {
            "n_scored_predictions": n,
            "outcome_accuracy": round(acc, 4),
            "avg_brier_score": round(avg_brier, 4),
        }
