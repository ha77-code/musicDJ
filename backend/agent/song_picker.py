"""Candidate pool builder — true bucket sampling driven by RuntimeTasteScorer tags.

Three buckets populated from scorer tags:
  - familiar_anchor: songs the user really knows and likes
  - underplayed_local: songs in the local playlist but rarely/never played
  - fresh_discovery: Netease discovery songs or songs not in local catalog

Default mix ratios: familiar 15-25% / underplayed 25-35% / discovery 45-60%.
Opening / exploration contexts raise discovery share to 55-65%.
Favor-familiar contexts raise familiar share to 35-45%.
"""

import json
import random
from pathlib import Path

from .runtime_taste import RuntimeTasteScorer

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROCESSED_DIR = DATA_DIR / "listening_history" / "processed"


class CandidatePoolBuilder:
    def __init__(self, pool_size: int = 15, scorer: RuntimeTasteScorer | None = None):
        self.pool_size = pool_size
        self.scorer = scorer or RuntimeTasteScorer()
        self._catalog_cache = None

    def set_scorer(self, scorer: RuntimeTasteScorer):
        self.scorer = scorer

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
        opening_or_explore: bool = False,
        favor_familiar: bool = False,
    ) -> list[dict]:
        """Build a diverse candidate pool using tag-driven bucket sampling.

        Uses RuntimeTasteScorer to assign composite weights and tags, then
        samples from three buckets (familiar / underplayed_local / discovery)
        with configurable ratios.
        """
        catalog = self._load_catalog()
        catalog_by_id = {str(s.get("id", "")): s for s in catalog} if catalog else {}
        recent_ta = recent_title_artists or set()
        exclude_ids = {current_song_id} | set(recently_played_ids) | set(skipped_ids)
        discovery_songs = discovery_songs or []

        # ── Score all local playlist songs ──
        scored_local = []
        for i, song in enumerate(playlist):
            sid = str(song.get("netease_id") or song.get("path", ""))
            if sid in exclude_ids:
                continue
            sa_key = (song.get("title", "").strip().lower(),
                      song.get("artist", "").strip().lower())
            if sa_key[0] and sa_key[1] and sa_key in recent_ta:
                continue

            nid = str(song.get("netease_id", ""))
            cat = catalog_by_id.get(nid, {})
            cw = cat.get("weight", 0.05)
            cpc = cat.get("play_count", 0)
            scored = self.scorer.score_and_tag(song, catalog_weight=cw,
                                               catalog_play_count=cpc)
            song["_composite"] = scored["composite_weight"]
            song["_tag"] = scored["tag"]
            song["_filter_reason"] = scored["filter_reason"]
            song["_pidx"] = i  # original playlist index
            scored_local.append(song)

        # ── Score discovery songs ──
        scored_discovery = []
        for ds in discovery_songs:
            sid = str(ds.get("netease_id", ""))
            if sid in exclude_ids:
                continue
            sa_key = (ds.get("title", "").strip().lower(),
                      ds.get("artist", "").strip().lower())
            if sa_key[0] and sa_key[1] and sa_key in recent_ta:
                continue
            nid = str(ds.get("netease_id", ""))
            scored = self.scorer.score_and_tag(ds, catalog_weight=0.3,
                                               catalog_play_count=0)
            ds["_composite"] = scored["composite_weight"]
            ds["_tag"] = scored["tag"]
            ds["_filter_reason"] = scored["filter_reason"]
            ds["_pidx"] = -1
            scored_discovery.append(ds)

        # ── Partition into buckets by tag ──
        familiar = []
        underplayed = []
        discovery_bucket = []

        for s in scored_local:
            tag = s.get("_tag", "")
            if s.get("_filter_reason"):  # skip penalized
                continue
            if tag == "familiar_anchor":
                familiar.append(s)
            elif tag in ("underplayed_local", "unclassified"):
                underplayed.append(s)
            else:
                # recently_played / skipped don't enter pool
                pass

        for s in scored_discovery:
            tag = s.get("_tag", "")
            if s.get("_filter_reason"):
                continue
            if tag in ("fresh_discovery",):
                discovery_bucket.append(s)
            elif tag in ("underplayed_local", "unclassified"):
                underplayed.append(s)
            else:
                pass

        # ── Bucket ratio selection ──
        if favor_familiar:
            fam_pct, und_pct, disc_pct = 0.40, 0.32, 0.28
        elif opening_or_explore:
            fam_pct, und_pct, disc_pct = 0.12, 0.28, 0.60
        else:
            fam_pct, und_pct, disc_pct = 0.20, 0.30, 0.50

        n_fam = min(len(familiar), max(1, int(self.pool_size * fam_pct)))
        n_und = min(len(underplayed), max(1, int(self.pool_size * und_pct)))
        n_disc = self.pool_size - n_fam - n_und
        n_disc = min(len(discovery_bucket), max(n_disc, 0))

        # Fill shortfall from adjacent buckets
        if n_disc < max(1, int(self.pool_size * disc_pct)):
            extra = max(1, int(self.pool_size * disc_pct)) - n_disc
            add_und = min(len(underplayed) - n_und, extra)
            n_und += add_und
            extra -= add_und
            if extra > 0:
                n_fam = min(len(familiar), n_fam + extra)
        if n_und < max(1, int(self.pool_size * und_pct)):
            extra = max(1, int(self.pool_size * und_pct)) - n_und
            add_fam = min(len(familiar) - n_fam, extra)
            n_fam += add_fam

        # ── Weighted random sampling from each bucket ──
        pool = []

        if familiar and n_fam > 0:
            sampled = self._weighted_sample(familiar, n_fam,
                                            weight_key="_composite")
            for s in sampled:
                pool.append(self._make_entry(s["_pidx"], s,
                                             s.get("play_count", 0),
                                             s["_composite"],
                                             self._build_hint(s["_composite"],
                                                              s.get("play_count", 0),
                                                              s),
                                             "familiar"))

        if underplayed and n_und > 0:
            sampled = self._weighted_sample(underplayed, n_und,
                                            weight_key="_composite")
            for s in sampled:
                pool.append(self._make_entry(s["_pidx"], s,
                                             s.get("play_count", 0),
                                             s["_composite"],
                                             self._build_hint(s["_composite"],
                                                              s.get("play_count", 0),
                                                              s),
                                             "underplayed_local"))

        if discovery_bucket and n_disc > 0:
            sampled = self._weighted_sample(discovery_bucket, n_disc,
                                            weight_key="_composite")
            for s in sampled:
                pool.append(self._make_entry(-1, s, 0, s["_composite"],
                                             self._build_discovery_hint(s),
                                             "fresh_discovery"))

        # ── Ensure minimum pool size ──
        if len(pool) < min(3, self.pool_size):
            all_remaining = [s for s in scored_local + scored_discovery
                             if not s.get("_filter_reason")
                             and s.get("_tag") not in ("recently_played",
                                                        "skipped_recently")]
            remaining = self.pool_size - len(pool)
            extra = self._weighted_sample(all_remaining,
                                          min(remaining, len(all_remaining)),
                                          weight_key="_composite")
            for s in extra:
                tag = s.get("_tag", "unclassified")
                pool.append(self._make_entry(s.get("_pidx", -1), s,
                                             s.get("play_count", 0),
                                             s.get("_composite", 0.05),
                                             "fallback", tag))

        # ── Shuffle, cap artists, assign indices ──
        random.shuffle(pool)
        pool = self._cap_artists(pool)
        for pi, entry in enumerate(pool):
            entry["pool_index"] = pi + 1
        return pool

    def sample_fallback(self, pool: list[dict],
                        recent_title_artists: set | None = None) -> dict | None:
        """Pick a fallback candidate using weighted random, avoiding recent repeats."""
        if not pool:
            return None
        recent_ta = recent_title_artists or set()
        fresh = []
        for c in pool:
            c_key = (c.get("title", "").strip().lower(),
                     c.get("artist", "").strip().lower())
            if c_key[0] and c_key[1] and c_key in recent_ta:
                continue
            fresh.append(c)
        candidates = fresh if fresh else pool
        if not candidates:
            return None
        weights = []
        for c in candidates:
            src = c.get("source", "local")
            zone = c.get("_zone", "")
            if src == "netease_discovery" or zone == "fresh_discovery":
                weights.append(5.0)
            elif zone in ("underplayed_local", "explore_local"):
                weights.append(3.0)
            elif zone == "familiar":
                weights.append(1.0)
            else:
                weights.append(2.0)
        total = sum(weights)
        if total <= 0:
            return random.choice(candidates)
        r = random.random() * total
        cum = 0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return candidates[i]
        return candidates[-1]

    def pick_fallback_from_playlist(self, playlist: list[dict],
                                    exclude_ids: set | None = None,
                                    exclude_title_artists: set | None = None,
                                    recent_title_artists: set | None = None) -> dict | None:
        """Fallback that filters playlist songs then does weighted random.
        Used when the candidate pool is completely empty."""
        if not playlist:
            return None
        exclude_ids = exclude_ids or set()
        exclude_ta = exclude_title_artists or set()
        recent_ta = recent_title_artists or set()

        filtered = []
        for i, s in enumerate(playlist):
            sid = str(s.get("netease_id") or s.get("path", ""))
            if sid in exclude_ids:
                continue
            sa = (s.get("title", "").strip().lower(),
                  s.get("artist", "").strip().lower())
            if sa[0] and sa[1] and (sa in exclude_ta or sa in recent_ta):
                continue
            # Score quickly
            scored = self.scorer.score_and_tag(s)
            if scored["filter_reason"]:
                continue
            s["_composite"] = scored["composite_weight"]
            s["_pidx"] = i
            filtered.append(s)

        candidates = filtered if filtered else list(playlist)
        if not candidates:
            return None
        sampled = self._weighted_sample(candidates, 1,
                                        weight_key="_composite")
        if sampled:
            return sampled[0]
        return random.choice(candidates)

    def lookup_candidate(self, pool: list[dict], pool_index: int) -> dict | None:
        for c in pool:
            if c["pool_index"] == pool_index:
                return c
        return None

    def format_pool_for_prompt(self, pool: list[dict]) -> str:
        lines = []
        for c in pool:
            zone = c.get("_zone", "")
            src = c.get("source", "")
            if zone == "fresh_discovery" or src == "netease_discovery":
                source_label = "🔍 为你发现"
            elif zone == "familiar":
                source_label = "⭐ 熟悉区"
            elif zone == "underplayed_local":
                source_label = "🌿 待发现"
            else:
                source_label = "🎵 候选"
            line = f"{c['pool_index']}. {c['artist']} — {c['title']} [{source_label}]"
            if c.get("hint"):
                line += f" — {c['hint']}"
            lines.append(line)
        return "\n".join(lines)

    # ── Internal ──

    @staticmethod
    def _weighted_sample(candidates: list, n: int,
                         weight_key: str = "weight") -> list:
        """Weighted random sampling without replacement."""
        if n <= 0 or not candidates:
            return []
        n = min(n, len(candidates))
        pool = list(candidates)
        selected = []
        for _ in range(n):
            w = [max(c.get(weight_key, 0.02), 0.02) for c in pool]
            total = sum(w)
            if total <= 0:
                idx = random.randrange(len(pool))
            else:
                r = random.random() * total
                cum = 0
                idx = 0
                for i, wi in enumerate(w):
                    cum += wi
                    if r <= cum:
                        idx = i
                        break
            selected.append(pool.pop(idx))
        return selected

    @staticmethod
    def _make_entry(idx: int, song: dict, play_count: int, weight: float,
                    hint: str, zone: str) -> dict:
        return {
            "pool_index": 0,
            "playlist_index": idx,
            "title": song.get("title", "?"),
            "artist": song.get("artist", "?"),
            "netease_id": song.get("netease_id", ""),
            "path": song.get("path", ""),
            "source": song.get("source", "local"),
            "cover_url": song.get("cover", "") or song.get("cover_url", ""),
            "album_name": song.get("album", ""),
            "weight": round(weight, 2),
            "play_count": play_count,
            "hint": hint,
            "_zone": zone,
        }

    @staticmethod
    def _cap_artists(pool: list[dict], max_per: int = 2) -> list[dict]:
        seen = {}
        out = []
        for c in pool:
            artist = c.get("artist", "")
            count = seen.get(artist, 0)
            if count >= max_per:
                continue
            seen[artist] = count + 1
            out.append(c)
        return out

    @staticmethod
    def _build_hint(weight: float, play_count: int, song: dict) -> str:
        hints = []
        if weight > 0.6:
            hints.append("你的神曲")
        elif weight > 0.35:
            hints.append("心头好")
        elif play_count <= 3:
            hints.append("还没怎么听过")
        elif weight > 0.1:
            hints.append("偶尔听")
        else:
            hints.append("歌单里的歌")
        return "，".join(hints)

    @staticmethod
    def _build_discovery_hint(song: dict) -> str:
        sq = song.get("search_query", "")
        if sq:
            return f"为你发现 · {sq}"
        return "新歌推荐"

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
