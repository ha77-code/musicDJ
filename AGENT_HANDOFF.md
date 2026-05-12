# MusicDJ Agent Handoff (2026-05-11)

## Current User Intent
- Keep DJ chat voice and music playing together.
- One request should produce two DJ outputs in sequence:
  1) a longer recommendation/response
  2) a short follow-up like `来了——xxx`
- No overlapping voices, no hard double accents, no triple-voice stacking.
- Player UI should be black-green, transparent enough to reveal bottom particle interaction.
- Player top area should be rhythm visualization (no rotating vinyl).
- Center area should focus on song title + lyrics.

## Project Snapshot

### Backend status
1. `backend/dj_server.py`
- `/api/audio` now supports Range passthrough in proxy mode.
- Proxy branch forwards `Accept-Ranges`, `Content-Length`, `Content-Range`, and keeps upstream `200/206`.
- `POST /api/agent/chat/voice` supports `voice_mode` (`realtime` | `tts`).
- Streaming events include:
  - `type: token`
  - `type: audio`
  - `type: tts_fallback` (realtime failed)
  - `type: tts_mode` (user picked tts)
  - `event: done`

2. `backend/agent/tts_provider.py`
- Fixed `mood_params` init risk when SSML is disabled.
- Added `force_plain` option in `synthesize(...)`.
- Removed unsafe shared mutation of `self.ssml_enabled` in fallback flow.

### Frontend status
Main file is `frontend/index.html`.

Core playback/agent improvements from earlier rounds are still present:
- Transition race control:
  - `transitionTokenRef`
  - `transitionTimerRef`
  - `cancelTransitionFallback()`
  - `scheduleTransitionFallback(...)`
- Lyrics timestamp parser handles both:
  - `[mm:ss.xx]`
  - `[mm:ss.xxx]`
- Weather payload structured as:
  - `iconEmoji`, `iconCode`, `description`, `temp`, `time`
- Voice mode persisted:
  - reducer `voiceMode`
  - localStorage key `dj_voice_mode`

## Latest Round (Implemented)

### 1) Sequential chat voice playback (critical fix)
Implemented chat-audio session queue to prevent overlap between:
- streamed assistant voice from `/api/agent/chat/voice`
- action-driven second voice in `executeActions`

Added chat voice controller refs and helpers:
- `chatVoiceRef` (session id, queue, player, done flag, waiters)
- `stopChatVoice()`
- `enqueueChatVoiceChunk(...)`
- `playNextChatVoice(...)`
- `markChatVoiceStreamDone(...)`
- `waitForChatVoiceDrain(...)`

Flow now:
1. `sendChat` starts a new session, cancels previous chat voice and TTS.
2. Stream `audio` chunks are queued and played in order.
3. `event: done` marks stream completion.
4. Only after queue drains (`waitForChatVoiceDrain`) do actions execute.
5. Then second line voice (for play action) is spoken.

Result:
- Two outputs can happen in one interaction, but strictly in sequence.
- Greatly reduces heavy overlap/double accents.

### 2) Reduced extra voice sources
- Transition trigger is now guarded when busy:
  - block if `state.appState !== 'idle'` or `state.isDjTalking`
- Interjections are also guarded:
  - only when `state.appState === 'idle'`
  - and `!state.isDjTalking`
- Added chat-voice stop hooks on:
  - mode toggle
  - skip reaction
  - new chat start

### 3) Kept second output while making it ordered
In `executeActions` `play` branch:
- after song selection/direct play, add assistant message:
  - `来了——{artist}的《{title}》`
- speak follow-up:
  - `来了，{artist}的《{title}》。`
- this now happens after first streamed speech finishes.

### 4) UI redesign toward black-green transparent rhythm style
- Removed reliance on rotating album visual.
- Emphasized rhythm/spectrum/wave look:
  - top spectrum and waveform colors shifted to emerald/green.
- Increased glass transparency to reveal particle base.
- Unified black-green styling for:
  - top nav
  - chat panel
  - recommendation cards
  - progress bar
  - playback controls
  - waveform/lyrics panel
- Mobile adaptation improved:
  - DJ layout now `flex-col lg:flex-row`
  - right panel becomes responsive height on small screens

## Key Code Anchors
- Chat voice session state: `frontend/index.html` around `chatVoiceRef` (near App refs)
- Chat pipeline: `sendChat` (waits for voice drain before actions)
- Action follow-up speech: `executeActions` -> `case 'play'`
- Interjection guard: `useInterjections`
- Transition guard: transition trigger in `useAudioPlayer`, plus `doTransition`
- UI components:
  - `BackgroundEffects`
  - `TopNav`
  - `PlayerCard`
  - `ChatSection`
  - `RecommendationCards`
  - `ProgressBar`
  - `PlaybackControls`

## Known Risks / Gaps
1. `frontend/index.html` still has legacy size and mixed history edits.
- Functionally improved, but file is large and hard to maintain.
- Recommended next step: split into modules/components (React file split).

2. Full end-to-end audio behavior still needs manual validation on real playback.
- Especially rapid consecutive chat sends and mode switching.

3. Transition "speak once then music only" behavior is tied to `transitionVoiceUsedRef`.
- Confirm product intent if user later wants frequent transitions to speak again.

## Validation Checklist (next run)
1. Sequential speech:
- Send a command that triggers `[[play:...]]`.
- Confirm first long response voice ends before second `来了——...` starts.
- No overlapping dual/triple voices.

2. Concurrency stress:
- Send another chat while first chat voice is still speaking.
- Confirm previous chat voice is canceled cleanly and no stacking remains.

3. Transition conflict:
- Near song end, send chat.
- Ensure no interjection/transition voice intrudes while chatting.

4. UI acceptance:
- Confirm black-green consistency with right chat panel.
- Confirm top rhythm visualization is visible while playing.
- Confirm center title + lyrics readability.
- Confirm transparency allows particle layer to show through.

5. Responsive:
- Verify desktop and narrow widths both keep major sections visible.

## Useful Commands
```powershell
# current changed files
git status --short

# inspect frontend changes only
git diff -- frontend/index.html

# inspect backend changes if needed
git diff -- backend/dj_server.py
git diff -- backend/agent/tts_provider.py
```

## Next Session Start
1. Read this handoff.
2. Run the validation checklist above first.
3. If sequential voice still has edge overlap in some browsers, move chat voice playback to WebAudio single context scheduler.
4. If user approves, refactor `frontend/index.html` into component files to reduce regression risk.

---

## Update (2026-05-11 Night)

### Transition narration upgraded (natural long-form)
- File changed: `backend/agent/dj_brain.py`
- Added a second-pass transition enhancer:
  - `_transition_depth(...)`:
    - `short` / `standard` / `deep` depth selection
    - currently defaults to richer narration for most cases
  - `_build_transition_user_prompt(...)`:
    - builds explicit "previous song -> next song" bridge prompt
    - forces mention of next song title/artist
    - allows expansion topics: creation story, artist intent, lyric meaning, chat-context continuation
  - `_ensure_rich_transition(...)`:
    - if LLM output is too short or lacks next-song anchor, auto-regenerates with rich prompt
    - if regen still fails, uses deterministic long fallback (~100+ chars) with song-aware narrative

### Prompt strategy updated
- Transition regeneration is now moving away from long hand-written prompt text.
- Current runtime path uses:
  - minimal system instruction
  - structured JSON payload with constraints/context
  - code-side rules for anchor + length + fallback
- This keeps DJ style generation less dependent on custom-written wording and more dependent on structured signals.

### Selection path now auto-applies rich transition
- In `_think_selection(...)`, after selected song is resolved (including album/lyric enrichment), action text is passed through `_ensure_rich_transition(...)`.
- Fallback candidate selection path also applies `_ensure_rich_transition(...)`.

### Validation done
- `python -m py_compile backend/agent/dj_brain.py` passed.
- `python -m py_compile backend/dj_server.py` passed.
- Local function-level smoke test confirmed generated transition length can exceed 100 chars and includes narrative bridge structure.

### Notes
- Existing frontend rule `transitionVoiceUsedRef` still enforces "speak once, then music-only" behavior (unchanged this round).
- If product decision changes later (want DJ to speak every transition), this guard must be adjusted in `frontend/index.html` (`doTransition` block).
