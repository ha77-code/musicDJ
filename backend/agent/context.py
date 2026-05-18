"""Context assembly from training data, environment, and playlist state."""

import json
import random
from datetime import datetime, date
from pathlib import Path

from .paths import data_dir, processed_history_dir, raw_history_dir, user_profile_dir

DATA_DIR = data_dir()
PROCESSED_DIR = processed_history_dir()
RAW_DIR = raw_history_dir()
USER_PROFILE_DIR = user_profile_dir()


class DJContext:
    def __init__(self, memory=None):
        self._taste_summary_cache = None
        self._top_songs_cache = None
        self._top_artists_cache = None
        self._catalog_cache = None
        self._profile_cache = None
        self._profile_mtime = None
        self.memory = memory  # DJMemory instance for skip/streak lookups

    def get_time_info(self) -> dict:
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        if hour < 6:
            period = "凌晨"
            activity_hint = "深度安静时间，适合氛围、后摇、钢琴独奏"
        elif hour < 9:
            period = "早晨"
            activity_hint = "刚起床不久，需要轻快积极的音乐唤醒"
        elif hour < 12:
            period = "上午"
            activity_hint = "工作/学习黄金时间，需要专注背景音乐"
        elif hour < 14:
            period = "中午"
            activity_hint = "午休放松时间，轻松不费脑的音乐"
        elif hour < 18:
            period = "下午"
            activity_hint = "下午工作延续，需要节奏但不吵闹的音乐"
        elif hour < 21:
            period = "傍晚"
            activity_hint = "一天结束放松，随意切换风格"
        elif hour < 24:
            period = "深夜"
            activity_hint = "核心听歌时间，情绪最敏感，需要陪伴感和沉浸感"
        else:
            period = "凌晨"
            activity_hint = "深度安静时间，适合氛围、后摇、钢琴独奏"

        return {
            "time_str": f"{weekday_names[weekday]} {period} {now.strftime('%H:%M')}",
            "period": period,
            "hour": hour,
            "weekday": weekday,
            "weekday_name": weekday_names[weekday],
            "is_weekend": weekday >= 5,
            "activity_hint": activity_hint,
        }

    # ── User profile files (taste.md / routines.md / mood-rules.md) ──

    def get_user_profile_context(self) -> str:
        """Load user profile markdown files and return concatenated context."""
        files = {
            "taste.md": "【用户音乐口味】",
            "routines.md": "【用户日常作息】",
            "mood-rules.md": "【情绪场景规则】",
        }
        parts = []
        try:
            for fname, label in files.items():
                p = USER_PROFILE_DIR / fname
                if p.exists():
                    mtime = p.stat().st_mtime
                    content = p.read_text(encoding="utf-8").strip()
                    if content:
                        parts.append(f"{label}\n{content}")
        except Exception:
            pass

        if parts:
            return "\n\n".join(parts)
        return ""

    # ── Memory-aware helpers ──

    def get_skipped_summary(self, n: int = 5) -> str:
        """Summarize recently skipped songs/artists for the AI to avoid."""
        if not self.memory:
            return ""

        transitions = self.memory.get_recent_transitions(20)
        skipped = [t for t in transitions if t.get("was_skipped")]
        if not skipped:
            return ""

        lines = []
        for t in skipped[-n:]:
            lines.append(
                f"  {t.get('next_song_artist', '?')} - {t.get('next_song_name', '?')}"
            )
        return "最近被跳过的歌（避免再选类似）：\n" + "\n".join(lines)

    def get_artist_streak_info(self, n: int = 10) -> str:
        """Detect if same artist has been playing too much."""
        if not self.memory:
            return ""

        transitions = self.memory.get_recent_transitions(n)
        artists = [t.get("next_song_artist", "") for t in transitions if t.get("next_song_artist")]
        if not artists:
            return ""

        from collections import Counter
        counts = Counter(artists)
        top = counts.most_common(3)
        if top and top[0][1] >= 3:
            return f"最近播放艺人倾向：{'、'.join(f'{a}({c}次)' for a, c in top)}"
        return ""

    def is_first_today(self) -> bool:
        """Check if this is the first session of the day."""
        if not self.memory:
            return True
        transitions = self.memory.get_recent_transitions(1)
        if not transitions:
            return True
        last_ts = transitions[0].get("timestamp", "")
        if not last_ts:
            return True
        try:
            last_date = datetime.fromisoformat(last_ts).date()
            return last_date < date.today()
        except (ValueError, TypeError):
            return True

    # ── Existing methods ──

    def get_weather_str(self, weather_data: dict | None) -> str:
        if not weather_data:
            return ""
        desc = weather_data.get("description", "")
        temp = weather_data.get("temp", "")
        if desc and temp:
            return f"{desc} {temp}°C"
        return desc or ""

    def get_music_taste_summary(self, force_reload: bool = False) -> str:
        if self._taste_summary_cache and not force_reload:
            return self._taste_summary_cache

        summary_parts = []

        # Load training summary
        summary = self._load_json(PROCESSED_DIR / "training_summary.json")
        if summary:
            summary_parts.append(f"曲库共{summary.get('total_songs', '?')}首，"
                                 f"核心歌曲{summary.get('tiers', {}).get('core', '?')}首，"
                                 f"喜欢{summary.get('tiers', {}).get('liked', '?')}首。")

        # Top songs — these are what the listener actually listens to
        top_songs = self.get_top_songs(15)
        if top_songs:
            song_lines = []
            for s in top_songs[:12]:
                plays = s.get("play_count", 0)
                name = s.get("name", "?")
                artist = s.get("artist", "?")
                song_lines.append(f"  - {name} / {artist}")
            summary_parts.append("播放次数最多的歌曲（注意：次数多=喜欢这首歌，不能推断喜欢这个歌手）：\n" + "\n".join(song_lines))

        # Yearly listening trend
        year_reports = self._load_json(RAW_DIR / "year_report_2025.json")
        if year_reports:
            items = year_reports.get("data", {}).get("yearItems", [])
            recent = [i for i in items if i.get("year", 0) >= 2023]
            if recent:
                trend = "、".join(f"{i['year']}年{i['playNum']}首" for i in recent[:3])
                summary_parts.append(f"近年听歌趋势：{trend}。")

        # Total listening
        total_data = self._load_json(RAW_DIR / "total.json")
        if total_data:
            total_sec = total_data.get("data", {}).get("totalDuration", 0)
            total_hr = total_sec // 3600
            summary_parts.append(f"累计听歌约{total_hr}小时。")

        self._taste_summary_cache = "\n".join(summary_parts)
        return self._taste_summary_cache

    def get_top_songs(self, n: int = 15) -> list[dict]:
        if self._top_songs_cache:
            return self._top_songs_cache[:n]

        songs = self._load_json(PROCESSED_DIR / "training_songs_top300.json")
        if songs:
            self._top_songs_cache = songs.get("songs", [])
        else:
            self._top_songs_cache = []
        return self._top_songs_cache[:n]

    def get_top_artists(self, n: int = 10) -> list[tuple]:
        if self._top_artists_cache:
            return self._top_artists_cache[:n]

        artists = self._load_json(PROCESSED_DIR / "artist_stats.json")
        if artists:
            self._top_artists_cache = [
                (a["name"], a["plays"], a["songs"])
                for a in artists.get("artists", [])
            ]
        else:
            self._top_artists_cache = []
        return self._top_artists_cache[:n]

    def get_song_weight(self, song_name: str, artist: str) -> float:
        """Look up a song's weight in the user's catalog."""
        songs = self.get_top_songs(300)
        for s in songs:
            if s.get("name") == song_name and artist in s.get("artist", ""):
                return s.get("weight", 0)
        return 0.0

    def build_context_window(self, current_song: dict, next_song: dict,
                             weather_data: dict | None = None,
                             history: list[str] | None = None) -> dict:
        """Assemble the full context for a transition request."""
        time_info = self.get_time_info()
        weather_str = self.get_weather_str(weather_data)
        taste_summary = self.get_music_taste_summary()
        profile_context = self.get_user_profile_context()
        skipped_summary = self.get_skipped_summary()
        artist_streak = self.get_artist_streak_info()

        cur = f"{current_song.get('artist', '?')} - {current_song.get('title', '?')}"
        nxt = f"{next_song.get('artist', '?')} - {next_song.get('title', '?')}"

        tags = " ".join(next_song.get("tags", [])) if next_song.get("tags") else ""

        history_str = ""
        if history:
            history_str = "\n".join(f"  {h}" for h in history[-5:])

        # Build listener state
        state_parts = []
        cur_weight = self.get_song_weight(
            next_song.get("title", ""), next_song.get("artist", ""))
        if cur_weight > 0.5:
            state_parts.append("听众非常喜欢这首歌")
        elif cur_weight > 0.1:
            state_parts.append("听众对这首歌有一定偏好")

        state_parts.append(f"当前时间：{time_info['time_str']}")
        state_parts.append(time_info["activity_hint"])
        if time_info["is_weekend"]:
            state_parts.append("今天是周末，听众可能比较放松")

        listener_state = "；".join(state_parts) if state_parts else "无特殊状态"

        return {
            "time_str": time_info["time_str"],
            "period": time_info["period"],
            "hour": time_info["hour"],
            "weekday_name": time_info["weekday_name"],
            "activity_hint": time_info["activity_hint"],
            "is_weekend": time_info["is_weekend"],
            "weather_str": weather_str,
            "current_song_str": cur,
            "next_song_str": nxt,
            "tags": tags,
            "history_str": history_str,
            "taste_summary": taste_summary,
            "profile_context": profile_context,
            "skipped_summary": skipped_summary,
            "artist_streak": artist_streak,
            "listener_state": listener_state,
        }

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None
