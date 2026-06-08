"""Runtime path helpers for development and packaged desktop runs.

Development keeps using the repository root. Packaged Tauri sidecars pass
MUSICDJ_APP_DATA and MUSICDJ_RESOURCE_DIR so writable data lives outside the
installed application. MUSICDJ_APPDATA is accepted as a compatibility alias.
"""

from __future__ import annotations

import os
import json
import shutil
import sys
from pathlib import Path


APP_NAME = "Music DJ"


def _clean_env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip().strip('"')
    return Path(value).expanduser().resolve() if value else None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    env_root = _clean_env_path("MUSICDJ_RESOURCE_DIR")
    if env_root:
        return env_root
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return project_root()


def app_data_root() -> Path:
    env_root = _clean_env_path("MUSICDJ_APP_DATA")
    if not env_root:
        env_root = _clean_env_path("MUSICDJ_APPDATA")
    if env_root:
        return env_root
    return project_root()


def packaged_mode() -> bool:
    return bool(os.environ.get("MUSICDJ_APP_DATA") or os.environ.get("MUSICDJ_APPDATA"))


def _safe_user_id(uid: str | int | None) -> str:
    text = str(uid or "").strip()
    return "".join(ch for ch in text if ch.isalnum() or ch in ("-", "_"))[:80]


def _read_root_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_root_config(config: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def active_user_id() -> str:
    env_uid = _safe_user_id(os.environ.get("MUSICDJ_ACTIVE_USER_ID", ""))
    if env_uid:
        return env_uid
    config = _read_root_config()
    if "active_user_id" in config:
        return _safe_user_id(config.get("active_user_id", ""))
    return _safe_user_id((config.get("netease", {}) or {}).get("uid", ""))


def set_active_user_id(uid: str) -> str:
    safe_uid = _safe_user_id(uid)
    config = _read_root_config()
    config["active_user_id"] = safe_uid
    _write_root_config(config)
    return safe_uid


def users_root_dir() -> Path:
    return app_data_root() / "data" / "users"


def user_data_dir(uid: str | int | None) -> Path:
    safe_uid = _safe_user_id(uid)
    if not safe_uid:
        return app_data_root() / "data" / "_anonymous"
    return users_root_dir() / safe_uid


def data_dir() -> Path:
    return user_data_dir(active_user_id())


def logs_dir() -> Path:
    return app_data_root() / "logs"


def frontend_dir() -> Path:
    return resource_root() / "frontend"


def user_profile_dir() -> Path:
    return app_data_root() / "user_profile"


def config_path() -> Path:
    return app_data_root() / "config.json"


def default_config_path() -> Path:
    return resource_root() / "config_example.json"


def playlist_path() -> Path:
    return data_dir() / "playlist.json"


def personality_path() -> Path:
    return data_dir() / "personality.json"


def stats_path() -> Path:
    return data_dir() / "listening_stats.json"


def likes_path() -> Path:
    return data_dir() / "user_likes.json"


def memory_db_path() -> Path:
    return data_dir() / "state.db"


def ncm_cache_dir() -> Path:
    return data_dir() / ".ncm_cache"


def voice_memos_dir() -> Path:
    return data_dir() / "voice_memos"


def processed_history_dir() -> Path:
    return data_dir() / "listening_history" / "processed"


def raw_history_dir() -> Path:
    return data_dir() / "listening_history" / "raw"


def _copy_file_if_missing(src: Path, dst: Path) -> None:
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def ensure_runtime_layout() -> None:
    """Create writable runtime folders and seed minimal files when packaged."""
    users_root_dir().mkdir(parents=True, exist_ok=True)
    for path in (
        data_dir(),
        logs_dir(),
        user_profile_dir(),
        voice_memos_dir(),
        processed_history_dir(),
        raw_history_dir(),
        ncm_cache_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)

    if packaged_mode():
        _copy_file_if_missing(default_config_path(), config_path())

    playlist = playlist_path()
    if not playlist.exists():
        playlist.write_text('{\n  "songs": [],\n  "current_index": -1\n}\n', encoding="utf-8")

    stats = stats_path()
    if not stats.exists():
        stats.write_text('{\n  "song_plays": {}\n}\n', encoding="utf-8")

    personality = personality_path()
    if not personality.exists():
        personality.write_text("{}\n", encoding="utf-8")
