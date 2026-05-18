"""Runtime path helpers for development and packaged desktop runs.

Development keeps using the repository root.  Packaged Tauri sidecars pass
MUSICDJ_APP_DATA and MUSICDJ_RESOURCE_DIR so writable data lives outside the
installed application.
"""

from __future__ import annotations

import os
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
    if env_root:
        return env_root
    return project_root()


def packaged_mode() -> bool:
    return bool(os.environ.get("MUSICDJ_APP_DATA"))


def data_dir() -> Path:
    return app_data_root() / "data"


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
