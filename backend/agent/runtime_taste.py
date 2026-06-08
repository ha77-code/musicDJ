"""Runtime taste scorer — merges offline catalog, live play stats, and
state.db feedback into composite weights + tags for song selection."""

import json
import math
from datetime import datetime, timedelta, timezone

from . import paths


class RuntimeTasteScorer:
    """Scores + tags + filter reasons for every candidate song.

    Merges four data sources:
      1. Offline catalog (training_songs_top300.json) — weight / play_count
      2. Live listening_stats.json — play counts, last_played timestamps
      3. state.db via DJMemory — skips / likes from both tables
      4. Current playlist.json — source, netease_id, and structure

    Produces:
      - composite_weight: float in roughly [-0.15, 1.2] range
      - tag: one of familiar_anchor / underplayed_local / fresh_discovery /
             recently_played / skipped_recently / unclassified
      - filter_reason: str or None (why a song should be excluded / demoted)
    """

    def __init__(self, memory=None):
        self._memory = memory
        self._stats = None
        self._stats_loaded = False
        self._catalog = None
        self._catalog_loaded = False
        self._catalog_by_id = {}
        self._skipped_ids = None
        self._skipped_loaded = False

    # ── Public API ──

    def score_and_tag(self, song: dict, catalog_weight: float = 0.05,
                      catalog_play_count: int = 0) -> dict:
        """Return {composite_weight, tag, filter_reason} for one song."""
        key = self._unified_key(song)
        stats = self._get_stats_entry(song)
        play_count = stats.get("count", catalog_play_count)
        last_played_ts = stats.get("last_played")
        source = str(song.get("source", "local")).lower()
        netease_id = str(song.get("netease_id", ""))
        is_discovery = (source == "netease_discovery")
        in_catalog = bool(catalog_weight > 0.01 or catalog_play_count > 0)
        in_local_playlist = bool(song.get("path") or netease_id)

        hours_since = self._hours_since(last_played_ts)
        was_skipped = self._was_skipped(key, netease_id)

        # ── Composite weight ──
        freshness = self._freshness_score(hours_since)
        play_density = min(1.0, math.log(play_count + 1) / math.log(30))
        novelty = self._novelty_bonus(play_count, in_local_playlist, in_catalog,
                                      is_discovery)
        catalog_signal = catalog_weight  # already 0-1

        composite = (
            0.40 * catalog_signal
            + 0.15 * play_density
            + 0.15 * freshness
            + 0.10 * novelty
            - (0.15 if was_skipped else 0)
        )

        # ── Tag ──
        tag = self._assign_tag(
            composite=composite,
            play_count=play_count,
            is_discovery=is_discovery,
            in_local=in_local_playlist,
            in_catalog=in_catalog,
            hours_since=hours_since,
            was_skipped=was_skipped,
        )

        # ── Filter reason ──
        filter_reason = self._filter_reason(tag, was_skipped, hours_since)

        return {
            "composite_weight": round(composite, 4),
            "tag": tag,
            "filter_reason": filter_reason,
        }

    def tag_song(self, song: dict, catalog_weight: float = 0.05,
                 catalog_play_count: int = 0) -> str:
        """Convenience: return tag string only."""
        return self.score_and_tag(song, catalog_weight, catalog_play_count)["tag"]

    # ── Internal scoring ──

    @staticmethod
    def _hours_since(timestamp) -> float | None:
        """Return hours since a stored play timestamp.

        listening_stats.json stores ISO strings today, but older/runtime data may
        contain Unix timestamps. Treat malformed or missing values as never
        played instead of breaking song selection.
        """
        if not timestamp:
            return None
        try:
            if isinstance(timestamp, (int, float)):
                played_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            else:
                value = str(timestamp).strip()
                if not value:
                    return None
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                played_at = datetime.fromisoformat(value)
                if played_at.tzinfo is None:
                    played_at = played_at.replace(tzinfo=timezone.utc)
                else:
                    played_at = played_at.astimezone(timezone.utc)
            delta = datetime.now(timezone.utc) - played_at
            return max(0.0, delta.total_seconds() / 3600)
        except Exception:
            return None

    @staticmethod
    def _freshness_score(hours_since: float | None) -> float:
        """Freshness bonus: higher = longer since last play. Penalty for <24h."""
        if hours_since is None:
            return 0.20  # never played
        if hours_since <= 24:
            return -0.20
        if hours_since > 720:
            return 0.15
        if hours_since > 168:
            return 0.10
        if hours_since > 24:
            return 0.05
        return 0.0

    @staticmethod
    def _novelty_bonus(play_count: int, in_local: bool, in_catalog: bool,
                       is_discovery: bool) -> float:
        """Bonus for songs the user hasn't heard much but match their taste."""
        if is_discovery:
            return 0.15
        if play_count == 0 and in_local:
            return 0.15
        if play_count <= 3 and in_local and not in_catalog:
            return 0.08
        return 0.0

    def _assign_tag(self, *, composite: float, play_count: int,
                    is_discovery: bool, in_local: bool, in_catalog: bool,
                    hours_since: float | None, was_skipped: bool) -> str:
        if was_skipped:
            return "skipped_recently"
        if is_discovery:
            return "fresh_discovery"
        if hours_since is not None and hours_since <= 24:
            return "recently_played"
        if composite >= 0.5 and in_catalog:
            return "familiar_anchor"
        if in_local and (play_count <= 3 or (play_count == 0 and not in_catalog)):
            return "underplayed_local"
        if composite >= 0.3:
            return "familiar_anchor"
        if in_local and play_count <= 5:
            return "underplayed_local"
        return "unclassified"

    def _filter_reason(self, tag: str, was_skipped: bool,
                       hours_since: float | None) -> str | None:
        if was_skipped:
            return "skipped_recently"
        if tag == "recently_played":
            return "played_within_24h"
        return None

    # ── Data loading ──

    def _get_stats_entry(self, song: dict) -> dict:
        """Look up a song in listening_stats.json.

        Tries the canonical key first, then the legacy 'local_<fullpath>' format
        for local files that were tracked before the key convention was unified."""
        key = self._unified_key(song)
        if not self._stats_loaded:
            self._load_stats()
        if key in self._stats:
            return self._stats[key]
        # Legacy fallback: older stats may use "local_<fullpath>" for local files
        source = str(song.get("source", "local")).lower()
        netease_id = str(song.get("netease_id", ""))
        if not netease_id and source == "local":
            path = song.get("path", "")
            if path:
                legacy_key = f"{source}_{path}"
                if legacy_key != key and legacy_key in self._stats:
                    return self._stats[legacy_key]
        return {}

    def _load_stats(self):
        self._stats = {}
        try:
            stats_path = paths.stats_path()
            if stats_path.exists():
                with open(stats_path, encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.get("song_plays", {}).items():
                    self._stats[k] = {"count": v.get("count", 0),
                                      "last_played": v.get("last_played")}
        except Exception:
            pass
        self._stats_loaded = True

    def _get_catalog_entry(self, netease_id: str) -> dict | None:
        if not self._catalog_loaded:
            self._load_catalog()
        return self._catalog_by_id.get(str(netease_id))

    def _load_catalog(self):
        self._catalog = []
        self._catalog_by_id = {}
        try:
            path = paths.processed_history_dir() / "training_songs_top300.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._catalog = data.get("songs", [])
                    for s in self._catalog:
                        sid = str(s.get("id", ""))
                        if sid:
                            self._catalog_by_id[sid] = s
        except Exception:
            pass
        self._catalog_loaded = True

    def _was_skipped(self, unified_key: str, netease_id: str = "") -> bool:
        if not self._memory:
            return False
        if not self._skipped_loaded:
            try:
                self._skipped_ids = set(self._memory.get_all_skipped_ids(200))
            except Exception:
                self._skipped_ids = set()
            self._skipped_loaded = True
        if unified_key in self._skipped_ids:
            return True
        if netease_id and netease_id in self._skipped_ids:
            return True
        return False

    # ── Key utilities ──

    @staticmethod
    def _unified_key(song: dict) -> str:
        """Build a consistent song key matching dj_server.get_song_key().

        netease songs:  {source}_{netease_id}
        local files:    {source}_{path}  (full path, stable across processes)
        No netease_id + no path: md5 fallback (rare)."""
        source = str(song.get("source", "local")).lower()
        netease_id = str(song.get("netease_id", ""))
        if netease_id:
            return f"{source}_{netease_id}"
        path = song.get("path", "")
        if path:
            return f"{source}_{path}"
        import hashlib
        fallback = hashlib.md5(
            f"{song.get('title','')}_{song.get('artist','')}".encode()
        ).hexdigest()[:12]
        return f"{source}_{fallback}"

    # ── Bulk helpers for CandidatePoolBuilder ──

    def score_batch(self, songs: list[dict],
                    catalog_by_id: dict | None = None) -> list[dict]:
        """Score a batch of songs, enriching each with composite_weight, tag, filter_reason.
        catalog_by_id maps netease_id → catalog entry with weight/play_count.
        """
        results = []
        for s in songs:
            nid = str(s.get("netease_id", ""))
            cat = (catalog_by_id or {}).get(nid, {})
            cw = cat.get("weight", 0.05)
            pc = cat.get("play_count", 0)
            scored = self.score_and_tag(s, catalog_weight=cw, catalog_play_count=pc)
            s["composite_weight"] = scored["composite_weight"]
            s["_tag"] = scored["tag"]
            s["_filter_reason"] = scored["filter_reason"]
            results.append(s)
        return results
