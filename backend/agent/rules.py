"""Interjection rules and rule engine for proactive DJ behavior."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class InterjectionRule:
    name: str
    priority: int  # 1-5, 5 highest
    cooldown_minutes: float
    _last_triggered: float = 0  # timestamp

    def evaluate(self, state: dict) -> bool:
        raise NotImplementedError

    def build_prompt(self, state: dict, dj_name: str) -> str:
        raise NotImplementedError

    def is_cooled_down(self, now: float) -> bool:
        return (now - self._last_triggered) >= self.cooldown_minutes * 60

    def mark_triggered(self, now: float):
        self._last_triggered = now


class HourChimeRule(InterjectionRule):
    """Late-night hour chime: 22:00-04:00, on the hour."""
    def __init__(self):
        super().__init__(name="hour_chime", priority=5, cooldown_minutes=55)

    def evaluate(self, state: dict) -> bool:
        now = state.get("current_time", datetime.now())
        if now.minute != 0:
            return False
        return now.hour >= 22 or now.hour <= 4

    def build_prompt(self, state: dict, dj_name: str) -> str:
        now = state.get("current_time", datetime.now())
        period = _period_name(now.hour)
        return (
            f"现在是凌晨{now.hour}点。作为一个深夜电台DJ，"
            f"请温柔地提醒听众时间不早了，注意休息，但语气要温暖不要唠叨。"
            f"不超过25个字。"
        )


class WeatherChangeRule(InterjectionRule):
    """Weather description changed since last check."""
    def __init__(self, cooldown: float = 30):
        super().__init__(name="weather_change", priority=4, cooldown_minutes=cooldown)

    def evaluate(self, state: dict) -> bool:
        current = state.get("weather_desc", "")
        previous = state.get("last_weather_desc", "")
        if not current:
            return False
        return current != previous

    def build_prompt(self, state: dict, dj_name: str) -> str:
        weather = state.get("weather_desc", "")
        return (
            f"外面天气现在是「{weather}」。请自然地提一嘴天气变化，"
            f"可以顺势推荐接下来适合这个天气听的歌。不超过25个字。"
        )


class ArtistStreakRule(InterjectionRule):
    """Same artist played N times in a row."""
    def __init__(self, threshold: int = 4, cooldown: float = 15):
        super().__init__(name="artist_streak", priority=3, cooldown_minutes=cooldown)
        self.threshold = threshold

    def evaluate(self, state: dict) -> bool:
        artists = state.get("recent_artists", [])
        if len(artists) < self.threshold:
            return False
        recent = artists[-self.threshold:]
        return len(set(recent)) == 1

    def build_prompt(self, state: dict, dj_name: str) -> str:
        artists = state.get("recent_artists", [])
        artist = artists[-1] if artists else "这位艺人"
        return (
            f"听众已经连续听了{self.threshold}首{artist}的歌。"
            f"请用轻松的语气提一句，可以调侃「你是不是上头了」。不超过25个字。"
        )


class ListeningDurationRule(InterjectionRule):
    """Milestones: every N minutes of continuous listening."""
    def __init__(self, milestones: list = None, cooldown: float = 40):
        super().__init__(name="listening_duration", priority=2, cooldown_minutes=cooldown)
        self.milestones = milestones or [30, 60, 90, 120]
        self._hit_milestones: set = set()

    def evaluate(self, state: dict) -> bool:
        minutes = int(state.get("session_duration_minutes", 0))
        for m in self.milestones:
            if minutes >= m and m not in self._hit_milestones:
                self._hit_milestones.add(m)
                return True
        return False

    def build_prompt(self, state: dict, dj_name: str) -> str:
        minutes = int(state.get("session_duration_minutes", 0))
        hours = minutes // 60
        if hours > 0:
            dur = f"{hours}小时{minutes % 60}分钟"
        else:
            dur = f"{minutes}分钟"
        return (
            f"听众已经连续听了{dur}。请肯定一下他对音乐的热爱，"
            f"语气温暖带点俏皮。不超过25个字。"
        )


class SongCountRule(InterjectionRule):
    """Every N songs, make an observation."""
    def __init__(self, every_n: int = 8, cooldown: float = 20):
        super().__init__(name="song_count", priority=2, cooldown_minutes=cooldown)
        self.every_n = every_n
        self._last_count = 0

    def evaluate(self, state: dict) -> bool:
        count = state.get("song_count", 0)
        milestone = (count // self.every_n) * self.every_n
        if milestone > 0 and milestone > self._last_count:
            self._last_count = milestone
            return True
        return False

    def build_prompt(self, state: dict, dj_name: str) -> str:
        count = state.get("song_count", 0)
        return (
            f"听众已经连续听了{count}首歌。请随口评论一句今晚的歌单品味"
            f"或者给一个小小的音乐小贴士。不超过25个字。"
        )


class MoodShiftRule(InterjectionRule):
    """Sudden mood change in consecutive songs."""
    MOOD_CONTRASTS = {
        ("energetic", "melancholy"),
        ("melancholy", "energetic"),
        ("chill", "energetic"),
        ("energetic", "chill"),
        ("playful", "melancholy"),
        ("melancholy", "playful"),
    }

    def __init__(self, cooldown: float = 15):
        super().__init__(name="mood_shift", priority=3, cooldown_minutes=cooldown)

    def evaluate(self, state: dict) -> bool:
        moods = state.get("recent_moods", [])
        if len(moods) < 2:
            return False
        prev, cur = moods[-2], moods[-1]
        return (prev, cur) in self.MOOD_CONTRASTS

    def build_prompt(self, state: dict, dj_name: str) -> str:
        moods = state.get("recent_moods", [])
        prev, cur = moods[-2] if len(moods) >= 2 else ("?", "?"), moods[-1] if moods else "?"
        mood_zh = {"energetic": "燃", "chill": "轻松", "melancholy": "忧郁",
                    "playful": "俏皮", "nostalgic": "怀旧"}
        return (
            f"歌单情绪从{mood_zh.get(prev, prev)}突然变成{mood_zh.get(cur, cur)}。"
            f"请用轻松的语气点出这个反差，可以自嘲一句。不超过25个字。"
        )


# ── Rule Engine ──

class RuleEngine:
    def __init__(self, scheduler_config: dict | None = None):
        cfg = scheduler_config or {}
        rules_cfg = cfg.get("rules", {})

        self.rules: list[InterjectionRule] = []

        # Register built-in rules respecting enabled flags
        if rules_cfg.get("hour_chime", {}).get("enabled", True):
            r = HourChimeRule()
            r.cooldown_minutes = rules_cfg.get("hour_chime", {}).get("cooldown", 55)
            self.rules.append(r)

        if rules_cfg.get("weather_change", {}).get("enabled", True):
            r = WeatherChangeRule(cooldown=rules_cfg.get("weather_change", {}).get("cooldown", 30))
            self.rules.append(r)

        if rules_cfg.get("artist_streak", {}).get("enabled", True):
            threshold = rules_cfg.get("artist_streak", {}).get("threshold", 4)
            cooldown = rules_cfg.get("artist_streak", {}).get("cooldown", 15)
            self.rules.append(ArtistStreakRule(threshold=threshold, cooldown=cooldown))

        if rules_cfg.get("listening_duration", {}).get("enabled", True):
            milestones = rules_cfg.get("listening_duration", {}).get("milestones", [30, 60, 90, 120])
            cooldown = rules_cfg.get("listening_duration", {}).get("cooldown", 40)
            self.rules.append(ListeningDurationRule(milestones=milestones, cooldown=cooldown))

        if rules_cfg.get("song_count", {}).get("enabled", True):
            every_n = rules_cfg.get("song_count", {}).get("every_n", 8)
            cooldown = rules_cfg.get("song_count", {}).get("cooldown", 20)
            self.rules.append(SongCountRule(every_n=every_n, cooldown=cooldown))

        if rules_cfg.get("mood_shift", {}).get("enabled", True):
            cooldown = rules_cfg.get("mood_shift", {}).get("cooldown", 15)
            self.rules.append(MoodShiftRule(cooldown=cooldown))

    def evaluate_all(self, state: dict) -> list[InterjectionRule]:
        """Return triggered rules sorted by priority descending."""
        now = state.get("current_time", datetime.now()).timestamp()
        triggered = []
        for rule in self.rules:
            if rule.is_cooled_down(now) and rule.evaluate(state):
                triggered.append(rule)
        triggered.sort(key=lambda r: -r.priority)
        return triggered


def _period_name(hour: int) -> str:
    if hour < 6: return "凌晨"
    if hour < 9: return "早晨"
    if hour < 12: return "上午"
    if hour < 14: return "中午"
    if hour < 18: return "下午"
    if hour < 21: return "傍晚"
    return "深夜"
