"""
听歌数据一键采集脚本
用法: python backend/collect_listening_data.py [--all] [--year 2025]
  python backend/collect_listening_data.py            # 基础采集（历年+排行+歌单+喜欢）
  python backend/collect_listening_data.py --all       # 全量采集（含周/月报告）
  python backend/collect_listening_data.py --year 2025 # 仅采集指定年份
"""

import json
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import requests
import os

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))
from agent import paths

BACKEND = os.environ.get("MUSICDJ_BACKEND", "http://127.0.0.1:8765")


def raw_dir():
    return paths.raw_history_dir()


def processed_dir():
    return paths.processed_history_dir()


def ensure_dirs():
    raw_dir().mkdir(parents=True, exist_ok=True)
    processed_dir().mkdir(parents=True, exist_ok=True)


def api(endpoint, body=None, timeout=15):
    """Call the DJ backend API."""
    url = f"{BACKEND}{endpoint}"
    try:
        resp = requests.post(url, json=body or {}, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        print(f"  [ERR] {endpoint} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  [ERR] {endpoint} -> {e}")
        return None


def save_json(name, data):
    path = raw_dir() / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size = len(json.dumps(data, ensure_ascii=False))
    print(f"  -> saved {name} ({size:,} bytes)")


def check_backend():
    """Check if the DJ backend is running."""
    try:
        resp = requests.get(f"{BACKEND}/api/status", timeout=10)
        if resp.status_code == 200:
            info = resp.json()
            print(f"Backend OK — DJ: {info.get('dj_name')}, "
                  f"Netease: {'Connected' if info.get('netease_available') else 'NOT CONNECTED'}")
            return info.get("netease_available", False)
    except Exception as e:
        print(f"  [DEBUG] Connection error: {e}")
    print("ERROR: DJ backend not running on http://127.0.0.1:8765")
    return False


# ── Collectors ───────────────────────────────────────

def collect_year_reports(start_year=2020, end_year=None):
    if end_year is None:
        end_year = datetime.now().year
    print(f"\n{'='*50}")
    print(f"Collecting year reports: {start_year}–{end_year}")
    results = {}
    for year in range(end_year, start_year - 1, -1):
        print(f"  Year {year}...", end=" ")
        data = api("/api/netease/listen/year/report", {"year": year})
        if data and data.get("code") == 200:
            save_json(f"year_report_{year}.json", data)
            results[year] = data
        else:
            print("no data or error")
        time.sleep(0.3)
    return results


def collect_total():
    print(f"\n{'='*50}")
    print("Collecting total listening time...", end=" ")
    data = api("/api/netease/listen/total")
    if data and data.get("code") == 200:
        save_json("total.json", data)
        return data
    print("failed")
    return None


def collect_reports(report_type="week"):
    print(f"\n{'='*50}")
    print(f"Collecting {report_type} reports (last 4)...")
    results = []
    today = datetime.now()
    for i in range(4):
        if report_type == "week":
            end_date = today - timedelta(weeks=i)
        else:
            end_date = today - timedelta(days=30 * i)
        end_str = end_date.strftime("%Y-%m-%d")
        print(f"  {report_type} ending {end_str}...", end=" ")
        data = api("/api/netease/listen/report", {"type": report_type, "endTime": end_str})
        if data and data.get("code") == 200:
            save_json(f"report_{report_type}_{end_str}.json", data)
            results.append(data)
        else:
            print("no data")
        time.sleep(0.3)
    return results


def collect_recent():
    print(f"\n{'='*50}")
    print("Collecting recent listening list...", end=" ")
    data = api("/api/netease/listen/recent")
    if data and data.get("code") == 200:
        save_json("recent_listen.json", data)
        return data
    print("failed")
    return None


def collect_user_record():
    print(f"\n{'='*50}")
    print("Collecting user records (all-time + weekly)...")
    results = {}
    for rec_type, label in [(0, "all_time"), (1, "weekly")]:
        print(f"  {label}...", end=" ")
        data = api("/api/netease/user/record", {"type": rec_type})
        if data and data.get("code") == 200:
            save_json(f"user_record_{label}.json", data)
            results[label] = data
        else:
            print("no data")
        time.sleep(0.3)
    return results


def collect_liked_songs():
    """Collect user's liked songs list (我喜欢)."""
    print(f"\n{'='*50}")
    print("Collecting liked songs...", end=" ")
    data = api("/api/netease/likelist")
    if data and data.get("code") == 200:
        ids = data.get("ids", [])
        print(f"{len(ids)} songs")
        save_json("liked_songs.json", data)
        return ids
    print("failed")
    return []


def collect_user_playlists():
    """Collect user's playlists metadata."""
    print(f"\n{'='*50}")
    print("Collecting user playlists...")
    data = api("/api/netease/user/playlist")
    if not data or data.get("code") != 200:
        print("  failed")
        return []
    playlists = data.get("playlist", [])
    print(f"  Found {len(playlists)} playlists")
    save_json("playlists_meta.json", data)
    return playlists


def collect_playlist_tracks(playlists):
    """Fetch all tracks from each playlist."""
    print(f"\n{'='*50}")
    print(f"Fetching tracks from {len(playlists)} playlists...")
    all_tracks = []  # list of {playlist_id, playlist_name, songs: []}
    for pl in playlists:
        pid = pl.get("id")
        pname = pl.get("name", "?")
        track_count = pl.get("trackCount", 0)
        print(f"  [{pid}] {pname} ({track_count} tracks)...", end=" ")
        data = api("/api/netease/playlist/tracks", {"id": str(pid), "limit": 500}, timeout=30)
        if data and data.get("code") == 200:
            songs = data.get("songs", [])
            save_json(f"playlist_tracks_{pid}.json", data)
            all_tracks.append({
                "playlist_id": pid,
                "playlist_name": pname,
                "songs": songs,
            })
            print(f"{len(songs)} fetched")
        else:
            print("failed")
        time.sleep(0.5)
    return all_tracks


def collect_song_details(song_ids, batch_size=50):
    """Fetch song details (genre, album info, etc.) for a list of song IDs."""
    print(f"\n{'='*50}")
    print(f"Fetching details for {len(song_ids)} songs...")
    detail_map = {}
    ids_list = list(song_ids)
    for i in range(0, len(ids_list), batch_size):
        batch = ids_list[i:i + batch_size]
        ids_str = ",".join(str(x) for x in batch)
        print(f"  batch {i // batch_size + 1} ({len(batch)} songs)...", end=" ")
        data = api("/api/netease/song/detail", {"ids": ids_str})
        if data and data.get("code") == 200:
            songs = data.get("songs", [])
            for s in songs:
                sid = str(s.get("id", ""))
                detail_map[sid] = {
                    "name": s.get("name", ""),
                    "artists": [a.get("name", "") for a in s.get("ar", [])],
                    "album": s.get("al", {}).get("name", ""),
                    "album_pic": s.get("al", {}).get("picUrl", ""),
                    "duration_ms": s.get("dt", 0),
                    "track_number": s.get("no", 0),
                }
            print(f"got {len(songs)}")
        else:
            print("failed")
        time.sleep(0.3)
    return detail_map


# ── Extractors ───────────────────────────────────────

def extract_songs_from_record(record_data):
    """Extract song list with play counts from user_record API response."""
    songs = []
    if not record_data:
        return songs
    for key in ("allData", "weekData"):
        song_list = record_data.get(key, [])
        for item in song_list:
            song = item.get("song", {})
            songs.append({
                "id": str(song.get("id", "")),
                "name": song.get("name", ""),
                "artist": ",".join(a.get("name", "") for a in song.get("ar", [])),
                "album": song.get("al", {}).get("name", ""),
                "play_count": item.get("playCount", 0),
                "score": item.get("score", 0),
                "source": "user_record",
            })
    return songs


def extract_songs_from_playlist(playlist_tracks):
    """Extract songs from playlist tracks data."""
    songs = []
    for pl in playlist_tracks:
        pname = pl.get("playlist_name", "")
        for song in pl.get("songs", []):
            songs.append({
                "id": str(song.get("id", "")),
                "name": song.get("name", ""),
                "artist": ",".join(a.get("name", "") for a in song.get("ar", [])),
                "album": song.get("al", {}).get("name", ""),
                "play_count": 0,
                "score": 0,
                "source": f"playlist:{pname}",
            })
    return songs


def extract_songs_from_liked(liked_ids, detail_map):
    """Build song entries from liked song IDs + details."""
    songs = []
    for sid in liked_ids:
        sid_str = str(sid)
        info = detail_map.get(sid_str, {})
        songs.append({
            "id": sid_str,
            "name": info.get("name", ""),
            "artist": ",".join(info.get("artists", [])),
            "album": info.get("album", ""),
            "play_count": 0,
            "score": 0,
            "source": "liked",
        })
    return songs


# ── Merge & Process ──────────────────────────────────

def merge_and_process(record_songs, playlist_songs, liked_songs, detail_map):
    """Merge all sources, deduplicate by song ID, assign priority scores."""
    print(f"\n{'='*50}")
    print("Merging & ranking all songs...")

    merged = OrderedDict()  # id -> song dict

    # Priority: user_record (has real play counts) > liked > playlist
    for s in record_songs:
        sid = s["id"]
        if sid not in merged:
            merged[sid] = s
        else:
            merged[sid]["play_count"] += s.get("play_count", 0)
            merged[sid]["score"] = max(merged[sid].get("score", 0), s.get("score", 0))

    for s in liked_songs:
        sid = s["id"]
        if sid not in merged:
            merged[sid] = s

    for s in playlist_songs:
        sid = s["id"]
        if sid not in merged:
            merged[sid] = s

    # Enrich with detail_map (genre, pic, etc.)
    for sid, song in merged.items():
        detail = detail_map.get(sid, {})
        if detail:
            if not song.get("album"):
                song["album"] = detail.get("album", "")
            if not song.get("name"):
                song["name"] = detail.get("name", "")
            song["album_pic"] = detail.get("album_pic", "")
            song["duration_ms"] = detail.get("duration_ms", 0)

    # Assign tier & weight for training
    song_list = list(merged.values())
    song_list.sort(key=lambda x: (x.get("play_count", 0), x.get("score", 0)), reverse=True)

    for i, s in enumerate(song_list):
        if s.get("play_count", 0) > 0:
            s["tier"] = "core"              # from user_record, has play count
            s["weight"] = max(0.1, s["play_count"] / max(1, song_list[0].get("play_count", 1)))
        elif s["source"] == "liked":
            s["tier"] = "liked"             # explicitly liked by user
            s["weight"] = 0.05
        else:
            s["tier"] = "playlist"          # from user's playlist
            s["weight"] = 0.02

    print(f"  Total unique songs: {len(song_list)}")
    print(f"  Core (w/ play counts): {sum(1 for s in song_list if s['tier']=='core')}")
    print(f"  Liked: {sum(1 for s in song_list if s['tier']=='liked')}")
    print(f"  Playlist: {sum(1 for s in song_list if s['tier']=='playlist')}")

    return song_list


# ── Save processed ───────────────────────────────────

def save_processed(name, data):
    path = processed_dir() / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  -> {name}")


def save_training_dataset(song_list, detail_map):
    """Save the final training-ready datasets."""
    print(f"\n{'='*50}")
    print("Saving training datasets...")

    # 1. Full song catalog (sorted by weight)
    save_processed("song_catalog.json", {
        "generated_at": datetime.now().isoformat(),
        "total_songs": len(song_list),
        "songs": song_list,
    })

    # 2. Core training set (top 300 with metadata)
    top300 = song_list[:300]
    save_processed("training_songs_top300.json", {
        "generated_at": datetime.now().isoformat(),
        "total": len(top300),
        "songs": top300,
    })

    # 3. Artist aggregation
    artists = {}
    for s in song_list:
        artist = s.get("artist", "未知")
        if artist not in artists:
            artists[artist] = {"plays": 0, "songs": 0, "weight": 0.0}
        artists[artist]["plays"] += s.get("play_count", 0)
        artists[artist]["songs"] += 1
        artists[artist]["weight"] += s.get("weight", 0)
    artist_list = sorted(artists.items(), key=lambda x: x[1]["plays"], reverse=True)
    save_processed("artist_stats.json", {
        "generated_at": datetime.now().isoformat(),
        "artists": [{"name": k, **v} for k, v in artist_list],
    })

    # 4. Summary
    tiers = {"core": 0, "liked": 0, "playlist": 0}
    for s in song_list:
        tiers[s.get("tier", "playlist")] += 1

    save_processed("training_summary.json", {
        "generated_at": datetime.now().isoformat(),
        "total_songs": len(song_list),
        "top300_songs": len(top300),
        "total_artists": len(artist_list),
        "tiers": tiers,
        "top_10_songs": song_list[:10],
        "top_10_artists": [{"name": k, **v} for k, v in artist_list[:10]],
    })

    # 5. Artist profile (rich format for DJ personality)
    artist_profile = []
    for name, stats in artist_list[:50]:
        artist_songs = [s for s in song_list if s.get("artist") == name]
        artist_profile.append({
            "name": name,
            "total_plays": stats["plays"],
            "song_count": stats["songs"],
            "top_songs": [{"name": s["name"], "plays": s["play_count"]}
                          for s in sorted(artist_songs, key=lambda x: x["play_count"], reverse=True)[:5]],
        })
    save_processed("artist_profile.json", {
        "generated_at": datetime.now().isoformat(),
        "artists": artist_profile,
    })

    print(f"\n  Total songs: {len(song_list)}")
    print(f"  Training set (top 300): {len(top300)}")
    print(f"  Artists: {len(artist_list)}")
    print(f"  Tiers: core={tiers['core']}, liked={tiers['liked']}, playlist={tiers['playlist']}")


# ── Main ─────────────────────────────────────────────

def main():
    ensure_dirs()

    do_all = "--all" in sys.argv
    year_filter = None
    for i, arg in enumerate(sys.argv):
        if arg == "--year" and i + 1 < len(sys.argv):
            year_filter = int(sys.argv[i + 1])

    if not check_backend():
        sys.exit(1)

    start = time.time()

    # ── Phase 1: Collect raw data ──

    # Year reports
    if year_filter:
        collect_year_reports(start_year=year_filter, end_year=year_filter)
    else:
        collect_year_reports(start_year=2020)

    collect_total()
    collect_recent()

    # User record (100 songs with play counts) — PRIMARY source
    user_records = collect_user_record()
    record_songs_all = extract_songs_from_record(user_records.get("all_time", {}))
    record_songs_week = extract_songs_from_record(user_records.get("weekly", {}))
    # Merge all-time + weekly, deduplicate by id
    record_songs_map = {}
    for s in record_songs_all + record_songs_week:
        sid = s["id"]
        if sid not in record_songs_map:
            record_songs_map[sid] = s
        else:
            record_songs_map[sid]["play_count"] += s.get("play_count", 0)
            record_songs_map[sid]["score"] = max(record_songs_map[sid].get("score", 0), s.get("score", 0))
    record_songs = list(record_songs_map.values())
    print(f"  Extracted {len(record_songs)} songs from user_record (all-time + weekly deduped)")

    # Liked songs — SECONDARY source
    liked_ids = collect_liked_songs()

    # Playlists — TERTIARY source
    playlists = collect_user_playlists()
    playlist_tracks = collect_playlist_tracks(playlists)
    playlist_songs = extract_songs_from_playlist(playlist_tracks)
    print(f"  Extracted {len(playlist_songs)} songs from playlists")

    # Weekly & monthly reports (only with --all)
    if do_all:
        collect_reports("week")
        collect_reports("month")

    # ── Phase 2: Fetch song details ──
    all_ids = set()
    for s in record_songs:
        all_ids.add(s["id"])
    for sid in liked_ids:
        all_ids.add(str(sid))
    for s in playlist_songs:
        all_ids.add(s["id"])
    detail_map = collect_song_details(all_ids)

    # Build liked songs list from detail_map
    liked_songs = extract_songs_from_liked(liked_ids, detail_map)

    # ── Phase 3: Merge & save ──
    song_list = merge_and_process(record_songs, playlist_songs, liked_songs, detail_map)
    save_training_dataset(song_list, detail_map)

    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"Done in {elapsed:.1f}s")
    print(f"Raw:      {raw_dir()}")
    print(f"Training: {processed_dir()}")


if __name__ == "__main__":
    main()
