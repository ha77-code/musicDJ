# MusicDJ Agent Handoff

## Project Goal
- Build a personal radio DJ agent for local use.
- The DJ should open proactively, chat naturally, recommend songs with taste-aware randomness, and avoid sounding like a playlist looper.
- Casual chat should stay casual unless the user clearly asks to play, search, skip, recommend, pause, resume, or adjust volume.
- DJ narration must match the song that actually plays next.
- The UI should remain the new black/white/green broadcast interface, not the old player + chat sidebar + recommendation sidebar.

## Code Map
- `frontend/index.html`: single-file React/Babel SPA. Contains the broadcast UI, player controls, chat input, opening flow, audio/TTS queues, visualizer, recommendation strip, and sand-like particle interaction.
- `backend/dj_server.py`: Flask entrypoint. Serves the frontend, proxies Netease audio/search APIs, manages playlist/status/stats APIs, agent chat, transition endpoints, and TTS/SSE streaming.
- `backend/agent/dj_brain.py`: DJ decision core. Handles greetings/opening, transitions, selected-song narration, candidate selection, rich fallback lines, and memory recording.
- `backend/agent/song_picker.py`: candidate pool builder. Uses bucket sampling for familiar, underplayed, and discovery songs instead of simple top-weight sorting.
- `backend/agent/runtime_taste.py`: runtime taste scorer. Combines offline catalog weight, live play stats, recency, novelty, and skip signals into weights and tags.
- `backend/agent/memory.py`: SQLite memory layer. Stores transitions, sessions, song interactions, reactions, skips, likes, and personality state.
- `backend/agent/music_discovery.py`: Netease discovery search. Generates exploratory, multilingual, genre, mood, context, and artist-similarity search lanes.
- `backend/agent/prompts.py`: prompt templates for selection, transitions, greetings, and DJ style.
- `backend/agent/taste_profile.py`: builds human-readable and search-friendly taste profiles from processed listening history and user profile notes.
- `backend/agent/tts_provider.py` and `backend/agent/realtime_voice.py`: TTS and realtime voice providers.

## Data And Runtime Files
- `data/playlist.json`: current playable playlist. Do not clear or rebuild casually.
- `data/listening_stats.json`: runtime listening statistics, play counts, and last-played data.
- `data/state.db`: SQLite long-term DJ memory.
- `data/listening_history/processed/*`: offline listening-history outputs such as `training_songs_top300.json`, `artist_stats.json`, and `training_summary.json`.
- `data/listening_history/raw/*`: raw Netease listening and playlist exports.
- `data/personality.json`: DJ personality and fallback line data.
- `user_profile/taste.md`: manually written taste preferences used by profile/search logic.
- `config.json`: local config and credentials; keep private.

## Current Implemented Behavior
- Frontend has been redesigned into a black/white/green broadcast DJ layout with top music stage and lower DJ script paper.
- Old visible Claudio/Speaking labels and the old right-side chat/recommendation layout should not return.
- Chat voice output is queued sequentially so streamed assistant voice and action-driven follow-up voice do not overlap.
- `pendingSong`, transition guards, transition tokens, and fallback timers are used to avoid playing one song while the DJ is introducing another.
- `runOpeningShow` tries to greet and recommend when the page opens in DJ mode.
- `scene: "opening"` and `scene: "transition"` are passed so backend selection can treat opening and normal transitions differently.
- `RuntimeTasteScorer` and bucket sampling were added so recommendations do not rely only on Top300 or playlist order.
- Frontend and backend both have music-intent guards so casual chat should not execute hidden `[[play]]` or `[[recommend]]` actions.
- Multilingual behavior should preserve Chinese, English, Japanese, Korean, and romanized song titles and artist names.
- `viz.spectrumRef` and `viz.waveformRef` are both connected to the current broadcast UI.

## Recent Changed Areas
- `frontend/index.html`: broadcast shell, music stage, rhythm deck, script paper, compact chat command bar, recommendation strip, opening blocked UI, intent guard, and SSE chat handling.
- `backend/dj_server.py`: chat/voice prompts, action-tag cleaning, music-intent detection, scene parameter forwarding, Netease proxy, stats APIs, and transition routes.
- `backend/agent/dj_brain.py`: scene-aware transition selection, richer natural narration, opening/explore detection, fallback selection, and memory recording.
- `backend/agent/song_picker.py`: bucket-based weighted sampling for familiar anchors, underplayed local songs, and fresh discoveries.
- `backend/agent/runtime_taste.py`: new runtime scoring layer for play density, freshness, novelty, skip penalty, and tags.
- `backend/agent/memory.py`: helper queries for skipped ids and recent feedback across transition and interaction tables.
- `backend/agent/prompts.py`: selection principles now prefer discovery/exploration over familiar-only picks.
- `.gitignore`: runtime DB sidecars and listening stats are intended to be ignored, though already-tracked files may still appear modified.

## Keep In Mind
- Do not delete or reset `data/playlist.json`, `data/state.db`, or listening-history data unless the user explicitly asks.
- Do not revert unrelated dirty worktree changes; several files may already be modified.
- Do not break the sequential chat voice queue or reintroduce overlapping TTS/chat/action voices.
- Do not return to the old UI layout; preserve the broadcast DJ concept.
- Do not make recommendations collapse back to liked songs, Top300 order, or playlist first items.
- Keep casual chat separate from music actions unless the user clearly asks for a music operation.
- When adding selected-song narration, bind the spoken song to the actual `pendingSong` that will play.
- Browser autoplay may block audio; text state should still show and user interaction should resume pending playback.

## Known Follow-Up Focus
- Tighten frontend/backend music intent detection so examples like `找工作好难` and `我想听你说说` stay chat-only, while `听点日语的` is treated as music intent.
- Ensure `openingBlocked + pendingSong` makes all obvious play/resume interactions load the pending song, not the playlist current index.
- Make runtime local-song keys stable and compatible with `listening_stats.json`; avoid Python built-in `hash()` for persistent keys.
- Align `think_transition_stream` with the same picker/scene logic used by non-streaming transitions.

## Useful Checks
```powershell
git status --short
```

```powershell
python -m py_compile backend/agent/runtime_taste.py backend/agent/song_picker.py backend/agent/dj_brain.py backend/agent/memory.py backend/dj_server.py backend/agent/prompts.py backend/agent/music_discovery.py backend/agent/taste_profile.py
```

```powershell
git diff --check
```
