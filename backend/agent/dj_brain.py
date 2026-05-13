"""Central DJ Brain — orchestrates context, LLM, actions, and memory."""

import json
import random
from datetime import datetime

from .actions import ActionParser, DJAction
from .context import DJContext
from .llm_provider import LLMProvider
from .memory import DJMemory
from .music_discovery import MusicDiscovery
from .prompts import (build_greeting_prompt, build_interjection_prompt,
                       build_selection_prompt, build_selection_user_prompt,
                       build_system_prompt, build_user_prompt)
from .runtime_taste import RuntimeTasteScorer
from .session import SessionManager
from .song_picker import CandidatePoolBuilder
from .taste_profile import (build_listener_state, build_taste_profile,
                            build_taste_profile_search)


class DJBrain:
    def __init__(self, config: dict):
        self.config = config
        self.personality = {
            "name": config.get("dj", {}).get("name", "clauseekio"),
            "style": config.get("dj", {}).get("style", "温暖陪伴型"),
        }
        self.llm = LLMProvider(config)
        self.memory = DJMemory()
        self.context = DJContext(memory=self.memory)
        self.session = SessionManager(self.memory)
        self.parser = ActionParser()
        self.taste_scorer = RuntimeTasteScorer(memory=self.memory)
        self.picker = CandidatePoolBuilder(
            pool_size=config.get("agent", {}).get("pool_size", 15),
            scorer=self.taste_scorer)
        self.discovery = MusicDiscovery(config)
        self._discovery_ratio = config.get("agent", {}).get("discovery_ratio", 0.7)
        self._current_transition_id = None
        self._current_session_id = None
        self._user_activity = ""
        self._taste_profile_cache = None
        self._profile_context_cache = None
        self._greeted_today = False

    # ── Public API ──

    

    # -- Transition narration controls --

    def _transition_depth(self, chat_context: str = "") -> str:
        """Pick narration depth for transition copy."""
        chat_len = len((chat_context or "").strip())
        activity = (self._user_activity or "").strip()
        if chat_len >= 80:
            return "deep"
        if activity in {"studying", "working", "before_sleep"}:
            return "standard"
        return "deep"

    @staticmethod
    def _contains_text(haystack: str, needle: str) -> bool:
        h = (haystack or "").strip().lower()
        n = (needle or "").strip().lower()
        return bool(h and n and n in h)

    @staticmethod
    def _extract_lyric_hint(raw: str) -> str:
        """Extract readable lyric line from lrc payload."""
        import re

        if not raw:
            return ""
        parts = []
        for line in raw.split("/"):
            clean = re.sub(r"\[\d{2}:\d{2}(?:[.:]\d{1,3})?\]", "", line).strip()
            if not clean:
                continue
            if clean in {"??", "??", "??"}:
                continue
            if 3 <= len(clean) <= 28:
                parts.append(clean)
        return parts[0] if parts else ""

    @staticmethod
    def _build_story_themes(next_song: dict | None = None, chat_context: str = "") -> str:
        song = next_song or {}
        hints = []
        if song.get("album_name"):
            hints.append(f"mention album mood: {song.get('album_name', '')}")
        lyric = DJBrain._extract_lyric_hint(song.get("lyric_snippet", ""))
        if lyric:
            hints.append(f"quote one lyric image naturally: {lyric}")
        if (chat_context or "").strip():
            hints.append("continue naturally from recent chat context")
        hints.append("expand with creative origin, artist intent, lyric meaning, or your own interpretation")
        return "; ".join(hints)

    def _build_transition_user_prompt(self, *, time_str: str, weather_str: str,
                                      current_song_str: str, next_song: dict,
                                      history_str: str = "", tags: str = "",
                                      skipped_str: str = "", artist_streak: str = "",
                                      chat_context: str = "", depth: str = "deep") -> str:
        """Prompt for transition narration with adaptive length constraints."""
        next_song_str = f"{next_song.get('artist', '?')} - {next_song.get('title', '?')}"
        next_title = next_song.get("title", "")
        next_artist = next_song.get("artist", "")
        song_detail = []
        if next_song.get("album_name"):
            song_detail.append(f"album: {next_song.get('album_name', '')}")
        lyric_hint = self._extract_lyric_hint(next_song.get("lyric_snippet", ""))
        if lyric_hint:
            song_detail.append(f"lyric image: {lyric_hint}")

        if depth == "short":
            length_rule = "30-60 characters, concise and natural"
        elif depth == "standard":
            length_rule = "90-160 characters, richer but compact"
        else:
            length_rule = "160-280 characters, story-like and layered"

        parts = [
            f"time: {time_str}",
            f"just played: {current_song_str}",
            f"up next: {next_song_str}",
        ]
        if weather_str:
            parts.insert(1, f"weather: {weather_str}")
        if tags:
            parts.append(f"tags: {tags}")
        if song_detail:
            parts.append("song details:\n- " + "\n- ".join(song_detail))
        if skipped_str:
            parts.append(skipped_str)
        if artist_streak:
            parts.append(artist_streak)
        if history_str:
            parts.append(f"recent lines (avoid repetition):\n{history_str}")
        if chat_context:
            parts.append(f"recent chat context (continue naturally):\n{chat_context}")

        parts.extend([
            "",
            "Task: write a natural radio line before playing the next song.",
            f"Length requirement: {length_rule}",
            "Hard requirements:",
            f"1) Must explicitly mention next track info: title '{next_title}' or artist '{next_artist}'",
            "2) Keep it conversational, avoid robotic radio phrasing",
            "3) You may expand with origin story, artist intent, lyric meaning, or spontaneous recommendation",
            f"4) Optional angles: {self._build_story_themes(next_song, chat_context)}",
            "5) Mention the previous/current song only if it feels natural; do not force a comparison",
            "6) Use natural spoken rhythm; do not use bracketed stage directions",
            "Output must be JSON with fields say/reason/segue/mood/action.",
            "Important: say may be natural Chinese, English, Japanese, Korean, or any natural mix. Preserve original Japanese/Korean/English/Chinese song titles and artist names exactly — do not transliterate or translate them.",
        ])

        return "\n".join(parts)

    def _ensure_rich_transition(self, action: DJAction, current_song: dict,
                                next_song: dict, weather_desc: str = "",
                                chat_context: str = "", depth: str = "deep") -> DJAction:
        """Second-pass expansion to avoid rigid/too-short transition lines."""
        say = (action.say or "").strip()
        next_title = (next_song.get("title") or "").strip()
        next_artist = (next_song.get("artist") or "").strip()
        has_anchor = (
            self._contains_text(say, next_title)
            or self._contains_text(say, next_artist)
        )

        if depth == "short":
            min_len = 24
        elif depth == "standard":
            min_len = 70
        else:
            min_len = 110

        need_retry = (len(say) < min_len) or (not has_anchor)
        if not need_retry:
            return action

        time_info = self.context.get_time_info()
        weather_str = self.context.get_weather_str(
            {"description": weather_desc} if weather_desc else None
        )
        history_str = "\n".join(self._recent_sayings(4))
        tags = " ".join(next_song.get("tags", [])) if next_song.get("tags") else ""
        skipped_str = self.context.get_skipped_summary()
        artist_streak = self.context.get_artist_streak_info()
        cur_str = f"{current_song.get('artist', '?')} - {current_song.get('title', '?')}"

        system_prompt = (
            "You are a human-like multilingual radio DJ. "
            "Output JSON only with fields say/reason/segue/mood/action. "
            "say is the spoken line and may be Chinese, English, Japanese, Korean, or a natural mix; "
            "preserve Japanese/Korean/English/Chinese song titles and artist names exactly. "
            "Do not transliterate, translate, or alter kana/kanji/hangul/romanisation in song metadata. "
            "reason is internal planning."
        )
        user_prompt = self._build_transition_user_prompt(
            time_str=time_info["time_str"],
            weather_str=weather_str,
            current_song_str=cur_str,
            next_song=next_song,
            history_str=history_str,
            tags=tags,
            skipped_str=skipped_str,
            artist_streak=artist_streak,
            chat_context=chat_context or "",
            depth=depth,
        )

        retry = self.llm.generate(system_prompt, user_prompt, json_mode=True)
        if retry:
            retry_action = self.parser.parse_json_response(retry.get("text", ""))
            if retry_action and retry_action.say:
                retry_action.action = action.action or "play_selected"
                retry_action.selected_song_index = action.selected_song_index
                retry_action.selected_song_title = action.selected_song_title
                retry_action.selected_song_artist = action.selected_song_artist
                return retry_action

        lyric_hint = self._extract_lyric_hint(next_song.get("lyric_snippet", ""))
        lyric_piece = f"它那句“{lyric_hint}”很容易让人入戏。" if lyric_hint else ""
        album_piece = f"放到《{next_song.get('album_name')}》这张专辑里听会更完整。" if next_song.get("album_name") else ""
        chat_piece = "你刚才聊到的情绪我记着呢，" if (chat_context or "").strip() else ""
        period = time_info["period"]
        weather_piece = f"{weather_desc}的" if weather_desc else ""
        action.say = (
            f"{chat_piece}接下来给你放 {next_artist} 的《{next_title}》。"
            f"{lyric_piece}{album_piece}"
            "先听这一首，看看它会不会刚好撞上你现在的状态。"
        )
        return action

    # Runtime overrides: keep generation driven by structured payloads instead of
    # long handwritten prompts. These later method definitions replace the
    # earlier exploratory versions above.

    @staticmethod
    def _extract_lyric_hint(raw: str) -> str:
        """Extract a short lyric hint from lrc payload."""
        import re

        if not raw:
            return ""

        parts = []
        for line in raw.split("/"):
            clean = re.sub(r"\[\d{2}:\d{2}(?:[.:]\d{1,3})?\]", "", line).strip()
            if not clean:
                continue
            if len(clean) < 3 or len(clean) > 28:
                continue
            if clean.endswith(":"):
                continue
            parts.append(clean)
        return parts[0] if parts else ""

    @staticmethod
    def _depth_length_rules(depth: str) -> tuple[int, int]:
        if depth == "short":
            return 30, 60
        if depth == "standard":
            return 90, 160
        return 160, 280

    @staticmethod
    def _minimal_transition_system_prompt() -> str:
        return (
            "You are a multilingual radio DJ. "
            "Read the structured payload and return one JSON object only. "
            "Keep `say` natural: Chinese, English, Japanese, Korean, or any natural mix. "
            "Never skip Japanese, Korean, English, or multilingual songs. "
            "Preserve original song titles and artist names exactly — do not transliterate, "
            "translate, or alter kana/kanji/hangul/romanisation."
        )

    def _build_transition_payload(self, *, current_song: dict, next_song: dict,
                                  time_str: str, weather_str: str = "",
                                  history_str: str = "", tags: str = "",
                                  skipped_str: str = "", artist_streak: str = "",
                                  chat_context: str = "", depth: str = "deep") -> str:
        """Build structured transition payload instead of long handwritten prompt text."""
        min_len, max_len = self._depth_length_rules(depth)
        lyric_hint = self._extract_lyric_hint(next_song.get("lyric_snippet", ""))
        payload = {
            "task": "transition",
            "output": {
                "format": "json",
                "fields": ["say", "reason", "segue", "mood", "action"],
                "language": "zh-CN, en, ja, ko, or natural mixed language; preserve Japanese/Korean/English/Chinese titles and artist names exactly — do not transliterate or translate",
            },
            "constraints": {
                "must_anchor_next_song": True,
                "next_song_title": next_song.get("title", ""),
                "next_song_artist": next_song.get("artist", ""),
                "length_chars": {"min": min_len, "max": max_len},
                "tone": "natural_radio_dj",
                "previous_song_reference": "optional; mention the current/previous song only when it creates a natural bridge",
                "allow_topics": [
                    "simple_recommendation",
                    "mood_observation",
                    "origin_story",
                    "artist_intent",
                    "lyric_meaning",
                    "personal_interpretation",
                    "chat_followup",
                ],
                "forbid": [
                    "robotic_broadcast",
                    "bracket_stage_directions",
                    "generic_no_song_anchor",
                    "forced_previous_song_comparison",
                    "mechanical_up_next_phrasing",
                ],
            },
            "context": {
                "time": time_str,
                "weather": weather_str,
                "current_song": {
                    "title": current_song.get("title", ""),
                    "artist": current_song.get("artist", ""),
                },
                "next_song": {
                    "title": next_song.get("title", ""),
                    "artist": next_song.get("artist", ""),
                    "album_name": next_song.get("album_name", ""),
                    "tags": tags,
                    "lyric_hint": lyric_hint,
                },
                "recent_chat": chat_context,
                "recent_lines": history_str,
                "skipped_summary": skipped_str,
                "artist_streak": artist_streak,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _ensure_rich_transition(self, action: DJAction, current_song: dict,
                                next_song: dict, weather_desc: str = "",
                                chat_context: str = "", depth: str = "deep") -> DJAction:
        """Second-pass expansion to avoid rigid or too-short transition lines."""
        say = (action.say or "").strip()
        next_title = (next_song.get("title") or "").strip()
        next_artist = (next_song.get("artist") or "").strip()
        has_anchor = (
            self._contains_text(say, next_title)
            or self._contains_text(say, next_artist)
        )
        min_len, _ = self._depth_length_rules(depth)
        need_retry = (len(say) < min_len) or (not has_anchor)
        if not need_retry:
            return action

        time_info = self.context.get_time_info()
        weather_str = self.context.get_weather_str(
            {"description": weather_desc} if weather_desc else None
        )
        history_str = "\n".join(self._recent_sayings(4))
        tags = " ".join(next_song.get("tags", [])) if next_song.get("tags") else ""
        skipped_str = self.context.get_skipped_summary()
        artist_streak = self.context.get_artist_streak_info()

        retry = self.llm.generate(
            self._minimal_transition_system_prompt(),
            self._build_transition_payload(
                current_song=current_song,
                next_song=next_song,
                time_str=time_info["time_str"],
                weather_str=weather_str,
                history_str=history_str,
                tags=tags,
                skipped_str=skipped_str,
                artist_streak=artist_streak,
                chat_context=chat_context or "",
                depth=depth,
            ),
            json_mode=True,
        )
        if retry:
            retry_action = self.parser.parse_json_response(retry.get("text", ""))
            if retry_action and retry_action.say:
                retry_action.action = action.action or "play_selected"
                retry_action.selected_song_index = action.selected_song_index
                retry_action.selected_song_title = action.selected_song_title
                retry_action.selected_song_artist = action.selected_song_artist
                return retry_action

        lyric_hint = self._extract_lyric_hint(next_song.get("lyric_snippet", ""))
        lyric_piece = f"它那句“{lyric_hint}”很容易让人入戏。" if lyric_hint else ""
        album_piece = f"放到《{next_song.get('album_name')}》这张专辑里听会更完整。" if next_song.get("album_name") else ""
        chat_piece = "你刚才聊到的情绪我记着呢，" if (chat_context or "").strip() else ""
        period = time_info["period"]
        weather_piece = f"{weather_desc}的" if weather_desc else ""
        action.say = (
            f"{chat_piece}接下来给你放 {next_artist} 的《{next_title}》。"
            f"{lyric_piece}{album_piece}"
            "先听这一首，看看它会不会刚好撞上你现在的状态。"
        )
        return action

    def think_transition(self, current_song: dict, next_song: dict | None = None,
                          weather_data: dict | None = None,
                          history: list[str] | None = None,
                          user_activity: str = "",
                         playlist: list[dict] | None = None,
                         chat_context: str = "",
                         scene: str = "") -> tuple[DJAction, dict | None]:
        """Generate a DJ transition. If playlist given, LLM selects next song.
        Returns (DJAction, selected_song_dict | None)."""

        # 1. Ensure session
        if not self._current_session_id:
            self._current_session_id = self.session.start_session()
            self._greeted_today = not self.context.is_first_today()

        if user_activity:
            self._user_activity = user_activity

        time_info = self.context.get_time_info()
        weather_str = self.context.get_weather_str(weather_data)
        weather_desc = weather_data.get("description", "") if weather_data else ""
        cur_str = f"{current_song.get('artist', '?')} - {current_song.get('title', '?')}"

        # 2. Song selection mode (curator) — also supports radio segment
        if playlist and len(playlist) >= 2:
            return self._think_selection(
                current_song, playlist, time_info, weather_str, weather_desc,
                history, cur_str, chat_context=chat_context, scene=scene)

        # 3. Legacy mode: pre-determined next song
        if not next_song:
            next_song = current_song

        ctx = self.context.build_context_window(current_song, next_song, weather_data, history)
        profile_context = self._get_profile_context()
        system_prompt = build_system_prompt(
            self.personality, ctx["taste_summary"], ctx["listener_state"],
            profile_context=profile_context)
        user_prompt = build_user_prompt(
            ctx["time_str"], ctx["weather_str"],
            ctx["current_song_str"], ctx["next_song_str"],
            ctx["history_str"], ctx["tags"],
            skipped_str=ctx.get("skipped_summary", ""),
            artist_streak=ctx.get("artist_streak", ""))
        llm_result = self.llm.generate(system_prompt, user_prompt, json_mode=True)
        action = None
        if llm_result:
            action = self.parser.parse_json_response(llm_result["text"])

        if not action:
            action = self.parser.fallback_action(
                current_song, next_song,
                weather_data.get("description", "") if weather_data else "",
                next_song.get("tags", []),
                recent_sayings=self._recent_sayings())
            llm_result = {"text": action.say, "model": "fallback", "latency_ms": 0, "method": "fallback"}

        self._record(current_song, next_song, action, llm_result or {}, ctx)
        return action, None

    # ── Internal: song selection ──

    def _think_selection(self, current_song, playlist, time_info, weather_str,
                          weather_desc, history, cur_str, chat_context="", scene=""):
        # Build taste profile (cached per session)
        if not self._taste_profile_cache:
            self._taste_profile_cache = build_taste_profile()

        listener_state = build_listener_state(
            time_info, weather_desc, self._user_activity)

        # Get recently played / skipped tracks
        cur_id = current_song.get("netease_id") or current_song.get("path", "")
        recent_transitions = self.memory.get_recent_transitions(15)
        recent_ids = []
        recent_title_artists = set()  # (title, artist) tuples for hard dedup
        for t in recent_transitions[-8:]:
            rid = t.get("next_song_id", "")
            if rid and rid != cur_id:
                recent_ids.append(rid)
            na = (t.get("next_song_name", "").strip().lower(),
                  t.get("next_song_artist", "").strip().lower())
            if na[0] and na[1]:
                recent_title_artists.add(na)

        skipped_ids = []
        for t in recent_transitions:
            if t.get("was_skipped"):
                sid = t.get("next_song_id", "")
                if sid:
                    skipped_ids.append(sid)

        # ── Detect scene / context flags ──
        opening_or_explore = (scene == "opening") or any(
            key in (chat_context or "")
            for key in ("开台", "发散", "不要只从", "新东西", "探索", "开场",
                        "想听点新的", "随便来点", "不一样", "没听过", "换换口味")
        )
        favor_familiar = any(
            key in (chat_context or "")
            for key in ("熟悉的", "常听", "红心", "喜欢的歌", "喜欢的感觉",
                        "来点熟的")
        )

        # ── Discover fresh songs from Netease ──
        discovery_songs = []
        try:
            search_taste = build_taste_profile_search()
            discovery_songs = self.discovery.discover(
                taste_profile=search_taste,
                context={
                    "period": time_info["period"],
                    "weather_desc": weather_desc,
                    "user_activity": self._user_activity,
                    "is_weekend": time_info["is_weekend"],
                },
                count=14 if opening_or_explore else 10,
            )
        except Exception as e:
            print(f"[DJBrain] Discovery failed (non-fatal): {e}")

        # ── Build mixed candidate pool ──
        pool = self.picker.build_pool(
            current_song_id=cur_id,
            playlist=playlist,
            recently_played_ids=recent_ids,
            recent_title_artists=recent_title_artists,
            skipped_ids=skipped_ids,
            user_activity=self._user_activity,
            time_period=time_info["period"],
            is_weekend=time_info["is_weekend"],
            weather_desc=weather_desc,
            discovery_songs=discovery_songs,
            discovery_ratio=max(self._discovery_ratio, 0.85) if opening_or_explore else self._discovery_ratio,
            opening_or_explore=opening_or_explore,
            favor_familiar=favor_familiar,
        )

        # Format for LLM
        pool_str = self.picker.format_pool_for_prompt(pool)
        discovery_count = sum(1 for s in pool if s.get("source") == "netease_discovery")
        local_count = len(pool) - discovery_count
        recent_str = "\n".join(
            f"  {t.get('next_song_artist', '?')} - {t.get('next_song_name', '?')}"
            for t in recent_transitions[-5:])

        skipped_str = self.context.get_skipped_summary()
        artist_streak = self.context.get_artist_streak_info()

        system_prompt = build_selection_prompt(
            self.personality, self._taste_profile_cache, listener_state)
        user_prompt = build_selection_user_prompt(
            time_info["time_str"], weather_str, cur_str, pool_str, recent_str,
            "\n".join(history[-3:]) if history else "",
            skipped_str=skipped_str, artist_streak=artist_streak)

        # Add source hint — prefer discovery and exploration over familiar picks
        if discovery_count > 0:
            user_prompt += (
                f"\n\n重要：候选池里有{discovery_count}首是刚从网易云为你搜到的新歌（标记🔍），"
                f"以及探索区/半熟区的歌（标记🌿🎵），少量熟悉区的歌（标记⭐）。"
                f"你的职责是电台DJ，不是歌单循环器——请优先从🔍和🌿区选歌。"
                f"只有在新歌都不合适的情况下，才偶尔从⭐区里选一首。"
            )

        # CRITICAL: instruct LLM to avoid recently played songs
        recent_names = [f"{t.get('next_song_artist', '')} - {t.get('next_song_name', '')}"
                        for t in recent_transitions[-5:]
                        if t.get('next_song_name')]
        if recent_names:
            user_prompt += (
                f"\n\n⚠️ 最近5首已经播过（绝对不要再选这些歌！）：\n"
                + "\n".join(f"  ❌ {n}" for n in recent_names)
            )

        # Add chat context so DJ remembers what user just asked
        if chat_context:
            user_prompt += (
                f"\n\n听众刚才在聊天里说了（这是你选歌的重要线索！）：\n{chat_context}"
            )

        llm_result = self.llm.generate(system_prompt, user_prompt, json_mode=True)
        action = None
        selected_song = None
        depth = self._transition_depth(chat_context)

        if llm_result:
            action = self.parser.parse_json_response(llm_result["text"])
            if action:
                sel = self.picker.lookup_candidate(pool, action.selected_song_index)
                if sel:
                    action.action = "play_selected"
                    selected_song = {
                        "playlist_index": sel["playlist_index"],
                        "title": sel["title"],
                        "artist": sel["artist"],
                        "netease_id": sel.get("netease_id", ""),
                        "path": sel.get("path", ""),
                        "source": sel.get("source", "local"),
                        "weight": sel["weight"],
                        "hint": sel.get("hint", ""),
                        "cover_url": sel.get("cover_url", ""),
                        "album_name": sel.get("album_name", ""),
                    }
                    action.selected_song_title = sel["title"]
                    action.selected_song_artist = sel["artist"]

                    # ── Fetch song details for richer commentary ──
                    if sel.get("netease_id"):
                        try:
                            detail = self.discovery.get_song_detail(sel["netease_id"])
                            if detail:
                                selected_song["album_name"] = selected_song["album_name"] or detail.get("album_name", "")
                                selected_song["album_pic"] = detail.get("album_pic", "")
                            lyric = self.discovery.get_song_lyric_snippet(sel["netease_id"], 3)
                            if lyric:
                                selected_song["lyric_snippet"] = lyric
                        except Exception:
                            pass
                    # Rebuild narration for natural long-form transition quality.
                    action = self._ensure_rich_transition(
                        action,
                        current_song=current_song,
                        next_song=selected_song,
                        weather_desc=weather_desc,
                        chat_context=chat_context,
                        depth=depth,
                    )
                else:
                    action = None

        # Fallback: pick best pool candidate using weighted random sampling
        if not action or not selected_song:
            if pool:
                # Use weighted random fallback (prefers discovery > explore > semi > familiar)
                best = self.picker.sample_fallback(pool, recent_title_artists)

                selected_song = {"playlist_index": best["playlist_index"],
                                 "title": best["title"], "artist": best["artist"],
                                 "netease_id": best.get("netease_id", ""),
                                 "path": best.get("path", ""),
                                 "source": best.get("source", "local"),
                                 "cover_url": best.get("cover_url", ""),
                                 "album_name": best.get("album_name", "")}
                # Generate varied fallback sayings instead of fixed templates
                source_hint = "新发现的" if best.get("source") == "netease_discovery" else ""
                fallback_sayings = [
                    f"来首{source_hint}{best['artist']}的{best['title']}。",
                    f"嗯…{best['title']}，{best['artist']}这首刚好。",
                    f"{best['artist']}——{best['title']}，听。",
                ]
                action = DJAction(
                    say=random.choice(fallback_sayings),
                    reason=f"fallback: weighted-random pool candidate",
                    mood="chill", action="play_selected",
                    selected_song_index=best["pool_index"],
                    selected_song_title=best["title"],
                    selected_song_artist=best["artist"])
                action = self._ensure_rich_transition(
                    action,
                    current_song=current_song,
                    next_song=selected_song,
                    weather_desc=weather_desc,
                    chat_context=chat_context,
                    depth=depth,
                )
                llm_result = llm_result or {"text": "fallback", "model": "fallback",
                                            "latency_ms": 0, "method": "fallback"}
            else:
                # Pool is empty — use filtered playlist fallback (weighted random, not sequential)
                fb = self.picker.pick_fallback_from_playlist(
                    playlist, exclude_ids={cur_id} | set(recent_ids),
                    exclude_title_artists=recent_title_artists,
                    recent_title_artists=recent_title_artists)
                if fb:
                    ns = fb
                    fb_idx = fb.get("_pidx", -1)
                    selected_song = {"playlist_index": fb_idx,
                                     "title": ns.get("title", "?"),
                                     "artist": ns.get("artist", "?"),
                                     "netease_id": ns.get("netease_id", ""),
                                     "path": ns.get("path", ""),
                                     "source": ns.get("source", "local"),
                                     "cover_url": ns.get("cover_url", ""),
                                     "album_name": ns.get("album", "")}
                else:
                    selected_song = None
                    ns = playlist[0] if playlist else {"title": "?", "artist": "?"}
                action = self.parser.fallback_action(
                    current_song, ns if not selected_song else selected_song,
                    weather_desc, ns.get("tags", []),
                    recent_sayings=self._recent_sayings())
                if not selected_song:
                    selected_song = None

        next_song_for_record = {
            "title": selected_song["title"] if selected_song else "?",
            "artist": selected_song["artist"] if selected_song else "?",
        }
        next_song_dict = next_song_for_record.copy()
        next_song_dict["netease_id"] = selected_song.get("netease_id", "") if selected_song else ""
        next_song_dict["path"] = selected_song.get("path", "") if selected_song else ""

        dummy_ctx = {
            "weather_str": weather_str, "period": time_info["period"],
            "taste_summary": "", "listener_state": listener_state,
        }
        self._record(current_song, next_song_dict, action, llm_result or {}, dummy_ctx)
        return action, selected_song

    # ── Radio Segment Planning (new) ──

    def think_radio_segment(self, current_song: dict, playlist: list[dict],
                            weather_data: dict | None = None,
                            n_songs: int = 3) -> dict | None:
        """Generate a mini radio segment: DJ intro + 2-3 songs + DJ outro.
        Returns a structured segment plan for the frontend to execute."""

        if len(playlist) < 2:
            return None

        time_info = self.context.get_time_info()
        weather_str = self.context.get_weather_str(weather_data)
        weather_desc = weather_data.get("description", "") if weather_data else ""
        cur_str = f"{current_song.get('artist', '?')} - {current_song.get('title', '?')}"

        # Build context
        listener_state = build_listener_state(
            time_info, weather_desc, self._user_activity)

        # Pick top N songs from candidate pool
        cur_id = current_song.get("netease_id") or current_song.get("path", "")
        recent_transitions = self.memory.get_recent_transitions(10)
        recent_ids = []
        for t in recent_transitions[-5:]:
            rid = t.get("next_song_id", "")
            if rid and rid != cur_id:
                recent_ids.append(rid)

        skipped_ids = []
        for t in recent_transitions:
            if t.get("was_skipped"):
                sid = t.get("next_song_id", "")
                if sid:
                    skipped_ids.append(sid)

        pool = self.picker.build_pool(
            current_song_id=cur_id,
            playlist=playlist,
            recently_played_ids=recent_ids,
            skipped_ids=skipped_ids,
            user_activity=self._user_activity,
            time_period=time_info["period"],
            is_weekend=time_info["is_weekend"],
            weather_desc=weather_desc,
        )

        if not pool:
            return None

        # Select N songs using weighted random (avoid sequential bias)
        top_n = []
        if pool:
            # Use sample_fallback logic: prefer discovery > explore > semi > familiar
            temp_pool = list(pool)
            for _ in range(min(n_songs, len(temp_pool))):
                picked = self.picker.sample_fallback(temp_pool)
                if picked:
                    top_n.append(picked)
                    temp_pool = [c for c in temp_pool if c.get("pool_index") != picked.get("pool_index")]
        song_plan = []
        for i, s in enumerate(top_n):
            song_plan.append({
                "playlist_index": s["playlist_index"],
                "title": s["title"],
                "artist": s["artist"],
                "netease_id": s.get("netease_id", ""),
                "path": s.get("path", ""),
                "source": s.get("source", "local"),
                "weight": s["weight"],
                "hint": s.get("hint", ""),
            })

        # Generate DJ intro for this segment
        profile_context = self._get_profile_context()
        taste = self.context.get_music_taste_summary()
        skipped_str = self.context.get_skipped_summary()
        artist_streak = self.context.get_artist_streak_info()

        segment_prompt = self._build_segment_system_prompt(profile_context, taste, listener_state)
        segment_user = self._build_segment_user_prompt(
            time_info["time_str"], weather_str, cur_str, top_n, skipped_str, artist_streak)

        llm_result = self.llm.generate(segment_prompt, segment_user, json_mode=True)
        dj_lines = []
        if llm_result:
            parsed = self.parser.parse_json_response(llm_result["text"])
            if parsed:
                dj_lines = [
                    {"position": "intro", "text": parsed.say, "mood": parsed.mood},
                ]
                if parsed.reason:
                    dj_lines.append({
                        "position": "outro",
                        "text": parsed.reason,
                        "mood": parsed.mood,
                    })

        if not dj_lines:
            # Fallback DJ lines
            dj_lines = [
                {"position": "intro",
                 "text": f"来，接下来几首给你安排好了。先听{top_n[0]['artist']}的{top_n[0]['title']}。",
                 "mood": "chill"},
            ]

        return {
            "songs": song_plan,
            "dj_lines": dj_lines,
            "scene": time_info["period"],
            "weather": weather_desc,
            "time": time_info["time_str"],
        }

    def _build_segment_system_prompt(self, profile_context: str, taste: str,
                                      listener_state: str) -> str:
        return f"""你叫{self.personality['name']}，不是AI，是一个有血有肉的真人电台DJ。

## 你的性格
{self.personality['style']}

## 关于听众
{profile_context}

## 听众口味
{taste}

## 当前状态
{listener_state}

## 任务
你正在编排一小段"电台节目"——接下来要放2-3首歌。请想好怎么介绍这段音乐的"主题感"。

DJ intro：在这几首歌之前说的开场白——可以是为什么选这几首联播、想营造什么氛围、或者随意聊一句。
DJ outro：这组歌快结束时的收尾——自然过渡，不用太长。

## 说话方式
- 像跟老朋友聊天，介绍音乐但不机械
- 用语气词，自然停顿
- 15-35个字

## 输出格式
永远只输出合法JSON：
{{"say": "DJ开场白（15-35字）", "reason": "DJ收尾/过渡词（15-25字）", "mood": "energetic|chill|melancholy|playful|nostalgic", "action": "play_selected"}}

## 示例
深夜推3首后摇/氛围：
{{"say": "嗯…接下来这几首，是我专门给你挑的。闭眼听就行，什么都不用想。", "reason": "几首安静的歌快放完了，继续陪你。不用说话。", "mood": "chill", "action": "play_selected"}}

下雨天推LANY/独立：
{{"say": "外面雨还在下……正好，这几首歌跟雨声搭在一起听特别妙。来，第一首。", "reason": "雨天氛围组收尾，希望这几首让你放松了一点。", "mood": "melancholy", "action": "play_selected"}}

## 绝对禁止
- 不要用括号写动作描述
- 不要机械播报"""

    def _build_segment_user_prompt(self, time_str: str, weather_str: str,
                                    current_song: str, top_songs: list,
                                    skipped_str: str, artist_streak: str) -> str:
        songs_text = "\n".join(
            f"  {i+1}. {s['artist']} - {s['title']} (权重{s.get('weight', 0):.2f})"
            for i, s in enumerate(top_songs))
        parts = [
            f"现在：{time_str}",
            f"刚播完：{current_song}",
            f"接下来计划播这几首：\n{songs_text}",
            f"请生成DJ开场白。",
        ]
        if weather_str:
            parts.insert(2, f"天气：{weather_str}")
        if skipped_str:
            parts.append(skipped_str)
        if artist_streak:
            parts.append(artist_streak)
        return "\n".join(parts)

    # ── Greeting (enhanced) ──

    def greet(self, weather_data: dict | None = None) -> DJAction:
        """Generate a personalized greeting when the user starts listening."""

        if not self._current_session_id:
            self._current_session_id = self.session.start_session()

        time_info = self.context.get_time_info()
        weather_str = self.context.get_weather_str(weather_data)
        weather_desc = weather_data.get("description", "") if weather_data else ""
        profile_context = self._get_profile_context()
        is_first = self.context.is_first_today()
        self._greeted_today = not is_first

        # Build state context for greeting
        state_lines = [f"当前时间：{time_info['time_str']}"]
        if weather_str:
            state_lines.append(f"当前天气：{weather_str}")
        state_lines.append(time_info["activity_hint"])
        if time_info["is_weekend"]:
            state_lines.append("今天是周末")
        if is_first:
            state_lines.append("今天是今天第一次打开电台，可以稍微热情一点")

        # Use enhanced greeting prompt
        system_prompt = build_greeting_prompt(
            self.personality,
            "\n".join(state_lines),
            profile_context=profile_context)

        user_lines = [
            "用户刚刚打开电台。请用一句自然的问候（say字段）欢迎听众。",
            "不要超过25个字。",
        ]
        if is_first:
            user_lines.append("这是今天第一句问候，可以结合时段和天气个性化一点。")

        user_prompt = "\n".join(user_lines)

        llm_result = self.llm.generate(system_prompt, user_prompt, json_mode=True)
        action = None
        if llm_result:
            action = self.parser.parse_json_response(llm_result["text"])

        if not action:
            # Rich fallback greetings
            greetings = []
            period = time_info["period"]
            if weather_desc:
                if "雨" in weather_desc:
                    greetings.append(f"{period}好…外面在下雨，正好听歌。我是{self.personality['name']}。")
                elif "晴" in weather_desc:
                    greetings.append(f"{period}好，天气不错。我是{self.personality['name']}，来点好听的。")
                elif "云" in weather_desc or "阴" in weather_desc:
                    greetings.append(f"{period}好。阴天最适合窝着听歌了。我是{self.personality['name']}。")

            if not greetings:
                if period == "深夜":
                    greetings.append(f"这个点还在醒着啊…没事，我陪你。{self.personality['name']}，上线了。")
                elif period == "早晨":
                    greetings.append(f"早啊——新的一天，来点好听的。我是{self.personality['name']}。")
                elif period == "下午":
                    greetings.append(f"下午好。我是{self.personality['name']}，接下来的音乐交给我。")
                else:
                    greetings.append(f"{period}好，我是{self.personality['name']}。")

            action = DJAction(
                say=greetings[0],
                reason=f"fallback greeting",
                segue="smooth",
                mood="chill",
                action="greet",
            )

        return action

    # ── Profile context helper ──

    def _get_profile_context(self) -> str:
        """Load and cache user profile files."""
        if self._profile_context_cache is not None:
            return self._profile_context_cache
        self._profile_context_cache = self.context.get_user_profile_context()
        return self._profile_context_cache

    # ── Streaming (delegates to standard think_transition) ──

    def think_transition_stream(self, current_song: dict, next_song: dict | None = None,
                                 weather_data: dict | None = None,
                                 history: list[str] | None = None,
                                 user_activity: str = "",
                                 playlist: list[dict] | None = None,
                                 chat_context: str = "",
                                 scene: str = ""):
        """Streaming version — delegates to think_transition so the new picker,
        RuntimeTasteScorer, bucket sampler, and scene-aware ratios are always used.

        Maintains SSE-compatible yield shape (token events + done event).
        Real per-token streaming can be re-added later once the streaming LLM
        path also integrates _think_selection."""
        # Delegate to the standard (non-streaming) path that uses _think_selection
        action, selected_song = self.think_transition(
            current_song=current_song,
            next_song=next_song,
            weather_data=weather_data,
            history=history,
            user_activity=user_activity,
            playlist=playlist,
            chat_context=chat_context,
            scene=scene,
        )

        # Yield as SSE-compatible events (token first, then done)
        if action and action.say:
            yield {"type": "token", "text": action.say}
        resp = {
            "say": action.say if action else "",
            "reason": action.reason if action else "",
            "segue": action.segue if action else "smooth",
            "mood": action.mood if action else "chill",
            "action": action.action if action else "play_next",
            "method": "agent_stream",
        }
        if selected_song:
            resp["selected_song"] = selected_song
        yield {"type": "done", "action": action, "response": resp}

    def _recent_sayings(self, n: int = 10) -> list[str]:
        """Get recently used DJ sayings to avoid repetition."""
        try:
            transitions = self.memory.get_recent_transitions(n)
            return [t.get("say_text", "") for t in transitions if t.get("say_text")]
        except Exception:
            return []

    def _record(self, current_song, next_song, action, llm_result, ctx):
        self._current_transition_id = self.memory.record_transition({
            "session_id": self._current_session_id,
            "current_song_id": current_song.get("netease_id") or current_song.get("path", ""),
            "current_song_name": current_song.get("title", ""),
            "current_song_artist": current_song.get("artist", ""),
            "next_song_id": next_song.get("netease_id") or next_song.get("path", ""),
            "next_song_name": next_song.get("title", ""),
            "next_song_artist": next_song.get("artist", ""),
            "say_text": action.say,
            "reason": action.reason,
            "segue_type": action.segue,
            "mood": action.mood,
            "action": action.action,
            "model_used": llm_result.get("model", "unknown"),
            "latency_ms": llm_result.get("latency_ms", 0),
            "weather_desc": ctx.get("weather_str", ""),
            "time_period": ctx.get("period", ""),
        })

    def set_user_activity(self, activity: str):
        self._user_activity = activity
        self._taste_profile_cache = None  # refresh on next call
        self._profile_context_cache = None  # refresh profile too

    def record_reaction(self, song_index: int, reaction: str):
        """Record user feedback on the current transition."""
        if self._current_transition_id:
            skipped = reaction == "skip"
            self.memory.update_reaction(self._current_transition_id, reaction, skipped)

            # Also record as song interaction
            transitions = self.memory.get_recent_transitions(1)
            if transitions:
                t = transitions[0]
                self.memory.record_song_interaction(
                    self._current_session_id,
                    t["next_song_id"], t["next_song_name"], t["next_song_artist"],
                    reaction,
                    transition_log_id=self._current_transition_id,
                )

            # Adjust personality based on reaction
            if reaction == "like":
                self.memory.update_personality_trait("warmth", 0.01)
            elif reaction == "skip":
                self.memory.update_personality_trait("edgyness", 0.01)

    def think_interjection(self, rule, state: dict) -> DJAction | None:
        """Generate a proactive interjection triggered by a scheduler rule."""
        system_prompt = build_interjection_prompt(
            self.personality,
            rule.build_prompt(state, self.personality["name"]),
        )

        time_info = self.context.get_time_info()
        weather_str = state.get("weather_desc", "")
        current = state.get("current_song", {})
        cur_str = f"{current.get('artist', '?')} - {current.get('title', '?')}"

        user_lines = [
            f"现在：{time_info['time_str']}",
            f"当前播放：{cur_str}",
        ]
        if weather_str:
            user_lines.insert(1, f"天气：{weather_str}")
        user_prompt = "\n".join(user_lines)

        llm_result = self.llm.generate(system_prompt, user_prompt, json_mode=True)
        action = None
        if llm_result:
            action = self.parser.parse_json_response(llm_result["text"])

        if not action:
            action = DJAction(
                say=rule.build_prompt(state, self.personality["name"])[:40],
                reason=f"fallback interjection for {rule.name}",
                segue="smooth",
                mood="chill",
                action="play_next",
            )

        return action

    def get_interjection_context(self) -> dict:
        """Gather current state snapshot for the scheduler's rule evaluation."""
        time_info = self.context.get_time_info()

        # Get session stats
        sid = self._current_session_id
        transitions = []
        if sid:
            transitions = self.memory.get_session_transitions(sid)

        # Recent artists and moods from transitions
        recent_artists = [t["next_song_artist"] for t in transitions[-10:]
                          if t.get("next_song_artist")]
        recent_moods = [t["mood"] for t in transitions[-10:] if t.get("mood")]

        # Session duration
        duration_minutes = 0
        if sid and transitions:
            first_ts = transitions[0].get("timestamp", "")
            if first_ts:
                try:
                    first_dt = datetime.fromisoformat(first_ts)
                    duration_sec = (datetime.now() - first_dt).total_seconds()
                    duration_minutes = duration_sec / 60
                except (ValueError, TypeError):
                    pass

        # Find current song info
        current_song = {}
        if transitions:
            last = transitions[-1]
            current_song = {
                "title": last.get("next_song_name", ""),
                "artist": last.get("next_song_artist", ""),
            }

        # Weather from most recent transition
        weather_desc = ""
        if transitions:
            weather_desc = transitions[-1].get("weather_desc", "")

        return {
            "current_time": datetime.now(),
            "current_song": current_song,
            "weather_desc": weather_desc,
            "session_duration_minutes": duration_minutes,
            "song_count": len(transitions),
            "recent_artists": recent_artists,
            "recent_moods": recent_moods,
        }

    def close(self):
        """End the current session and clean up."""
        if self._current_session_id:
            self.session.end_session(self._current_session_id)
            self._current_session_id = None

    def get_stream_state(self) -> dict:
        """Get current state for SSE streaming."""
        summary = self.memory.get_stats_summary()
        return {
            "session_id": self._current_session_id,
            "total_transitions": summary["total_transitions"],
            "top_mood": summary["top_mood"],
            "personality": summary["personality"],
        }
