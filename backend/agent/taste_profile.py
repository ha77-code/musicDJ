"""Build a rich, human-readable taste profile from listening history."""

import json
from pathlib import Path

from .paths import data_dir, processed_history_dir, raw_history_dir, user_profile_dir

DATA_DIR = data_dir()
PROCESSED_DIR = processed_history_dir()
RAW_DIR = raw_history_dir()
USER_PROFILE_DIR = user_profile_dir()


def build_taste_profile() -> str:
    sections = []

    summary = _load(PROCESSED_DIR / "training_summary.json")
    if summary:
        tiers = summary.get("tiers", {})
        sections.append(
            f"曲库共 {summary.get('total_songs', '?')} 首，"
            f"其中常听的 {tiers.get('core', '?')} 首，"
            f"点过红心 {tiers.get('liked', '?')} 首，"
            f"涉及 {summary.get('total_artists', '?')} 位歌手。"
        )

    # Top artists
    artists = _load(PROCESSED_DIR / "artist_stats.json")
    if artists:
        lines = []
        for a in artists.get("artists", [])[:10]:
            lines.append(f"  {a['name']} — {a['plays']}次播放，{a['songs']}首歌")
        sections.append("### 最爱歌手\n" + "\n".join(lines))

    # Top songs
    catalog = _load(PROCESSED_DIR / "training_songs_top300.json")
    if catalog:
        songs = catalog.get("songs", [])
        lines = []
        for s in songs[:12]:
            weight = s.get("weight", 0)
            star = " ⭐ 神曲" if weight > 0.8 else (" ❤️ 心头好" if weight > 0.4 else "")
            lines.append(f"  {s['name']} / {s['artist']}{star}")
        sections.append("### 最爱歌曲\n（注意：次数多=喜欢这首歌，不等同喜欢这个歌手）\n" + "\n".join(lines))

    # Total listening
    total = _load(RAW_DIR / "total.json")
    if total:
        sec = total.get("data", {}).get("totalDuration", 0)
        hr = sec // 3600
        sections.append(f"### 听歌统计\n累计听歌约 {hr} 小时（{sec // 86400} 天）。")

    return "\n\n".join(sections)


def build_listener_state(time_info: dict, weather_desc: str, user_activity: str) -> str:
    parts = [f"当前时间：{time_info['time_str']}"]
    if time_info["is_weekend"]:
        parts.append("今天是周末，适合放松")
    else:
        parts.append("今天是工作日")
    if weather_desc:
        parts.append(f"天气：{weather_desc}")
    if user_activity:
        activity_labels = {
            "studying": "听众正在学习，需要安静的背景音乐，不要选太吵的歌",
            "working": "听众正在工作，需要专注，选不打扰的歌",
            "chilling": "听众在放松，选有氛围感的歌",
            "working_out": "听众在运动，选有节奏有能量的歌",
            "driving": "听众在开车，选有律动感的歌",
            "commuting": "听众在通勤，选轻松愉快的歌",
            "before_sleep": "听众准备睡觉，选安静的、助眠的歌",
        }
        parts.append(activity_labels.get(user_activity, f"听众正在{user_activity}"))
    return "；".join(parts)


def _load(path: Path) -> dict | None:
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def build_taste_profile_search() -> dict:
    """Build a search-friendly taste profile dict for MusicDiscovery.

    Returns {top_artists: [...], genres: [...]} for generating
    Netease search queries. Uses the same data sources as build_taste_profile()
    but in a machine-readable format.
    """
    profile = {
        "top_artists": [],
        "genres": [],
        "language_queries": [
            "J-pop",
            "K-pop",
            "Japanese city pop",
            "Korean R&B",
            "English pop",
            "anime OST",
        ],
    }

    # Top artists from stats
    artists = _load(PROCESSED_DIR / "artist_stats.json")
    if artists:
        profile["top_artists"] = [
            a["name"] for a in artists.get("artists", [])[:8]
        ]

    # Genres from user profile markdown + listening data
    taste_md = USER_PROFILE_DIR / "taste.md"
    if taste_md.exists():
        text = taste_md.read_text(encoding="utf-8")
        # Extract genre keywords
        genre_map = {
            "轻音乐": ["轻音乐", "钢琴", "纯音乐"],
            "爵士": ["爵士", "Bossa Nova"],
            "独立": ["独立", "另类"],
            "J-POP": ["J-POP", "动漫OST", "City Pop"],
            "K-POP": ["K-POP", "Korean", "韩流", "韩国", "Korean R&B"],
            "R&B": ["R&B"],
            "电子": ["电子", "Lo-fi", "氛围电子"],
            "民谣": ["民谣"],
            "摇滚": ["摇滚", "后摇"],
            "Hip-Hop": ["Hip-Hop"],
            "流行": ["华语流行", "欧美流行"],
        }
        found = []
        text_lower = text.lower()
        for genre_key, keywords in genre_map.items():
            if any(kw.lower() in text_lower for kw in keywords):
                found.append(genre_key)
        profile["genres"] = found

    return profile
