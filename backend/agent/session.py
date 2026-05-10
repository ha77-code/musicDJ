"""Session management for DJ listening sessions."""

from datetime import datetime
from pathlib import Path


class SessionManager:
    def __init__(self, memory):
        self.memory = memory
        self._active_id = None

    def start_session(self, device_info: str = "") -> int:
        with self.memory._connect() as conn:
            cur = conn.execute(
                "INSERT INTO listening_session (start_time, device_info) VALUES (?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), device_info))
            self._active_id = cur.lastrowid
            return self._active_id

    def end_session(self, session_id: int | None = None):
        sid = session_id or self._active_id
        if not sid:
            return
        with self.memory._connect() as conn:
            # Update song count and duration from transitions
            rows = conn.execute(
                "SELECT COUNT(*) as cnt FROM transition_log WHERE session_id=?", (sid,)
            ).fetchone()
            song_count = rows["cnt"] if rows else 0

            conn.execute(
                "UPDATE listening_session SET end_time=?, song_count=? WHERE id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), song_count, sid))

        self._active_id = None

    def get_active_session_id(self) -> int | None:
        return self._active_id

    def get_session_stats(self, session_id: int | None = None) -> dict:
        sid = session_id or self._active_id
        if not sid:
            return {}
        with self.memory._connect() as conn:
            session = conn.execute(
                "SELECT * FROM listening_session WHERE id=?", (sid,)
            ).fetchone()
            if not session:
                return {}

            transitions = conn.execute(
                "SELECT * FROM transition_log WHERE session_id=? ORDER BY id ASC",
                (sid,)
            ).fetchall()

            moods = [t["mood"] for t in transitions if t["mood"]]

            return {
                "id": session["id"],
                "start_time": session["start_time"],
                "end_time": session["end_time"],
                "song_count": session["song_count"],
                "transitions": len(transitions),
                "moods": moods,
            }
