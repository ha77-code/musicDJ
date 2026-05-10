"""DJ Action dataclass and parser for structured LLM output."""

import json
import re
from dataclasses import dataclass, field


@dataclass
class DJAction:
    say: str = ""
    reason: str = ""
    segue: str = "smooth"
    mood: str = "chill"
    action: str = "play_next"
    selected_song_index: int = 0
    selected_song_title: str = ""
    selected_song_artist: str = ""

    VALID_SEGUES = {"smooth", "contrast", "mood_match", "surprise"}
    VALID_MOODS = {"energetic", "chill", "melancholy", "playful", "nostalgic"}
    VALID_ACTIONS = {"play_next", "repeat", "shuffle", "greet", "play_selected"}

    def validate(self):
        if not self.say or len(self.say) < 4:
            return False
        if self.segue not in self.VALID_SEGUES:
            self.segue = "smooth"
        if self.mood not in self.VALID_MOODS:
            self.mood = "chill"
        if self.action not in self.VALID_ACTIONS:
            self.action = "play_next"
        return True


class ActionParser:
    @staticmethod
    def parse_json_response(raw: str) -> DJAction | None:
        if not raw:
            return None

        text = raw.strip()

        # Try direct JSON parse
        try:
            data = json.loads(text)
            return ActionParser._dict_to_action(data)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown fence
        m = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
        if m:
            try:
                data = json.loads(m.group(1))
                return ActionParser._dict_to_action(data)
            except json.JSONDecodeError:
                pass

        # Try finding JSON object bounds
        m = re.search(r'\{[\s\S]*"say"[\s\S]*\}', text)
        if m:
            try:
                data = json.loads(m.group(0))
                return ActionParser._dict_to_action(data)
            except json.JSONDecodeError:
                pass

        # Last resort: extract just the say text
        m = re.search(r'"say"\s*:\s*"([^"]+)"', text)
        if m:
            action = DJAction(say=m.group(1).strip())
            action.validate()
            return action

        return None

    @staticmethod
    def _dict_to_action(data: dict) -> DJAction | None:
        if not isinstance(data, dict):
            return None
        if "say" not in data:
            return None

        action = DJAction(
            say=data.get("say", "").strip(),
            reason=data.get("reason", "").strip(),
            segue=data.get("segue", "smooth").lower(),
            mood=data.get("mood", "chill").lower(),
            action=data.get("action", "play_next").lower(),
            selected_song_index=data.get("selected_song_index", 0),
            selected_song_title=data.get("selected_song_title", "").strip(),
            selected_song_artist=data.get("selected_song_artist", "").strip(),
        )
        if not action.validate():
            return None
        return action

    # Track recently used fallback phrases to avoid repetition
    _used_fallbacks: list[str] = []

    @staticmethod
    def fallback_action(current_song: dict, next_song: dict,
                        weather_desc: str = "", tags: list[str] | None = None,
                        fallback_library: dict | None = None,
                        recent_sayings: list[str] | None = None) -> DJAction:
        """Rule-based fallback when LLM fails. Uses song-specific templates."""
        import random, json
        from datetime import datetime
        from pathlib import Path

        artist = next_song.get("artist", "") or ""
        title = next_song.get("title", "") or ""
        weather = weather_desc or "default"
        hour = datetime.now().hour

        # Load fallback library from personality.json
        candidates = []
        if fallback_library is None:
            try:
                lib_path = Path(__file__).resolve().parent.parent.parent / "data" / "personality.json"
                fallback_library = json.loads(lib_path.read_text(encoding="utf-8")).get("fallback_transitions", {})
            except Exception:
                fallback_library = {}

        # Match weather category
        weather_cat = "default"
        for kw in ["雨", "阴", "晴", "雪", "夜"]:
            if kw in weather:
                weather_cat = kw
                break
        if hour >= 22 or hour < 6:
            weather_cat = "夜"

        # Get templates for this weather
        weather_group = fallback_library.get(weather_cat, fallback_library.get("default", {}))
        candidates = weather_group.get("default", [])

        # If no weather match, use global default
        if not candidates:
            default_group = fallback_library.get("default", {})
            candidates = default_group.get("default", [
                "{artist}来了——{title}，听着就很对。",
            ])

        # Format templates with song info
        formatted = []
        for tpl in candidates:
            s = tpl.replace("{artist}", artist).replace("{title}", title)
            if not artist and "{artist}" in tpl:
                s = s.replace("{artist}的", "").replace("{artist}", "")
            if not title:
                continue
            formatted.append(s)

        if not formatted:
            formatted = [f"接一首{artist or title}，这个点刚好。"]

        # Avoid recently used phrases
        avoid = set(recent_sayings or []) | set(ActionParser._used_fallbacks[-10:])
        fresh = [s for s in formatted if s not in avoid]
        if not fresh:
            ActionParser._used_fallbacks = ActionParser._used_fallbacks[-3:]
            fresh = formatted

        say = random.choice(fresh)
        ActionParser._used_fallbacks.append(say)
        if len(ActionParser._used_fallbacks) > 20:
            ActionParser._used_fallbacks = ActionParser._used_fallbacks[-20:]

        # Pick mood based on time and weather
        mood = "chill"
        if "雨" in weather:
            mood = "melancholy"
        elif hour >= 22 or hour < 6:
            mood = "chill"
        elif 6 <= hour < 10:
            mood = "playful"
        elif "晴" in weather:
            mood = "energetic"

        # Pick segue
        segues = ["smooth", "mood_match", "smooth", "smooth", "contrast"]
        segue = random.choice(segues)

        return DJAction(
            say=say,
            reason=f"fallback (weather={weather_cat}, mood={mood})",
            segue=segue,
            mood=mood,
            action="play_next",
        )
