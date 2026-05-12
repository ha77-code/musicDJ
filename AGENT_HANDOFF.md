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

---

## Update (2026-05-12)

### User intent this round
- Replace the old DJ UI completely, based on the supplied Claudio-style reference:
  - Top area = music playback + rhythm visualization.
  - Bottom area = DJ speech, segue copy, and interactive script/chat area.
- Visual direction:
  - Black/white base with green accents.
  - Desktop should be adaptive/wide, mobile should collapse toward the vertical card reference.
  - Do not keep the old right-side chat panel / old recommendation sidebar as the main UI.
- Later refinements requested:
  - Playback controls must not be covered by the lower chat/script panel.
  - Startup should not always begin with `By Your Side`.
  - Recommended song and actually played song must match.
  - Missing segue between songs must be reduced.
  - Chat/script area should have a sand / quicksand interaction effect.
  - Font sizes were too large and needed to be reduced.
  - User chat messages must appear in the DJ script/chat area.
  - DJ can speak Chinese, English, or mixed language.
  - Japanese/Korean/English songs should not be skipped; language/song library should be richer.

### Frontend UI redesign
- Main file changed: `frontend/index.html`.
- New DJ view is now routed through `BroadcastShell` instead of rendering the old main combination:
  - old main DJ layout: `PlayerCard + ChatSection + RecommendationCards`
  - new main DJ layout: `BroadcastShell`
- New UI component group added:
  - `BroadcastShell`
  - `MusicStage`
  - `RhythmDeck`
  - `StageProgress`
  - `StageControls`
  - `ScriptPaper`
  - `CompactCommandBar`
  - `RecommendationStrip`
- Old components are still present in the file for now, but they are no longer the primary DJ view.
- The top music stage now includes:
  - station lockup / status (`Speaking...`, `Playing...`, `Standing by...`)
  - current song title + artist
  - compact current lyric/mood pill
  - large FFT spectrum canvas via `viz.spectrumRef`
  - progress strip with small waveform canvas via `viz.waveformRef`
  - play/pause, prev, next, volume controls
- The lower script paper now includes:
  - current DJ speech / segue as the primary text
  - `reasonText` when present
  - recent DJ/user script history
  - reaction buttons when `state.showReactions`
  - compact chat input and activity chips
  - lightweight horizontal recommendation cards
- Font sizes were reduced after user feedback:
  - `track-title`
  - `track-artist`
  - `lyric-pill`
  - `script-title`
  - `script-text`
  - `script-line`
  - command input
- Playback controls were moved upward inside the black music stage:
  - `.music-stage` bottom padding increased
  - `.stage-control-deck` bottom position moved up
  - mobile breakpoint adjusted separately

### Interactive sand / particle effect
- `ScriptPaper` now has:
  - animated sand streams (`sand-stream s1/s2/s3`)
  - drifting sand background (`sandDrift`, `sandFall`)
  - real particle dots (`sand-particle`)
  - pointer-following magnifier effect
- Mouse movement updates CSS vars:
  - `--sand-x`
  - `--sand-y`
  - per-particle `--p-scale`
  - per-particle `--p-opacity`
  - per-particle `--p-blur`
- Effect goal: particles near the cursor enlarge/brighten like a local magnifying glass over sand.

### Chat/script feed changes
- Added frontend state:
  - `djScriptFeed`
- Speech feed behavior:
  - `state.speechText` is captured into `djScriptFeed`
  - latest assistant chat replies are captured
  - latest user messages are now captured too
- `ScriptPaper` now chooses primary display from:
  1) active `state.speechText`
  2) latest non-user DJ/script feed item
  3) fallback text based on current song
- History lines now distinguish:
  - `You` for user messages
  - `DJ Reply` for assistant chat replies
  - `Cue` for speech/transition lines

### Playback / transition fixes
- In `useAudioPlayer.play()`:
  - when there is no loaded audio, it now loads saved `current_index` if valid instead of always loading index `0`.
- Startup behavior:
  - added `chooseStartupIndex(...)`.
  - if saved index is valid and non-zero, resume it.
  - if saved index is `0` or invalid and there are multiple songs, choose a random non-zero index.
  - This avoids repeatedly opening with `By Your Side` when the persisted state effectively points at the first song.
- In `onEnded`:
  - DJ mode now sets `SET_TRANSITION_TRIGGERED` instead of directly calling `nextTrack()`.
  - This reduces cases where consecutive songs play without DJ segue.
  - Also fixed an old typo: `TRANSITION_TRIGGERED` -> `SET_TRANSITION_TRIGGERED`.
- Added `loadMaterializedSong(song, idx)`:
  - Used when DJ selects a Netease discovery song that is not yet in the local playlist.
  - Sets `currentSong`, `current_index`, audio `src`, and stats/current playlist APIs in one path.
  - Fixes mismatch where DJ recommends one song but the browser plays a different song because old `loadSong(idx)` closure cannot see the newly appended playlist item yet.
- `playDirectSong(song)` now:
  - updates `currentSong` for UI immediately
  - supports `netease_discovery`
  - preserves the current playlist index so direct play can return to the prior playlist context.

### Multilingual / song-language support
- Backend files changed:
  - `backend/dj_server.py`
  - `backend/agent/dj_brain.py`
  - `backend/agent/prompts.py`
  - `backend/agent/music_discovery.py`
  - `backend/agent/taste_profile.py`
- Added `LANGUAGE_POLICY` in `backend/agent/prompts.py`.
- Policy now says:
  - DJ may speak Chinese, English, or natural Chinese-English mix.
  - Do not skip/reject songs because they are Japanese, Korean, English, or multilingual.
  - Preserve original song titles and artist names exactly, including Japanese kana/kanji and Korean hangul.
  - J-pop, K-pop, anime OST, city pop, English pop, R&B, hip-hop, electronic, rock, indie are valid.
- Applied language policy to:
  - `build_system_prompt`
  - `build_greeting_prompt`
  - `build_interjection_prompt`
  - `build_selection_prompt`
- `backend/dj_server.py` chat prompts now append a multilingual policy for:
  - `/api/agent/chat`
  - `/api/agent/chat/voice`
  - realtime voice prompt
- `backend/agent/dj_brain.py` transition retry prompts changed from hard Chinese-only to multilingual:
  - removed `Chinese characters` wording
  - minimal transition system prompt is now multilingual
  - structured payload `language` field now allows zh-CN / English / natural mixed language and preserving Japanese/Korean titles.
- `backend/agent/music_discovery.py`:
  - discovery query cap increased from 3 to 5.
  - added multilingual discovery queries such as:
    - `J-pop city pop`
    - `K-pop R&B`
    - `Japanese indie pop`
    - `Korean indie`
    - `English pop R&B`
    - `anime OST`
- `backend/agent/taste_profile.py`:
  - search profile now includes `language_queries`.
  - genre extraction adds `K-POP`.

### Validation done
- Frontend JSX/Babel parse passed:
  - `babel_parse_ok lines=2354`
- Backend compile passed:
  - `python -m py_compile backend/agent/dj_brain.py backend/agent/prompts.py backend/agent/music_discovery.py backend/agent/taste_profile.py backend/dj_server.py`
- Static service/resource smoke was previously run successfully during UI work:
  - `/` returns 200
  - `react.min.js` returns 200
  - `babel.min.js` returns 200

### Current known risks / follow-up
1. `frontend/index.html` is now very large.
- The new UI is working as a single-file SPA, but maintainability is getting worse.
- Recommended next step remains splitting components/hooks into separate files if the user approves.

2. Full manual browser/audio validation is still needed.
- Especially:
  - real song ending -> DJ transition -> selected song playback
  - discovery song selected by DJ -> actual audio source matches the announced song
  - direct play from chat -> returns cleanly to playlist context
  - rapid chat sends while audio is speaking

3. Runtime state files may change during smoke tests.
- Running the server can modify files such as:
  - `data/listening_stats.json`
  - `data/state.db-shm`
  - `data/state.db-wal`
- Treat those as runtime noise unless the user specifically asks to keep stats changes.

4. `.gitignore` already had unrelated user/worktree changes before this round.
- Do not revert it unless explicitly asked.

### Updated validation checklist
1. UI layout:
- Confirm playback controls are visible and clickable, not hidden under the lower script panel.
- Confirm desktop is a wide black/white/green broadcast card.
- Confirm mobile collapses into a vertical reference-card style.

2. Script/chat area:
- Send a user chat and confirm it appears in the script area as `You`.
- Confirm DJ reply appears as `DJ Reply`.
- Confirm active DJ speech still takes priority as the main script text.
- Move mouse across the script paper and confirm nearby sand particles enlarge/brighten.

3. Playback and segue:
- Let a song end in DJ mode and confirm it triggers transition speech rather than silent/direct next track.
- Confirm selected/recommended song and actual played song match, especially when selected song is a Netease discovery song not already in the playlist.
- Confirm opening no longer always starts at playlist index 0 / `By Your Side` when the saved index is invalid or zero.

4. Multilingual:
- Ask for an English song, a Japanese song, and a Korean song.
- Confirm DJ does not skip them for language reasons.
- Confirm action tags preserve original title/artist text.
- Confirm DJ can naturally answer in Chinese, English, or mixed language.

---

## Update (2026-05-12 Stabilization Pass)

### User intent clarified
- User said the goal is a personal-use radio DJ agent, and the current code still has many bugs.
- Priority should now be reliability over more visual work:
  - correct song selection and actual playback match
  - stable song-end transitions
  - no dead air when chat/voice overlaps with song ending
  - no voice/action ordering regressions
  - visible chat history in the script area

### Frontend fixes in `frontend/index.html`
- Added `pendingTransition` state:
  - `pendingTransition` queues a DJ transition that could not run because the app was busy.
  - This prevents losing a transition when the song reaches the end during chat or another voice state.
- Fixed song-end busy handling:
  - `onEnded` now treats any non-idle app state as busy, not only `speaking`.
  - If a selected `pendingSong` already exists, song ending sets `pendingNext` so the selected song can start after speech.
  - If no selected song exists, song ending queues `pendingTransition` so the DJ can still speak once idle.
- Fixed selected-song priority:
  - `loadPendingSong()` now plays `pendingSong` before falling back to `pendingNext`.
  - This addresses the bug where the DJ announces one selected song but sequential playback starts a different song.
- Refactored `loadPendingSong()` to read from `stateRef.current`:
  - makes delayed callbacks and recovery paths use latest state
  - reduces stale-closure risk after chat or TTS interruptions
- Added idle recovery effect:
  - when app returns to idle, pending selected songs are loaded
  - pending sequential next in DJ mode is converted into a queued transition instead of silently skipping DJ speech
- Hardened transition fallback:
  - if fallback timeout fires and `pendingSong`/`pendingNext` exists, it now calls `loadPendingSong()` instead of doing nothing.
- Fixed React runtime TDZ risk:
  - `sendChat` no longer references `executeActions` before initialization in its dependency array.
  - Added `executeActionsRef`.
- Hardened chat `play` action matching:
  - added `normalizeTrackText`, `splitTrackArg`, and `trackMatchScore`
  - local playlist matching now prioritizes title match and avoids loose artist-only false positives.
  - Netease fallback still searches if no local match is good enough.
- Chat request history now includes the just-sent user message in the payload sent to `/api/agent/chat/voice`.
- Manual playback actions now clear queued transition/pending song state:
  - top controls
  - skip reaction
  - mode toggle
  - direct play
- Browser fallback speech is no longer hard-coded to `zh-CN`:
  - added `detectSpeechLang`
  - fallback speech chooses `zh-CN`, `en-US`, `ja-JP`, or `ko-KR` based on text.

### Validation done this pass
- Frontend JSX/Babel parse passed:
  - `babel_parse_ok lines=2512`
- Backend compile passed:
  - `python -m py_compile backend/agent/dj_brain.py backend/agent/prompts.py backend/agent/music_discovery.py backend/agent/taste_profile.py backend/dj_server.py`
- Static service/resource smoke passed:
  - `/` returned 200
  - `react.min.js` returned 200
  - `babel.min.js` returned 200
- `git diff --check -- frontend/index.html` produced only line-ending warnings, no whitespace errors.

### Workspace notes
- Running server smoke touched runtime files.
- `data/state.db-shm` and `data/state.db-wal` were restored from their Git blobs after SQLite cleanup noise.
- `data/listening_stats.json` remains modified runtime/stat noise.
- `.gitignore` remains an unrelated pre-existing modification.

### Next bugs to test manually
- Let a song end during normal DJ playback:
  - expected: DJ transition speech -> selected song starts
  - selected song should match the displayed/announced song
- Let a song end while chat voice is active:
  - expected: no dead air; transition should queue and run once idle
- Trigger a chat `[[play:...]]` action:
  - expected: long reply voice drains first, then confirmation voice, then selected/direct song plays
- Test Japanese/Korean/English requests:
  - expected: action tags preserve original title/artist, browser fallback voice picks a closer language if backend TTS falls back

---

## Update (2026-05-12 Opening And Transition Polish)

### User feedback addressed
- Remove visible `Claudio` naming and both `Speaking...` labels from the DJ interface.
- Opening page should behave like a personal radio DJ:
  - greet the listener
  - recommend a song
  - then play that recommended song after the DJ line
- Recommendations should be more divergent and not only from liked songs or familiar/top artists.
- When the user asks the DJ to play a song, after that direct-play song ends the next transition must not play an unrelated old playlist song underneath the DJ's segue.
- Transition copy should be natural:
  - it may mention the previous song if useful
  - it should not be forced to say "上一首..." every time

### Frontend changes
- `frontend/index.html`
- Removed the visible Claudio view toggle and placeholder view.
- Replaced visible `Claudio` script speaker label with `DJ`.
- Replaced `Speaking...` UI copy:
  - top music stage now shows `ON AIR` / `PLAYING` / `READY`
  - script badge now shows `ON AIR` / `Live Notes`
- Added `runOpeningShow(...)`:
  - on DJ startup, it calls `/api/agent/transition` with an opening-show chat context
  - context tells the agent to greet naturally and recommend a song beyond likes/top artists
  - the selected song is stored as `pendingSong`
  - the DJ line is spoken first, then `loadPendingSong()` starts the announced song
  - fallback still gives a greeting and plays a safe startup song
- Fixed direct-play ending:
  - if `state.directPlay` ends in DJ mode, it no longer immediately restores and plays the previous playlist index
  - it now clears direct play and triggers/queues a DJ transition
  - if a transition has already selected `pendingSong`, ended sets `pendingNext` and waits for the selected song instead of playing old music
- Removed pre-roll transition trigger:
  - the old `duration - currentTime <= 12` transition trigger is disabled
  - transitions now come from the real `ended` event
  - this prevents another/previous song from playing underneath the "next song" cue

### Backend recommendation changes
- `backend/agent/music_discovery.py`
  - discovery searches now use up to 7 query lanes instead of 5
  - query generation starts with exploratory/contextual searches such as indie pop, alternative R&B, city pop, dream pop, small Chinese indie/new-song queries, etc.
  - multilingual query lanes remain active
  - top artists are now only a small tail signal using one shuffled "similar recommendation" query
  - if session query de-dup exhausts the query list, it resets so discovery does not go empty too easily
- `backend/agent/dj_brain.py`
  - detects opening/exploration contexts from chat context
  - opening/exploration transitions request more discovery songs
  - opening/exploration raises discovery ratio to at least 0.85
- `backend/agent/prompts.py`
  - selection prompt now explicitly says not to pick only from liked/red-heart/most-played artists
  - transition prompt now says previous-song reference is optional
  - fallback transition copy no longer starts with "刚才那首..."

### Validation done
- Frontend JSX/Babel parse passed:
  - `babel_parse_ok lines=2556`
- Backend compile passed:
  - `python -m py_compile backend/agent/dj_brain.py backend/agent/prompts.py backend/agent/music_discovery.py backend/agent/taste_profile.py backend/dj_server.py`
- `git diff --check` produced only line-ending warnings, no whitespace errors.

### Manual checks still needed
- Open the page in DJ mode:
  - expected: DJ greets/recommends first, then plays the announced opening song.
- Ask DJ to play a song:
  - expected: requested song plays.
  - when it ends, DJ speaks a transition without old playlist audio starting underneath.
  - after the transition, the song named in the transition starts.
- Let a normal playlist song end:
  - expected: no pre-roll overlap; transition begins after the song ends, then selected song starts.

---

## Update (2026-05-12 Cleanup Pass)

### Cleanup done
- Removed old frontend components that were no longer rendered after the broadcast UI redesign:
  - `ProgressBar`
  - `PlaybackControls`
  - `VoiceWaveform`
  - `DJSpeechDisplay`
  - `ChatSection`
  - `RecommendationCards`
  - `PlayerCard`
- Removed obsolete `Claudio`/view-switch state and reducer actions:
  - `currentView`
  - `SET_VIEW`
  - old Claudio audio state fields/actions
- Removed unused legacy state fields:
  - `progress`
  - `segueType`
  - `lastReason`
  - `lastSegue`
  - `totalSeconds`
  - `liked`
  - `directSong`
- Removed old CSS tied to the deleted legacy components:
  - `.glass-light`
  - `.chat-msg`
  - `.chat-avatar`
  - `.chat-bubble`
  - `.rec-card`
  - `.rec-cover`
  - `.rec-info`
  - `.rec-title`
  - `.rec-artist`
  - `.rec-reason`
  - `.cl-view`
- Removed unused `HeartIcon`.
- Simplified the main DJ view render so it no longer checks an always-`dj` view state.
- Added runtime files to `.gitignore`:
  - `data/state.db-shm`
  - `data/state.db-wal`
  - `data/listening_stats.json`

### Validation done
- Frontend JSX/Babel parse passed:
  - `babel_parse_ok lines=2234`
- Backend compile passed:
  - `python -m py_compile backend/agent/dj_brain.py backend/agent/prompts.py backend/agent/music_discovery.py backend/agent/taste_profile.py backend/dj_server.py`
- `git diff --check -- frontend/index.html .gitignore` produced only CRLF warnings.

### Runtime caveat
- `data/state.db-shm`, `data/state.db-wal`, and `data/listening_stats.json` may still appear modified in `git status` because they are already tracked and a Python server process may hold SQLite files open.
- Do not forcibly stop Python unless the user confirms they are not actively using the local DJ server.
