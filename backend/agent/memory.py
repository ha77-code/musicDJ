"""SQLite-based long-term memory for DJ transitions, sessions, and personality."""

import sqlite3
from datetime import datetime
from pathlib import Path


class DJMemory:
    def __init__(self, db_path: str | Path = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "data" / "state.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS transition_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    session_id INTEGER,
                    current_song_id TEXT,
                    current_song_name TEXT,
                    current_song_artist TEXT,
                    next_song_id TEXT,
                    next_song_name TEXT,
                    next_song_artist TEXT,
                    say_text TEXT,
                    reason TEXT,
                    segue_type TEXT DEFAULT 'smooth',
                    mood TEXT DEFAULT 'chill',
                    action TEXT DEFAULT 'play_next',
                    model_used TEXT,
                    latency_ms INTEGER,
                    user_reaction TEXT DEFAULT NULL,
                    was_skipped INTEGER DEFAULT 0,
                    weather_desc TEXT DEFAULT '',
                    time_period TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS listening_session (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    end_time TEXT,
                    song_count INTEGER DEFAULT 0,
                    total_duration_seconds INTEGER DEFAULT 0,
                    mood_avg TEXT,
                    device_info TEXT
                );

                CREATE TABLE IF NOT EXISTS song_interaction (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    transition_log_id INTEGER,
                    song_id TEXT NOT NULL,
                    song_name TEXT,
                    song_artist TEXT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    reaction TEXT NOT NULL CHECK(reaction IN ('like','skip','listen_full','repeat','none')),
                    context_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS personality_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trait TEXT NOT NULL UNIQUE,
                    value REAL NOT NULL DEFAULT 0.5,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS user_preference (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_transition_ts ON transition_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_transition_session ON transition_log(session_id);
                CREATE INDEX IF NOT EXISTS idx_transition_next ON transition_log(next_song_id);
                CREATE INDEX IF NOT EXISTS idx_interaction_song ON song_interaction(song_id);
            """)

    # ── Transition log ──

    def record_transition(self, data: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO transition_log
                   (session_id, current_song_id, current_song_name, current_song_artist,
                    next_song_id, next_song_name, next_song_artist,
                    say_text, reason, segue_type, mood, action,
                    model_used, latency_ms, weather_desc, time_period)
                   VALUES (?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?,?)""",
                (
                    data.get("session_id"),
                    str(data.get("current_song_id", "")),
                    data.get("current_song_name", ""),
                    data.get("current_song_artist", ""),
                    str(data.get("next_song_id", "")),
                    data.get("next_song_name", ""),
                    data.get("next_song_artist", ""),
                    data.get("say_text", ""),
                    data.get("reason", ""),
                    data.get("segue_type", "smooth"),
                    data.get("mood", "chill"),
                    data.get("action", "play_next"),
                    data.get("model_used", ""),
                    data.get("latency_ms", 0),
                    data.get("weather_desc", ""),
                    data.get("time_period", ""),
                ))
            return cur.lastrowid

    def get_recent_transitions(self, n: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM transition_log ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_session_transitions(self, session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM transition_log WHERE session_id=? ORDER BY id ASC",
                (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_reaction(self, transition_id: int, reaction: str, skipped: bool = False):
        with self._connect() as conn:
            conn.execute(
                "UPDATE transition_log SET user_reaction=?, was_skipped=? WHERE id=?",
                (reaction, 1 if skipped else 0, transition_id))

    # ── Song interactions ──

    def record_song_interaction(self, session_id: int, song_id: str,
                                song_name: str, song_artist: str,
                                reaction: str, context: dict | None = None,
                                transition_log_id: int | None = None):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO song_interaction
                   (session_id, transition_log_id, song_id, song_name, song_artist,
                    reaction, context_json)
                   VALUES (?,?,?,?,?, ?,?)""",
                (session_id, transition_log_id, str(song_id), song_name, song_artist,
                 reaction, str(context) if context else "{}"))

    def get_song_skips(self, song_id: str, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM song_interaction WHERE song_id=? AND reaction='skip' "
                "ORDER BY id DESC LIMIT ?",
                (str(song_id), limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_skipped_artists(self, limit: int = 10) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT song_artist, COUNT(*) as cnt FROM song_interaction "
                "WHERE reaction='skip' GROUP BY song_artist ORDER BY cnt DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [r["song_artist"] for r in rows]

    # ── Personality ──

    def get_personality_state(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT trait, value FROM personality_state").fetchall()
        return {r["trait"]: r["value"] for r in rows}

    def update_personality_trait(self, trait: str, delta: float):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO personality_state (trait, value, updated_at)
                   VALUES (?, MAX(0, MIN(1, ?)), datetime('now','localtime'))
                   ON CONFLICT(trait) DO UPDATE SET
                   value = MAX(0, MIN(1, value + ?)),
                   updated_at = datetime('now','localtime')""",
                (trait, 0.5 + delta, delta))

    def get_transition_history_summary(self, n: int = 5) -> str:
        """Generate a text summary of recent transitions for prompt injection."""
        transitions = self.get_recent_transitions(n)
        if not transitions:
            return ""

        lines = []
        for t in transitions:
            cur = f"{t['current_song_artist']} - {t['current_song_name']}"
            nxt = f"{t['next_song_artist']} - {t['next_song_name']}"
            say = t["say_text"] or ""
            reaction = ""
            if t.get("was_skipped"):
                reaction = " [被跳过]"
            elif t.get("user_reaction") == "like":
                reaction = " [喜欢]"
            lines.append(f"  {cur} → {nxt}：\"{say}\"{reaction}")

        return "\n".join(lines)

    # ── Stats ──

    def get_transition_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM transition_log").fetchone()[0]

    def get_session_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM listening_session").fetchone()[0]

    def get_most_used_segue(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT segue_type, COUNT(*) as cnt FROM transition_log "
                "GROUP BY segue_type ORDER BY cnt DESC LIMIT 1"
            ).fetchone()
        return row["segue_type"] if row else "smooth"

    def get_most_used_mood(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mood, COUNT(*) as cnt FROM transition_log "
                "GROUP BY mood ORDER BY cnt DESC LIMIT 1"
            ).fetchone()
        return row["mood"] if row else "chill"

    def get_stats_summary(self) -> dict:
        return {
            "total_transitions": self.get_transition_count(),
            "total_sessions": self.get_session_count(),
            "top_segue": self.get_most_used_segue(),
            "top_mood": self.get_most_used_mood(),
            "personality": self.get_personality_state(),
        }
