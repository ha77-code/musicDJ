"""
Music DJ - 单文件 Python 后端
轻量、本地、人格可养成的智能音乐 DJ
"""
import json
import os
import random
import time
import base64
import hashlib
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory, send_file, Response, redirect

from agent.dj_brain import DJBrain
from agent.realtime_voice import RealtimeVoiceClient
from agent.scheduler import DJScheduler
from agent.tts_provider import TTSProvider

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "config.json"
PLAYLIST_PATH = DATA_DIR / "playlist.json"
PERSONALITY_PATH = DATA_DIR / "personality.json"
VOICE_MEMOS_DIR = DATA_DIR / "voice_memos"
FRONTEND_DIR = BASE_DIR / "frontend"
STATS_PATH = DATA_DIR / "listening_stats.json"
LIKES_PATH = DATA_DIR / "user_likes.json"

# ── App ────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


def load_json(path, default=None):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[json] Failed to load {path}: {e}")
    return default if default is not None else {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_config():
    return load_json(CONFIG_PATH, {})


# ── NCM Decryption ────────────────────────────────────
NCM_MAGIC = b"CTENFDAM"
NCM_AES_KEY = bytes.fromhex("687a4852416d736f356b496e62617857")  # hzHRAmso5kInbaxW
NCM_CACHE_DIR = BASE_DIR / "data" / ".ncm_cache"


def _build_key_box(key_data):
    """Build decryption S-box from decrypted key."""
    box = bytearray(range(256))
    key_len = len(key_data)
    j = 0
    for i in range(256):
        j = (j + box[i] + key_data[i % key_len]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def convert_ncm(filepath):
    """Decrypt a .ncm file and return path to the decrypted audio file.
    Returns (output_path, music_format, cover_data, info_dict) or (None, None, None, None)."""
    path = Path(filepath)
    if path.suffix.lower() != ".ncm":
        return None, None, None, None

    try:
        with open(filepath, "rb") as f:
            data = f.read()

        # Verify magic
        if data[:8] != NCM_MAGIC:
            return None, None, None, None

        # Skip magic(8) + gap(2)
        pos = 10

        # Key length
        key_len = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4

        # Encrypted key data
        enc_key = data[pos:pos + key_len]
        pos += key_len

        # Decrypt key with AES-128-ECB
        from Crypto.Cipher import AES
        cipher = AES.new(NCM_AES_KEY, AES.MODE_ECB)
        decrypted_key = cipher.decrypt(enc_key)
        # Unpad PKCS7
        pad = decrypted_key[-1]
        if pad < 0x20:
            decrypted_key = decrypted_key[:-pad]

        # Build key box
        key_box = _build_key_box(decrypted_key)

        # Music info length
        info_len = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4

        # Music info JSON
        info_json = data[pos:pos + info_len]
        pos += info_len

        import json as _json
        try:
            info = _json.loads(info_json)
        except Exception:
            info = {}

        music_format = info.get("format", "mp3")
        music_name = info.get("musicName", path.stem)
        artist = info.get("artist", [])

        # Cover image: crc32(4) + image_len(4) + image_data
        pos += 4  # skip crc32
        cover_data = None
        if pos + 4 < len(data):
            cover_len = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            if cover_len > 0 and pos + cover_len <= len(data):
                cover_data = data[pos:pos + cover_len]
                pos += cover_len

        # Remaining: encrypted audio
        audio_offset = pos
        audio_size = len(data) - audio_offset

        # Decrypt audio in chunks
        NCM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out_path = NCM_CACHE_DIR / f"{path.stem}.{music_format}"

        if out_path.exists():
            return str(out_path), music_format, cover_data, info

        # XOR decrypt: audio[i] ^= key_box[(i + 1) % 256]
        decrypted = bytearray()
        chunk_size = 0x8000  # 32KB chunks
        for chunk_start in range(0, audio_size, chunk_size):
            chunk = bytearray(data[audio_offset + chunk_start: audio_offset + min(chunk_start + chunk_size, audio_size)])
            for j in range(len(chunk)):
                chunk[j] ^= key_box[(chunk_start + j + 1) & 0xFF]
            decrypted.extend(chunk)

        with open(out_path, "wb") as f:
            f.write(decrypted)

        return str(out_path), music_format, cover_data, info

    except Exception as e:
        print(f"[NCM] Failed to decrypt {filepath}: {e}")
        return None, None, None, None


# ── Music Scanner ──────────────────────────────────────
def scan_music_directory(dir_path):
    """Scan a directory recursively for music files, extract metadata."""
    extensions = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac", ".wma", ".opus", ".ncm"}
    songs = []
    music_dir = Path(dir_path)

    if not music_dir.exists():
        return songs

    # Try importing mutagen for better metadata
    mutagen_available = False
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3
        mutagen_available = True
    except ImportError:
        pass

    for f in music_dir.rglob("*"):
        if f.suffix.lower() not in extensions:
            continue

        # Handle NCM files: decrypt first
        actual_path = f
        cover_data = None
        ncm_info = None

        if f.suffix.lower() == ".ncm":
            dec_path, fmt, cover_data, ncm_info = convert_ncm(str(f))
            if dec_path is None:
                continue
            actual_path = Path(dec_path)

        song = extract_song_info(actual_path, mutagen_available)

        # Override metadata from NCM embedded info
        if ncm_info:
            song["path"] = str(f)  # store original ncm path
            song["ncm_converted"] = str(actual_path)
            if ncm_info.get("musicName"):
                song["title"] = ncm_info["musicName"]
            if ncm_info.get("artist"):
                if isinstance(ncm_info["artist"], list):
                    song["artist"] = " / ".join(str(a[0]) if isinstance(a, list) else str(a) for a in ncm_info["artist"])
                else:
                    song["artist"] = str(ncm_info["artist"])
            if ncm_info.get("album"):
                song["album"] = str(ncm_info["album"])

        # Save cover image from NCM
        if cover_data:
            cover_name = hashlib.md5(cover_data).hexdigest()[:12] + ".jpg"
            cover_path = NCM_CACHE_DIR / cover_name
            if not cover_path.exists():
                cover_path.write_bytes(cover_data)
            song["cover"] = f"/data/.ncm_cache/{cover_name}"

        songs.append(song)

    return songs


def extract_song_info(filepath, use_mutagen):
    """Extract song metadata from a music file."""
    info = {
        "path": str(filepath),
        "title": filepath.stem,
        "artist": "未知艺术家",
        "album": "未知专辑",
        "duration": 0,
        "tags": [],
        "cover": None,
    }

    if use_mutagen:
        try:
            from mutagen import File as MutagenFile
            from mutagen.id3 import ID3

            mf = MutagenFile(str(filepath))
            if mf is not None:
                if hasattr(mf, "info") and hasattr(mf.info, "length"):
                    info["duration"] = int(mf.info.length)

                # Try ID3 tags
                if filepath.suffix.lower() == ".mp3":
                    try:
                        id3 = ID3(str(filepath))
                        if "TIT2" in id3:
                            info["title"] = str(id3["TIT2"])
                        if "TPE1" in id3:
                            info["artist"] = str(id3["TPE1"])
                        if "TALB" in id3:
                            info["album"] = str(id3["TALB"])
                    except Exception:
                        pass

                # Generic tags
                tags = mf.tags if hasattr(mf, "tags") and mf.tags else {}
                if tags:
                    info["title"] = str(tags.get("title", info["title"]))
                    info["artist"] = str(tags.get("artist", info["artist"]))
                    info["album"] = str(tags.get("album", info["album"]))
        except Exception:
            pass

    return info


# ── Weather ────────────────────────────────────────────
def get_weather_data():
    """Fetch current weather from OpenWeatherMap."""
    config = get_config()
    api_key = config.get("weather", {}).get("api_key", "")
    city = config.get("weather", {}).get("city", "北京")
    lang = config.get("weather", {}).get("lang", "zh_cn")

    if not api_key:
        return {"status": "no_key", "description": "晴", "temp": 20, "icon": "01d"}

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        resp = requests.get(
            url,
            params={"q": city, "appid": api_key, "lang": lang, "units": "metric"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "ok",
                "description": data["weather"][0]["description"],
                "temp": round(data["main"]["temp"]),
                "icon": data["weather"][0]["icon"],
                "city": city,
            }

        return {"status": "error", "description": "晴", "temp": 20, "icon": "01d", "error": resp.text}
    except Exception as e:
        return {"status": "error", "description": "晴", "temp": 20, "icon": "01d", "error": str(e)}


# ── Netease API Proxy ─────────────────────────────────
def check_netease_api():
    """Check if NeteaseCloudMusicApi is running."""
    config = get_config()
    if not config.get("netease", {}).get("enabled", True):
        return False
    host = config.get("netease", {}).get("api_host", "http://localhost:3000")
    try:
        resp = requests.get(f"{host}/search?keywords=test&limit=1", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def proxy_netease(endpoint, params=None):
    """Make a request to NeteaseCloudMusicApi and return JSON."""
    config = get_config()
    host = config.get("netease", {}).get("api_host", "http://localhost:3000")
    cookie = config.get("netease", {}).get("cookie", "")

    url = f"{host}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie

    try:
        if params:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
        else:
            resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return {"code": resp.status_code, "error": resp.text}
    except Exception as e:
        return {"code": -1, "error": str(e)}


# ── Listening Stats ───────────────────────────────────
def load_stats():
    return load_json(STATS_PATH, {
        "total_seconds": 0,
        "sessions": [],
        "song_plays": {},
        "daily_history": {},
    })


def save_stats(data):
    save_json(STATS_PATH, data)


def get_song_key(song):
    """Generate a unique key for tracking song plays."""
    sid = song.get("netease_id") or song.get("path", "")
    source = song.get("source", "local")
    return f"{source}_{sid}"


def get_fallback_transition(weather_desc, tags):
    """Get a fallback transition based on weather and emoji tags."""
    personality = load_json(PERSONALITY_PATH, {})
    fallbacks = personality.get("fallback_transitions", {})

    # Determine weather category key
    weather_key = "default"
    if weather_desc:
        for w in ["雨", "雪", "阴", "晴", "风", "夜"]:
            if w in weather_desc:
                weather_key = w
                break

    weather_fallbacks = fallbacks.get(weather_key, fallbacks.get("default", {}))

    # Match by tag
    if tags:
        for tag in tags:
            if tag in weather_fallbacks:
                return random.choice(weather_fallbacks[tag])

    # Default tag
    if "default" in weather_fallbacks:
        return random.choice(weather_fallbacks["default"])

    # Ultimate fallback
    return "不用多说，听就完了。"


# ── API Routes ─────────────────────────────────────────
@app.route("/")
def serve_index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(str(FRONTEND_DIR), filename)


@app.route("/api/status")
def api_status():
    config = get_config()
    return jsonify({
        "running": True,
        "dj_name": config.get("dj", {}).get("name", "clauseekio"),
        "llm_available": dj_brain.llm.check_available() if dj_brain else False,
        "netease_available": check_netease_api(),
        "playlist_count": len(load_json(PLAYLIST_PATH, {}).get("songs", [])),
        "current_song": load_json(PLAYLIST_PATH, {}).get("current_index", -1),
    })


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        new_config = request.get_json()
        save_json(CONFIG_PATH, new_config)
        return jsonify({"ok": True})
    return jsonify(get_config())


@app.route("/api/playlist")
def api_playlist():
    return jsonify(load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1}))


@app.route("/api/playlist/import", methods=["POST"])
def api_playlist_import():
    """Batch import songs into playlist. Deduplicates by netease_id or path."""
    data = request.get_json()
    new_songs = data.get("songs", [])
    if not new_songs:
        return jsonify({"error": "songs array required"}), 400

    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    existing = playlist.get("songs", [])
    existing_netease = {s["netease_id"] for s in existing if s.get("netease_id")}
    existing_paths = {s["path"] for s in existing if s.get("path")}

    added = 0
    for song in new_songs:
        song.setdefault("tags", [])
        song.setdefault("source", "local")
        nid = song.get("netease_id")
        if nid:
            if nid in existing_netease:
                continue
            existing_netease.add(nid)
        else:
            p = song.get("path", "")
            if p in existing_paths:
                continue
            existing_paths.add(p)
        existing.append(song)
        added += 1

    playlist["songs"] = existing
    save_json(PLAYLIST_PATH, playlist)
    return jsonify({"ok": True, "added": added, "total": len(existing)})


@app.route("/api/playlist/add", methods=["POST"])
def api_playlist_add():
    """Add a single song to the playlist."""
    data = request.get_json()
    song = data.get("song", {})
    if not song:
        return jsonify({"error": "song data required"}), 400

    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    songs = playlist.get("songs", [])

    # Deduplicate: skip if same netease_id or path already exists
    if song.get("netease_id"):
        exists = any(s.get("netease_id") == song["netease_id"] for s in songs)
    else:
        exists = any(s.get("path") == song.get("path", "") for s in songs)

    if not exists:
        song.setdefault("tags", [])
        song.setdefault("source", "local")
        songs.append(song)

    playlist["songs"] = songs
    save_json(PLAYLIST_PATH, playlist)
    return jsonify({"ok": True, "total": len(songs), "added": not exists})


@app.route("/api/playlist/scan", methods=["POST"])
def api_playlist_scan():
    data = request.get_json()
    dir_path = data.get("path", "")
    if not dir_path or not os.path.isdir(dir_path):
        return jsonify({"error": "无效的目录路径"}), 400

    songs = scan_music_directory(dir_path)
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    existing_paths = {s["path"] for s in playlist.get("songs", [])}

    new_songs = []
    for s in songs:
        if s["path"] not in existing_paths:
            new_songs.append(s)

    playlist.setdefault("songs", []).extend(new_songs)
    save_json(PLAYLIST_PATH, playlist)
    return jsonify({"added": len(new_songs), "total": len(playlist["songs"]), "new_songs": new_songs})


@app.route("/api/playlist/reorder", methods=["POST"])
def api_playlist_reorder():
    """Reorder playlist: {from_index, to_index}"""
    data = request.get_json()
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    songs = playlist.get("songs", [])
    from_idx = data.get("from_index", 0)
    to_idx = data.get("to_index", 0)

    if 0 <= from_idx < len(songs) and 0 <= to_idx < len(songs):
        song = songs.pop(from_idx)
        songs.insert(to_idx, song)
        # Adjust current_index
        cur = playlist.get("current_index", -1)
        if cur == from_idx:
            playlist["current_index"] = to_idx
        elif from_idx < cur <= to_idx:
            playlist["current_index"] = cur - 1
        elif to_idx <= cur < from_idx:
            playlist["current_index"] = cur + 1

    playlist["songs"] = songs
    save_json(PLAYLIST_PATH, playlist)
    return jsonify({"ok": True, "playlist": playlist})


@app.route("/api/playlist/song/<int:index>", methods=["DELETE"])
def api_playlist_remove(index):
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    songs = playlist.get("songs", [])
    if 0 <= index < len(songs):
        removed = songs.pop(index)
        playlist["songs"] = songs
        if playlist["current_index"] >= len(songs):
            playlist["current_index"] = len(songs) - 1
        save_json(PLAYLIST_PATH, playlist)
        return jsonify({"ok": True, "removed": removed})
    return jsonify({"error": "索引超出范围"}), 400


@app.route("/api/playlist/current", methods=["POST"])
def api_playlist_set_current():
    """Set currently playing song index."""
    data = request.get_json()
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    idx = data.get("index", -1)
    playlist["current_index"] = idx
    save_json(PLAYLIST_PATH, playlist)
    return jsonify({"ok": True, "current_index": idx})


@app.route("/api/weather")
def api_weather():
    weather = get_weather_data()
    return jsonify({
        **weather,
        "time": datetime.now().strftime("%H:%M"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    })


@app.route("/api/transition", methods=["POST"])
def api_transition():
    """Simple fallback transition (word library). Main transitions go through /api/agent/transition."""
    data = request.get_json()
    next_song = data.get("next_song", {})
    weather = get_weather_data()
    fallback_text = get_fallback_transition(weather.get("description", "晴"), next_song.get("tags", []))
    return jsonify({
        "text": fallback_text,
        "method": "fallback",
        "weather": weather.get("description", ""),
    })


@app.route("/api/audio")
def api_audio():
    """Stream an audio file by path or redirect to Netease CDN."""
    filepath = request.args.get("path", "")
    source = request.args.get("source", "local")
    netease_id = request.args.get("netease_id", "")
    proxy = request.args.get("proxy", "0") == "1"  # server-side streaming proxy
    range_header = request.headers.get("Range")

    # Netease song: get streaming URL and redirect
    if source == "netease" and netease_id:
        result = proxy_netease("/song/url", {"id": netease_id, "br": 320000})
        songs = result.get("data", [])
        url = None
        if songs and songs[0].get("url"):
            url = songs[0]["url"]
        else:
            result = proxy_netease("/song/url", {"id": netease_id, "br": 128000})
            songs = result.get("data", [])
            if songs and songs[0].get("url"):
                url = songs[0]["url"]
        if url:
            # Server-side proxy: more reliable, avoids CDN geo/CORS issues
            if proxy:
                try:
                    proxy_headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://music.163.com/",
                    }
                    if range_header:
                        proxy_headers["Range"] = range_header

                    resp = requests.get(url, headers=proxy_headers, timeout=30, stream=True)
                    if resp.status_code in (200, 206):
                        content_type = resp.headers.get("Content-Type", "audio/mpeg")
                        out_headers = {
                            "Accept-Ranges": resp.headers.get("Accept-Ranges", "bytes"),
                            "Cache-Control": "no-cache",
                        }
                        content_len = resp.headers.get("Content-Length")
                        if content_len:
                            out_headers["Content-Length"] = content_len
                        content_range = resp.headers.get("Content-Range")
                        if content_range:
                            out_headers["Content-Range"] = content_range

                        return Response(resp.iter_content(chunk_size=65536),
                                        status=resp.status_code,
                                        content_type=content_type,
                                        headers=out_headers)
                except Exception as e:
                    print(f"[audio-proxy] Streaming proxy failed: {e}, falling back to redirect")

            # Direct redirect
            resp = redirect(url, code=302)
            resp.headers["Referer"] = "https://music.163.com/"
            return resp
        return jsonify({"error": "无法获取播放链接，可能需要网易云 Cookie"}), 404

    # Check if this is an NCM file in the playlist
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    for song in playlist.get("songs", []):
        if song.get("path") == filepath and song.get("ncm_converted"):
            ncm_path = Path(song["ncm_converted"])
            if ncm_path.exists():
                return send_file(ncm_path, mimetype="audio/*")

    path = Path(filepath)
    if not path.exists() or not path.is_file():
        return jsonify({"error": "file not found"}), 404
    return send_file(path, mimetype="audio/*")

@app.route("/api/tag", methods=["POST"])
def api_tag():
    """Set emoji tags for a song."""
    data = request.get_json()
    song_index = data.get("index", -1)
    new_tags = data.get("tags", [])

    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    songs = playlist.get("songs", [])

    if 0 <= song_index < len(songs):
        songs[song_index]["tags"] = new_tags
        playlist["songs"] = songs
        save_json(PLAYLIST_PATH, playlist)
        return jsonify({"ok": True, "song": songs[song_index]})

    return jsonify({"error": "索引超出范围"}), 400


@app.route("/api/personality", methods=["GET", "POST"])
def api_personality():
    if request.method == "POST":
        data = request.get_json()
        save_json(PERSONALITY_PATH, data)
        return jsonify({"ok": True})
    return jsonify(load_json(PERSONALITY_PATH, {}))


@app.route("/api/voice-memo", methods=["POST"])
def api_voice_memo():
    """Save a voice memo recording."""
    if "audio" not in request.files:
        return jsonify({"error": "未收到音频文件"}), 400

    audio = request.files["audio"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"memo_{timestamp}.webm"
    VOICE_MEMOS_DIR.mkdir(parents=True, exist_ok=True)
    audio.save(str(VOICE_MEMOS_DIR / filename))
    return jsonify({"ok": True, "filename": filename})


@app.route("/api/voice-memos")
def api_voice_memos():
    """List all voice memos."""
    memos = []
    if VOICE_MEMOS_DIR.exists():
        for f in sorted(VOICE_MEMOS_DIR.glob("memo_*.webm"), reverse=True):
            memos.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "created": datetime.fromtimestamp(f.stat().st_ctime).isoformat(),
            })
    return jsonify(memos)


@app.route("/data/voice_memos/<path:filename>")
def serve_voice_memo(filename):
    return send_from_directory(str(VOICE_MEMOS_DIR), filename)


@app.route("/data/.ncm_cache/<path:filename>")
def serve_ncm_cache(filename):
    return send_from_directory(str(NCM_CACHE_DIR), filename)


# ── Netease API Routes ───────────────────────────────
@app.route("/api/netease/search", methods=["POST"])
def api_netease_search():
    data = request.get_json()
    keywords = data.get("keywords", "")
    limit = data.get("limit", 20)
    page = data.get("page", 1)
    if not keywords:
        return jsonify({"error": "keywords required"}), 400
    result = proxy_netease("/search", {"keywords": keywords, "limit": limit, "offset": (page - 1) * limit, "type": 1})
    return jsonify(result)


@app.route("/api/netease/song/url", methods=["POST"])
def api_netease_song_url():
    data = request.get_json()
    song_id = data.get("id", "")
    br = data.get("br", 320000)
    if not song_id:
        return jsonify({"error": "id required"}), 400
    result = proxy_netease("/song/url", {"id": song_id, "br": br})
    return jsonify(result)


@app.route("/api/netease/song/detail", methods=["POST"])
def api_netease_song_detail():
    data = request.get_json()
    ids = data.get("ids", "")
    if not ids:
        return jsonify({"error": "ids required"}), 400
    result = proxy_netease("/song/detail", {"ids": str(ids)})
    return jsonify(result)


@app.route("/api/netease/song/lyric", methods=["POST"])
def api_netease_song_lyric():
    data = request.get_json()
    song_id = data.get("id", "")
    if not song_id:
        return jsonify({"error": "id required"}), 400
    result = proxy_netease("/lyric", {"id": song_id})
    return jsonify(result)


@app.route("/api/netease/likelist", methods=["POST"])
def api_netease_likelist():
    """Get user's liked songs list. Requires cookie with uid."""
    data = request.get_json()
    uid = data.get("uid", "")
    config = get_config()
    if not uid:
        uid = config.get("netease", {}).get("uid", "")
    if not uid:
        return jsonify({"error": "uid required — set netease.uid in config.json"}), 400
    result = proxy_netease("/likelist", {"uid": uid})
    return jsonify(result)


@app.route("/api/netease/user/playlist", methods=["POST"])
def api_netease_user_playlist():
    """Get user's playlists. Requires cookie with uid."""
    data = request.get_json()
    uid = data.get("uid", "")
    config = get_config()
    if not uid:
        uid = config.get("netease", {}).get("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    result = proxy_netease("/user/playlist", {"uid": uid})
    return jsonify(result)


@app.route("/api/netease/playlist/tracks", methods=["POST"])
def api_netease_playlist_tracks():
    """Get tracks from a playlist by ID."""
    data = request.get_json()
    playlist_id = data.get("id", "")
    limit = data.get("limit", 500)
    if not playlist_id:
        return jsonify({"error": "playlist id required"}), 400
    result = proxy_netease("/playlist/track/all", {"id": playlist_id, "limit": limit})
    return jsonify(result)


@app.route("/api/netease/user/record", methods=["POST"])
def api_netease_user_record():
    """Get user's listening history. type=0 (weekly), type=1 (all-time)."""
    data = request.get_json()
    uid = data.get("uid", "")
    record_type = data.get("type", 0)
    config = get_config()
    if not uid:
        uid = config.get("netease", {}).get("uid", "")
    if not uid:
        return jsonify({"error": "uid required"}), 400
    result = proxy_netease("/user/record", {"uid": uid, "type": record_type})
    return jsonify(result)


@app.route("/api/netease/listen/year/report", methods=["POST"])
def api_netease_listen_year_report():
    """听歌足迹 - 年度听歌报告。body: {year: 2025}"""
    data = request.get_json() or {}
    params = {}
    if data.get("year"):
        params["year"] = data["year"]
    result = proxy_netease("/listen/data/year/report", params)
    return jsonify(result)


@app.route("/api/netease/listen/total", methods=["POST"])
def api_netease_listen_total():
    """听歌足迹 - 总收听时长。"""
    result = proxy_netease("/listen/data/total")
    return jsonify(result)


@app.route("/api/netease/listen/report", methods=["POST"])
def api_netease_listen_report():
    """听歌足迹 - 周/月/年报告。body: {type: "week"|"month"|"year", endTime: "2025-05-07"}"""
    data = request.get_json() or {}
    params = {}
    if data.get("type"):
        params["type"] = data["type"]
    if data.get("endTime"):
        params["endTime"] = data["endTime"]
    result = proxy_netease("/listen/data/report", params)
    return jsonify(result)


@app.route("/api/netease/listen/recent", methods=["POST"])
def api_netease_listen_recent():
    """最近听歌列表。"""
    result = proxy_netease("/recent/listen/list")
    return jsonify(result)


# ── Agent Routes ─────────────────────────────────────
# Global DJBrain and DJScheduler and TTSProvider instances (initialized in main)
dj_brain = None
scheduler = None
tts_provider = None
current_mode = "dj"  # "normal" | "dj"


@app.route("/api/mode", methods=["GET", "POST"])
def api_mode():
    """Get or set the current playback mode."""
    global current_mode
    if request.method == "POST":
        data = request.get_json() or {}
        mode = data.get("mode", "dj")
        if mode in ("normal", "dj"):
            current_mode = mode
            # Pause scheduler in normal mode
            if scheduler:
                if mode == "normal":
                    scheduler.pause()
                else:
                    scheduler.resume()
        return jsonify({"mode": current_mode})
    return jsonify({"mode": current_mode})


@app.route("/api/agent/transition", methods=["POST"])
def api_agent_transition():
    """Enhanced transition with structured output (say/reason/segue/mood/action).
    In normal mode: just play next song sequentially, no AI.
    In DJ mode: LLM selects next song + generates DJ commentary."""
    global current_mode

    data = request.get_json()
    current_song = data.get("current_song", {})
    weather_data = data.get("weather", None)
    history = data.get("history", [])
    user_activity = data.get("user_activity", "")
    chat_context = data.get("chat_context", "")

    # ── Normal mode: simple sequential, no AI ──
    if current_mode == "normal":
        playlist_data = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
        songs = playlist_data.get("songs", [])
        cur_idx = playlist_data.get("current_index", -1)
        next_idx = (cur_idx + 1) % len(songs) if songs else 0
        next_song = songs[next_idx] if songs and next_idx < len(songs) else {}
        return jsonify({
            "say": "",
            "reason": "",
            "segue": "",
            "mood": "",
            "action": "play_next",
            "method": "normal",
            "next_index": next_idx,
            "next_title": next_song.get("title", ""),
            "next_artist": next_song.get("artist", ""),
        })

    # ── DJ mode: full AI orchestration ──
    if not dj_brain:
        return api_transition()

    # Pass playlist for song selection mode
    playlist_data = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    playlist = playlist_data.get("songs", [])

    action, selected_song = dj_brain.think_transition(
        current_song, None, weather_data, history, user_activity, playlist,
        chat_context=chat_context)

    resp = {
        "say": action.say,
        "reason": action.reason,
        "segue": action.segue,
        "mood": action.mood,
        "action": action.action,
        "method": "agent",
    }
    if selected_song:
        resp["selected_song"] = selected_song
    return jsonify(resp)


@app.route("/api/agent/greet", methods=["POST"])
def api_agent_greet():
    """Generate a DJ greeting when user starts listening. Normal mode: no greeting."""
    global current_mode
    if current_mode == "normal":
        return jsonify({"say": "", "mood": ""})

    if not dj_brain:
        return jsonify({"say": "欢迎回来。"})
    data = request.get_json() or {}
    weather_data = data.get("weather", None)
    action = dj_brain.greet(weather_data)
    return jsonify({"say": action.say, "mood": action.mood})


@app.route("/api/agent/stream")
def api_agent_stream():
    """SSE endpoint for real-time DJ state updates and interjections."""
    def generate():
        import time as _time
        while True:
            if dj_brain:
                state = dj_brain.get_stream_state()
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"

            # Check for pending interjections from scheduler
            if scheduler:
                interj = scheduler.get_pending_interjection()
                if interj:
                    yield f"event: interjection\ndata: {json.dumps(interj, ensure_ascii=False)}\n\n"

            _time.sleep(2)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/agent/reaction", methods=["POST"])
def api_agent_reaction():
    """Record user reaction to a transition (like/skip)."""
    data = request.get_json()
    song_index = data.get("song_index", -1)
    reaction = data.get("reaction", "none")
    if dj_brain:
        dj_brain.record_reaction(song_index, reaction)
    return jsonify({"ok": True})


@app.route("/api/agent/history")
def api_agent_history():
    """Get recent transition history."""
    n = request.args.get("n", 20, type=int)
    if not dj_brain:
        return jsonify([])
    history = dj_brain.memory.get_recent_transitions(n)
    return jsonify(history)


@app.route("/api/agent/interjection")
def api_agent_interjection():
    """Get any pending proactive interjection from the scheduler."""
    if not scheduler:
        return jsonify(None)
    interj = scheduler.get_pending_interjection()
    return jsonify(interj)


@app.route("/api/agent/memory-summary")
def api_agent_memory_summary():
    """Get memory stats summary."""
    if not dj_brain:
        return jsonify({})
    return jsonify(dj_brain.memory.get_stats_summary())


@app.route("/api/agent/chat", methods=["POST"])
def api_agent_chat():
    """Streaming AI DJ chat with personalized DJ persona."""
    data = request.get_json()
    message = data.get("message", "")
    chat_history = data.get("history", [])

    if not dj_brain or not message:
        return jsonify({"error": "DJ agent not ready"}), 503

    personality = dj_brain.personality
    taste = dj_brain.context.get_music_taste_summary()
    time_info = dj_brain.context.get_time_info()
    profile_context = dj_brain._get_profile_context()

    # Current song context
    current_song_info = data.get("current_song", {})
    cur_title = current_song_info.get("title", "")
    cur_artist = current_song_info.get("artist", "")
    cur_str = f"正在播放：{cur_artist} — {cur_title}" if cur_title else "暂无正在播放的歌曲"

    weather_str = ""
    try:
        w = get_weather_data()
        if w.get("status") == "ok":
            weather_str = f"天气：{w.get('description','')} {w.get('temp','')}°C"
    except Exception:
        pass

    system_prompt = f"""你是{personality['name']}，一个能控制播放器的AI音乐DJ。你不是AI，你是一个有血有肉的人。

## 你的性格
{personality['style']}

## 关于听众（你很了解TA）
{profile_context}

## 听众音乐口味
{taste}

## 当前状态
{cur_str}
{weather_str}
时间：{time_info['time_str']}
{time_info['activity_hint']}

## 你可以控制播放器
你是一个真实的DJ，可以操控播放器播放任何歌曲。标记放在回复末尾，不会显示。

可用动作：
- [[skip]] — 切歌，下一首我会从网易云给你选
- [[search:关键词]] — 搜索网易云曲库
- [[play:歌名—歌手]] — 直接从网易云搜索并播放这首歌（不限于歌单里的！任何歌都可以）
- [[recommend:歌名—歌手]] — 推荐一首歌
- [[volume:80]] — 调整音量

重要：[[play:]]和[[search:]]都会搜索网易云的海量曲库，不是只搜你的本地歌单。想放什么直接说，我能找到。

## 说话方式
- 像跟老朋友深夜连麦聊天，不是播新闻
- 用语气词：嗯、嘿、诶、啧、嘶、害、说实话、讲真
- 用口语词：巨好听、上头、绝了、离谱
- 句子长短交错，可以有停顿（用……）
- 绝对不要用括号描述动作
- 先自然回复，再加动作标记
- 不要长篇大论，每条 15-80 字
- 如果没有操作需求，就正常聊天，不加标记
- 标记必须放在最后，一行一个

## 示例
用户："切歌" → 你："好嘞，这首差不多了，换一首更有感觉的。[[skip]]"
用户："搜一下周杰伦的晴天" → 你："晴天啊，经典中的经典！我帮你搜。[search:周杰伦 晴天]"
用户："放G.E.M.邓紫棋的龙卷风" → 你："龙卷风，你最喜欢的邓紫棋！马上安排。[play:龙卷风—G.E.M.邓紫棋]"
用户："推荐一首适合现在听的歌" → 你："现在在下雨，半夜了…来首LANY的吧，超级适合。[recommend:ILYSB—LANY]" """

    def generate():
        full_text = ""
        try:
            for token in dj_brain.llm.generate_stream(system_prompt, message,
                                                       chat_history if chat_history else None):
                if token is None:
                    yield f"data: {json.dumps({'error': 'API failed'}, ensure_ascii=False)}\n\n"
                    return
                full_text += token
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'full_text': full_text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/agent/chat/voice", methods=["POST"])
def api_agent_chat_voice():
    """Streaming AI chat with real-time voice output.

    Flow:
    1. DeepSeek generates DJ response text (preserving personality)
    2. Text sent to Volcano real-time dialogue API
    3. Audio chunks streamed via SSE with text tokens

    Fallback: Phase 2 SSML TTS if real-time API unavailable.
    """
    import queue as _queue
    import threading as _threading
    import re as _re

    data = request.get_json() or {}
    message = data.get("message", "")
    chat_history = data.get("history", [])
    voice_mode = str(data.get("voice_mode", "realtime")).lower()
    if voice_mode not in {"realtime", "tts"}:
        voice_mode = "realtime"
    use_realtime_voice = voice_mode == "realtime"

    if not dj_brain or not message:
        return jsonify({"error": "DJ agent not ready"}), 503

    personality = dj_brain.personality
    taste = dj_brain.context.get_music_taste_summary()
    time_info = dj_brain.context.get_time_info()
    profile_context = dj_brain._get_profile_context()

    current_song_info = data.get("current_song", {})
    cur_title = current_song_info.get("title", "")
    cur_artist = current_song_info.get("artist", "")
    cur_str = f"正在播放：{cur_artist} — {cur_title}" if cur_title else "暂无正在播放的歌曲"

    weather_str = ""
    try:
        w = get_weather_data()
        if w.get("status") == "ok":
            weather_str = f"天气：{w.get('description','')} {w.get('temp','')}°C"
    except Exception:
        pass

    system_prompt = f"""你是{personality['name']}，一个能控制播放器的AI音乐DJ。你不是AI，你是一个有血有肉的人。

## 你的性格
{personality['style']}

## 关于听众（你很了解TA）
{profile_context}

## 听众音乐口味
{taste}

## 当前状态
{cur_str}
{weather_str}
时间：{time_info['time_str']}
{time_info['activity_hint']}

## 你可以执行的操作
在回复的末尾加上动作标记来控制播放器。标记不会显示给用户。

可用动作：
- [[skip]] — 切到下一首歌
- [[search:关键词]] — 搜索歌曲
- [[play:歌名—歌手]] — 直接播放指定歌曲
- [[volume:80]] — 调整音量（0-100）

## 说话方式
- 像跟老朋友深夜连麦聊天，不是播新闻
- 用语气词：嗯、嘿、诶、啧、嘶、害、说实话、讲真
- 用口语词：巨好听、上头、绝了、离谱
- 句子长短交错，可以有停顿（用……）
- 绝对不要用括号描述动作
- 先自然回复，再加动作标记
- 不要长篇大论，每条 15-80 字
- 如果没有操作需求，就正常聊天，不加标记
- 标记必须放在最后，一行一个

## 绝对禁止
- 不要用括号写动作描述（叹气）（停顿）（笑）—— TTS 会念出来
- 不要用「下一首」「接下来请收听」这种机械播报
- 不要长篇大论

## 语音情感控制
用 [em:词] 标记需要加重语气的地方，TTS 会自然强调。
限制：一句话最多 1-2 个标记。"""

    def generate():
        # Step 1: DeepSeek generates full response
        full_text = ""
        try:
            for token in dj_brain.llm.generate_stream(system_prompt, message,
                                                       chat_history if chat_history else None):
                if token is None:
                    yield f"data: {json.dumps({'error': 'LLM API failed'}, ensure_ascii=False)}\n\n"
                    return
                full_text += token
                yield f"data: {json.dumps({'type': 'token', 'text': token}, ensure_ascii=False)}\n\n"
            yield f"event: text_done\ndata: {json.dumps({'full_text': full_text}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return

        if not full_text.strip():
            yield f"event: done\ndata: \n\n"
            return

        # Strip action markers for voice synthesis
        clean_for_voice = _re.sub(r'\[\[\w+(?::[^\]]*)?\]\]', '', full_text).strip()
        clean_for_voice = _re.sub(r'\[em:([^\]]+)\]', r'\1', clean_for_voice).strip()

        if not clean_for_voice:
            yield f"event: done\ndata: \n\n"
            return

        # Step 2: Try real-time voice API (optional by request)
        rt_client = RealtimeVoiceClient(dj_brain.config)
        voice_ok = False
        tried_realtime = False

        if use_realtime_voice and rt_client.check_available():
            tried_realtime = True
            # Extract a condensed personality for the voice model
            voice_prompt = (
                f"你是{personality['name']}，一个深夜电台DJ。"
                f"你的性格：{personality['style']}"
                f"请用自然的、有情感的语气朗读以下内容。"
                f"注意停顿、呼吸和语气变化。"
            )

            if rt_client.connect(voice_prompt):
                audio_queue = _queue.Queue()
                voice_done = False
                voice_error = None

                def on_audio(chunk):
                    audio_queue.put(chunk)

                def on_done():
                    nonlocal voice_done
                    voice_done = True
                    audio_queue.put(b"__END__")

                def on_error(err):
                    nonlocal voice_error
                    voice_error = err
                    audio_queue.put(b"__END__")

                rt_client.start_receiving(on_audio, on_done, on_error)
                rt_client.send_text(clean_for_voice)

                yield f"data: {json.dumps({'type': 'voice_start'}, ensure_ascii=False)}\n\n"

                while True:
                    try:
                        chunk = audio_queue.get(timeout=30)
                    except _queue.Empty:
                        break
                    if chunk == b"__END__":
                        break
                    b64 = base64.b64encode(chunk).decode("ascii")
                    yield f"data: {json.dumps({'type': 'audio', 'data': b64}, ensure_ascii=False)}\n\n"

                rt_client.close()
                voice_ok = not voice_error

        # Step 3: Fallback to SSML streaming TTS
        if not voice_ok:
            if tried_realtime:
                yield f"data: {json.dumps({'type': 'tts_fallback'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'tts_mode'}, ensure_ascii=False)}\n\n"

            if not tts_provider or not tts_provider.check_available():
                yield f"data: {json.dumps({'error': 'TTS not configured'}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: \n\n"
                return

            # Use Phase 2 streaming TTS for the fallback
            chunk_queue = _queue.Queue()

            def on_chunk(chunk):
                chunk_queue.put(chunk)

            _threading.Thread(
                target=tts_provider.synthesize_stream,
                args=(clean_for_voice, "chill", on_chunk),
                daemon=True).start()

            while True:
                try:
                    chunk = chunk_queue.get(timeout=30)
                except _queue.Empty:
                    break
                if chunk == b"__END__":
                    break
                b64 = base64.b64encode(chunk).decode("ascii")
                yield f"data: {json.dumps({'type': 'audio', 'data': b64}, ensure_ascii=False)}\n\n"

        yield f"event: done\ndata: \n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/agent/transition/stream", methods=["POST"])
def api_agent_transition_stream():
    """Streaming transition: send AI tokens in real-time as they arrive."""
    data = request.get_json()
    current_song = data.get("current_song", {})
    weather_data = data.get("weather", None)
    history = data.get("history", [])
    user_activity = data.get("user_activity", "")
    chat_context = data.get("chat_context", "")

    if not dj_brain:
        return jsonify({"error": "DJ agent not ready"}), 503

    playlist_data = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    playlist = playlist_data.get("songs", [])

    def generate():
        for event in dj_brain.think_transition_stream(
                current_song, None, weather_data, history, user_activity, playlist,
                chat_context=chat_context):
            if event["type"] == "token":
                yield f"data: {json.dumps({'token': event['text']}, ensure_ascii=False)}\n\n"
            elif event["type"] == "done":
                action = event["action"]
                resp = {
                    "say": action.say,
                    "reason": action.reason,
                    "segue": action.segue,
                    "mood": action.mood,
                    "action": action.action,
                    "method": "agent_stream",
                }
                yield f"event: done\ndata: {json.dumps(resp, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/agent/radio-segment", methods=["POST"])
def api_radio_segment():
    """Generate a radio segment plan (DJ intro + 2-3 songs)."""
    data = request.get_json()
    current_song = data.get("current_song", {})
    weather_data = data.get("weather", None)

    if not dj_brain:
        return jsonify({"error": "DJ agent not ready"}), 503

    playlist_data = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    playlist = playlist_data.get("songs", [])

    if not playlist:
        return jsonify({"error": "No playlist available"}), 400

    segment = dj_brain.think_radio_segment(
        current_song, playlist, weather_data, n_songs=data.get("n_songs", 3))

    if not segment:
        return jsonify({"error": "Could not generate segment"}), 500

    return jsonify(segment)


@app.route("/api/agent/user-activity", methods=["GET", "POST"])
def api_user_activity():
    """Get or set current user activity."""
    if request.method == "POST":
        data = request.get_json()
        activity = data.get("activity", "")
        if dj_brain:
            dj_brain.set_user_activity(activity)
        return jsonify({"ok": True, "activity": activity})
    return jsonify({"activity": dj_brain._user_activity if dj_brain else ""})


# ── TTS Route ─────────────────────────────────────────
@app.route("/api/tts/synthesize", methods=["POST"])
def api_tts_synthesize():
    """Synthesize speech from text using 火山引擎 TTS. Returns audio/mpeg binary."""
    data = request.get_json()
    text = data.get("text", "")
    mood = data.get("mood", "chill")

    if not text:
        return jsonify({"error": "text required"}), 400

    if not tts_provider or not tts_provider.check_available():
        return jsonify({"error": "TTS not configured"}), 503

    audio_bytes = tts_provider.synthesize(text, mood)
    if audio_bytes is None:
        return jsonify({"error": "TTS synthesis failed"}), 500

    return Response(audio_bytes, mimetype="audio/mpeg",
                    headers={"Content-Length": str(len(audio_bytes)),
                             "Cache-Control": "no-cache"})


@app.route("/api/tts/synthesize/stream", methods=["POST"])
def api_tts_synthesize_stream():
    """Streaming TTS: split text into sentence groups, synthesize each via HTTP,
    send audio chunks as base64 SSE events for sequential frontend playback."""
    import queue as _queue
    data = request.get_json()
    text = data.get("text", "")
    mood = data.get("mood", "chill")

    if not text:
        return jsonify({"error": "text required"}), 400

    if not tts_provider or not tts_provider.check_available():
        return jsonify({"error": "TTS not configured"}), 503

    def generate():
        chunk_queue = _queue.Queue()

        def on_chunk(chunk: bytes):
            chunk_queue.put(chunk)

        # Start streaming synthesis in background thread
        import threading
        thread = threading.Thread(
            target=tts_provider.synthesize_stream,
            args=(text, mood, on_chunk),
            daemon=True)
        thread.start()

        while True:
            try:
                chunk = chunk_queue.get(timeout=30)
            except _queue.Empty:
                break
            if chunk == b"__END__":
                yield "event: done\ndata: \n\n"
                break
            b64 = base64.b64encode(chunk).decode("ascii")
            yield f"data: {b64}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── Listening Stats Routes ────────────────────────────
@app.route("/api/stats")
def api_stats():
    """Get listening statistics."""
    stats = load_stats()
    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})

    # Merge song play counts into playlist data
    song_plays = stats.get("song_plays", {})
    songs_with_counts = []
    for song in playlist.get("songs", []):
        key = get_song_key(song)
        play_data = song_plays.get(key, {"count": 0, "last_played": None})
        songs_with_counts.append({
            **song,
            "play_count": play_data.get("count", 0),
            "last_played": play_data.get("last_played"),
        })

    return jsonify({
        "total_seconds": stats.get("total_seconds", 0),
        "sessions": stats.get("sessions", []),
        "daily_history": stats.get("daily_history", {}),
        "songs": songs_with_counts,
    })


@app.route("/api/stats/tick", methods=["POST"])
def api_stats_tick():
    """Record a 30-second listening tick."""
    data = request.get_json()
    seconds = data.get("seconds", 30)
    song_index = data.get("song_index", -1)

    stats = load_stats()
    stats["total_seconds"] = stats.get("total_seconds", 0) + seconds

    # Daily history
    today = datetime.now().strftime("%Y-%m-%d")
    daily = stats.setdefault("daily_history", {})
    daily[today] = daily.get(today, 0) + seconds

    # Session tracking
    sessions = stats.setdefault("sessions", [])
    if sessions and sessions[-1].get("date") == today:
        sessions[-1]["seconds"] = sessions[-1].get("seconds", 0) + seconds
    else:
        sessions.append({"date": today, "seconds": seconds})

    # Song play count
    if song_index >= 0:
        playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
        songs = playlist.get("songs", [])
        if song_index < len(songs):
            key = get_song_key(songs[song_index])
            sp = stats.setdefault("song_plays", {})
            entry = sp.setdefault(key, {"count": 0, "last_played": None})
            entry["count"] = entry.get("count", 0) + 1
            entry["last_played"] = datetime.now().isoformat()

    save_stats(stats)
    return jsonify({"ok": True, "total_seconds": stats["total_seconds"]})


@app.route("/api/stats/song-play", methods=["POST"])
def api_stats_song_play():
    """Record a single song play event."""
    data = request.get_json()
    song_index = data.get("song_index", -1)

    playlist = load_json(PLAYLIST_PATH, {"songs": [], "current_index": -1})
    songs = playlist.get("songs", [])
    if not (0 <= song_index < len(songs)):
        return jsonify({"error": "invalid index"}), 400

    stats = load_stats()
    key = get_song_key(songs[song_index])
    sp = stats.setdefault("song_plays", {})
    entry = sp.setdefault(key, {"count": 0, "last_played": None})
    entry["count"] = entry.get("count", 0) + 1
    entry["last_played"] = datetime.now().isoformat()
    save_stats(stats)

    return jsonify({"ok": True, "count": entry["count"]})


# ── Main ───────────────────────────────────────────────
if __name__ == "__main__":
    config = get_config()
    port = config.get("app", {}).get("port", 8765)

    # Initialize DJ Agent Brain
    dj_brain = DJBrain(config)
    llm_ok = dj_brain.llm.check_available()

    # Initialize TTS Provider (火山引擎豆包语音)
    tts_provider = TTSProvider(config)
    tts_ok = tts_provider.check_available()

    # Initialize Scheduler (Phase 3: proactive DJ)
    scheduler = DJScheduler(dj_brain, config)
    scheduler.start()

    print(f"""
==========================================
         Music DJ Server Started
  DJ: {config.get('dj', {}).get('name', 'clauseekio')}
  -> http://localhost:{port}
  LLM API: {'Connected' if llm_ok else 'Not available'}
  TTS:     {'火山引擎' if tts_ok else 'Not configured'}
  Netease: {'Connected' if check_netease_api() else 'Not connected'}
  Agent:  Ready (memory: {dj_brain.memory.get_transition_count()} transitions)
  Scheduler: {'Running' if scheduler.enabled else 'Disabled'}
==========================================
""")
    app.run(host="127.0.0.1", port=port, debug=False)
