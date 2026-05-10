"""Music discovery — search Netease cloud catalog for fresh song recommendations.

Generates search queries from user taste profile + current context,
then fetches matching songs from Netease API. Results are cached per-session
to avoid redundant API calls.
"""

import json
import random
import time
from pathlib import Path

import requests


class MusicDiscovery:
    """Searches Netease cloud music catalog for songs matching user taste + context.

    Unlike the local playlist (songs the user already owns), this opens up
    the entire Netease catalog for the DJ to recommend from — creating a
    genuine "radio discovery" experience.
    """

    def __init__(self, config: dict):
        netease = config.get("netease", {})
        self.api_host = netease.get("api_host", "http://localhost:3000")
        self.cookie = netease.get("cookie", "")
        self.enabled = netease.get("enabled", True)

        # Cache: query → results, expires after session
        self._cache: dict[str, list[dict]] = {}
        self._detail_cache: dict[str, dict] = {}
        self._session_queries: set = set()  # track queries used this session

    # ── Public API ─────────────────────────────────────

    def discover(self, taste_profile: dict, context: dict,
                 count: int = 10) -> list[dict]:
        """Discover songs matching taste profile + current context.

        Args:
            taste_profile: Output of build_taste_profile_search()
            context: {period, weather_desc, user_activity, is_weekend}
            count: Max songs to return

        Returns list of song dicts with: title, artist, netease_id,
            album, cover_url, source="netease_discovery"
        """
        if not self.enabled or not self._check_netease():
            return []

        queries = self._generate_queries(taste_profile, context)
        all_songs = []

        for query in queries[:3]:  # max 3 queries to stay fast
            songs = self._search_cached(query, limit=8)
            all_songs.extend(songs)

        if not all_songs:
            return []

        # Deduplicate by netease_id
        seen = set()
        unique = []
        for s in all_songs:
            sid = s.get("netease_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                unique.append(s)

        # Shuffle and limit
        random.shuffle(unique)
        return unique[:count]

    def get_song_detail(self, netease_id: str) -> dict | None:
        """Fetch rich song details: album, publish year, lyrics snippet."""
        if netease_id in self._detail_cache:
            return self._detail_cache[netease_id]

        detail = self._fetch_song_detail(netease_id)
        if detail:
            self._detail_cache[netease_id] = detail
        return detail

    def get_song_lyric_snippet(self, netease_id: str, max_lines: int = 4) -> str:
        """Fetch a short lyric snippet for the DJ to reference."""
        try:
            resp = self._api_get("/lyric", {"id": netease_id})
            lrc = resp.get("lrc", {})
            if lrc and lrc.get("lyric"):
                lines = [l.strip() for l in lrc["lyric"].split("\n")
                        if l.strip() and not l.strip().startswith("[")]
                return " / ".join(lines[:max_lines])
        except Exception:
            pass
        return ""

    # ── Query Generation ───────────────────────────────

    def _generate_queries(self, taste: dict, context: dict) -> list[str]:
        """Build search queries from taste profile + situational context.

        Queries are ranked: artist-based first (highest signal), then genre+mood.
        """
        queries = []

        # 1. Artist-based: top artists from taste profile
        top_artists = taste.get("top_artists", [])
        for artist in top_artists[:3]:
            queries.append(artist)

        # 2. Genre + mood combination
        genres = taste.get("genres", [])
        period = context.get("period", "")
        weather = context.get("weather_desc", "")
        activity = context.get("user_activity", "")

        # Period-based genre picks
        period_genre_map = {
            "深夜": ["氛围", "后摇", "独立", "R&B", "民谣"],
            "凌晨": ["钢琴", "氛围", "后摇", "轻音乐"],
            "早晨": ["独立流行", "轻音乐", "City Pop", "R&B"],
            "上午": ["后摇", "Lo-fi", "轻音乐", "爵士"],
            "下午": ["独立", "流行", "R&B", "电子"],
            "傍晚": ["City Pop", "流行", "R&B", "放克"],
        }
        period_genres = period_genre_map.get(period, ["流行", "独立"])

        # Weather modifier
        if weather and any(w in weather for w in ["雨", "雪"]):
            mood_keywords = ["安静", "氛围", "治愈", "温暖"]
        elif weather and "晴" in weather:
            mood_keywords = ["轻快", "清新", "活力"]
        else:
            mood_keywords = ["陪伴", "沉浸"]

        # Combine genre + mood for richer queries
        picked_genre = period_genres[0] if period_genres else "流行"
        picked_mood = mood_keywords[0] if mood_keywords else "放松"
        queries.append(f"{picked_genre} {picked_mood}")

        # 3. Activity-specific
        if activity:
            activity_map = {
                "studying": "学习 专注 纯音乐",
                "working": "工作 轻音乐 后摇",
                "working_out": "运动 电子 节奏",
                "before_sleep": "睡前 安静 钢琴",
                "commuting": "通勤 流行 轻松",
            }
            act_query = activity_map.get(activity)
            if act_query:
                queries.append(act_query)

        # 4. Genre from taste profile
        if genres:
            queries.append(f"{genres[0]} 精选")

        # Filter duplicates and queries already used this session
        fresh = []
        for q in queries:
            if q not in self._session_queries:
                fresh.append(q)
                self._session_queries.add(q)
        return fresh

    # ── Netease API ────────────────────────────────────

    def _check_netease(self) -> bool:
        try:
            resp = requests.get(f"{self.api_host}/search?keywords=test&limit=1",
                               timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _search_cached(self, query: str, limit: int = 8) -> list[dict]:
        if query in self._cache:
            return self._cache[query]

        try:
            songs = self._api_search(query, limit)
            self._cache[query] = songs
            return songs
        except Exception:
            return []

    def _api_search(self, keywords: str, limit: int = 8) -> list[dict]:
        resp = self._api_get("/search", {
            "keywords": keywords,
            "limit": limit,
            "type": 1,  # song
        })
        result = resp.get("result", {})
        songs_data = result.get("songs", [])
        formatted = []
        for s in songs_data:
            artists = " / ".join(a.get("name", "") for a in s.get("artists", []))
            formatted.append({
                "title": s.get("name", "?"),
                "artist": artists,
                "netease_id": str(s.get("id", "")),
                "album": s.get("album", {}).get("name", ""),
                "cover_url": s.get("album", {}).get("picUrl", ""),
                "duration": s.get("duration", 0) // 1000,
                "source": "netease_discovery",
                "search_query": keywords,
            })
        return formatted

    def _fetch_song_detail(self, netease_id: str) -> dict | None:
        try:
            resp = self._api_get("/song/detail", {"ids": str(netease_id)})
            songs = resp.get("songs", [])
            if not songs:
                return None
            s = songs[0]
            artists = " / ".join(a.get("name", "") for a in s.get("ar", []))
            return {
                "title": s.get("name", ""),
                "artist": artists,
                "album_name": s.get("al", {}).get("name", ""),
                "album_pic": s.get("al", {}).get("picUrl", ""),
                "publish_time": s.get("publishTime", 0),
                "duration_ms": s.get("dt", 0),
            }
        except Exception:
            return None

    def _api_get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.api_host}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return {"code": resp.status_code}
