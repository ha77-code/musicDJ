"""Candidate pool builder — selects ~15 songs for the LLM to choose from.

Mixes two sources:
  - Local playlist: songs the user already owns (familiar)
  - Netease discovery: fresh recommendations from the cloud catalog

This gives the DJ both comfort and discovery — like a real radio station.
"""

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROCESSED_DIR = DATA_DIR / "listening_history" / "processed"


class CandidatePoolBuilder:
    def __init__(self, pool_size: int = 15):
        self.pool_size = pool_size
        self._catalog_cache = None

    def build_pool(
        self,
        current_song_id: str,
        playlist: list[dict],
        recently_played_ids: list[str],
        skipped_ids: list[str],
        user_activity: str,
        time_period: str,
        is_weekend: bool,
        weather_desc: str,
        discovery_songs: list[dict] | None = None,
        discovery_ratio: float = 0.7,
        recent_title_artists: set | None = None,
    ) -> list[dict]:
        """Build a diverse candidate pool mixing local and discovery songs.

        Args:
            discovery_songs: Results from MusicDiscovery.discover()
            discovery_ratio: Target ratio of discovery songs (0.0-1.0)
        """
        catalog = self._load_catalog()
        catalog_by_id = {str(s.get("id", "")): s for s in catalog} if catalog else {}

        # ── Score local playlist songs ──
        local_candidates = []
        recent_ta = recent_title_artists or set()
        for i, song in enumerate(playlist):
            sid = str(song.get("netease_id") or song.get("path", ""))
            if sid == current_song_id:
                continue
            if sid in recently_played_ids:
                continue
            if sid in skipped_ids:
                continue
            # Hard dedup by title+artist
            sa = (song.get("title", "").strip().lower(),
                  song.get("artist", "").strip().lower())
            if sa[0] and sa[1] and sa in recent_ta:
                continue

            taste = catalog_by_id.get(sid, {})
            weight = taste.get("weight", 0.05)
            play_count = taste.get("play_count", 0)
            hint = self._build_hint(weight, play_count, song, taste)
            local_candidates.append((weight, i, song, play_count, hint, "local"))

        # Sort by weight, diversify artists
        local_candidates.sort(key=lambda x: x[0], reverse=True)
        local_pool = self._diversify(local_candidates, self.pool_size)

        # ── Score discovery songs ──
        discovery_pool = []
        if discovery_songs:
            for ds in discovery_songs:
                sid = str(ds.get("netease_id", ""))
                if sid == current_song_id or sid in recently_played_ids or sid in skipped_ids:
                    continue
                # Hard dedup by title+artist
                sa = (ds.get("title", "").strip().lower(),
                      ds.get("artist", "").strip().lower())
                if sa[0] and sa[1] and sa in recent_ta:
                    continue
                search_q = ds.get("search_query", "")
                hint = f"为你发现 · {search_q}" if search_q else "新歌推荐"
                discovery_pool.append({
                    "pool_index": 0,  # assigned later
                    "playlist_index": -1,  # not in local playlist
                    "title": ds["title"],
                    "artist": ds["artist"],
                    "netease_id": sid,
                    "path": "",
                    "source": "netease_discovery",
                    "weight": 0.3,  # moderate weight — fresh but unproven
                    "play_count": 0,
                    "hint": hint,
                    "cover_url": ds.get("cover_url", ""),
                })

        # ── Mix local + discovery ──
        target_discovery = max(1, int(self.pool_size * discovery_ratio))
        discovery_count = min(target_discovery, len(discovery_pool))
        local_count = min(self.pool_size - discovery_count, len(local_pool))

        pool = []
        # Add discovery songs first (fresh first)
        if discovery_pool:
            random.shuffle(discovery_pool)
            pool.extend(discovery_pool[:discovery_count])
        # Add local songs
        pool.extend(local_pool[:local_count])

        # Shuffle to avoid positional bias
        random.shuffle(pool)

        # Assign pool indices
        for pi, entry in enumerate(pool):
            entry["pool_index"] = pi + 1

        return pool

    def lookup_candidate(self, pool: list[dict], pool_index: int) -> dict | None:
        for c in pool:
            if c["pool_index"] == pool_index:
                return c
        return None

    def format_pool_for_prompt(self, pool: list[dict]) -> str:
        lines = []
        for c in pool:
            source_label = "🎵 你的歌单" if c["source"] != "netease_discovery" else "🔍 为你发现"
            line = f"{c['pool_index']}. {c['artist']} — {c['title']} [{source_label}]"
            if c["hint"]:
                line += f" — {c['hint']}"
            lines.append(line)
        return "\n".join(lines)

    # ── Internal ──

    @staticmethod
    def _diversify(candidates: list, max_count: int) -> list[dict]:
        """Pick top candidates while ensuring max 2 per artist."""
        pool = []
        artist_counts = {}
        for weight, idx, song, pc, hint, source in candidates:
            artist = song.get("artist", "")
            if artist_counts.get(artist, 0) >= 2:
                continue
            pool.append({
                "pool_index": 0,
                "playlist_index": idx,
                "title": song.get("title", "?"),
                "artist": artist,
                "netease_id": song.get("netease_id", ""),
                "path": song.get("path", ""),
                "source": song.get("source", "local"),
                "cover_url": song.get("cover", "") or song.get("cover_url", ""),
                "album_name": song.get("album", ""),
                "weight": round(weight, 2),
                "play_count": pc,
                "hint": hint,
            })
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
            if len(pool) >= max_count:
                break
        return pool

    @staticmethod
    def _build_hint(weight: float, play_count: int, song: dict, taste: dict) -> str:
        hints = []
        if weight > 0.8:
            hints.append("你的神曲")
        elif weight > 0.4:
            hints.append("心头好")
        elif weight > 0.1:
            hints.append("偶尔听")
        else:
            hints.append("一首老歌")
        return "，".join(hints)

    def _load_catalog(self):
        if self._catalog_cache is not None:
            return self._catalog_cache
        try:
            path = PROCESSED_DIR / "training_songs_top300.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._catalog_cache = data.get("songs", [])
                    return self._catalog_cache
        except Exception:
            pass
        self._catalog_cache = []
        return self._catalog_cache
