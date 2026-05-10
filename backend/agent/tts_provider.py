"""TTS provider — 火山引擎豆包语音合成 (HTTP 非流式, SSML enabled)."""

import base64
import json
import re
import time
import uuid

import requests


# ── SSML Mood Configuration ─────────────────────────────
# Percentage-based prosody adjustments per DJ mood
DEFAULT_SSML_MOOD_CONFIG = {
    "energetic":  {"pitch": "+8%",  "rate": "+15%", "volume": "+20%"},
    "melancholy": {"pitch": "-6%",  "rate": "-10%", "volume": "-10%"},
    "chill":      {"pitch": "-3%",  "rate": "-5%",  "volume": "0%"},
    "playful":    {"pitch": "+5%",  "rate": "+8%",  "volume": "+10%"},
    "nostalgic":  {"pitch": "-4%",  "rate": "-8%",  "volume": "-5%"},
    "warm":       {"pitch": "-2%",  "rate": "-3%",  "volume": "+5%"},
    "dark":       {"pitch": "-8%",  "rate": "-12%", "volume": "-8%"},
}


class TTSProvider:
    def __init__(self, config: dict):
        tts_cfg = config.get("tts", {})
        self.app_id = tts_cfg.get("app_id", "")
        self.token = tts_cfg.get("token", "")
        self.voice_type = tts_cfg.get("voice_type", "BV700_V2_streaming")
        self.resource_id = tts_cfg.get("resource_id", "volc.tts.default")
        self.encoding = tts_cfg.get("encoding", "mp3")
        self.speed_ratio = tts_cfg.get("speed_ratio", 0.95)
        self.volume_ratio = tts_cfg.get("volume_ratio", 1.0)
        self.pitch_ratio = tts_cfg.get("pitch_ratio", 1.0)
        self._api_url = "https://openspeech.bytedance.com/api/v1/tts"

        # SSML config
        self.ssml_enabled = tts_cfg.get("ssml_enabled", True)
        mood_params = tts_cfg.get("mood_params", {})
        if mood_params:
            self.mood_params = mood_params  # legacy map for fallback
        self.ssml_mood_config = tts_cfg.get("ssml_mood_config", DEFAULT_SSML_MOOD_CONFIG)

    # ── Public API ─────────────────────────────────────

    def synthesize(self, text: str, mood: str = "chill") -> bytes | None:
        """Convert text to speech, returns audio bytes (mp3)."""
        if not self.app_id or not self.token or not text:
            return None

        text = self._clean_text(text)

        if self.ssml_enabled:
            clean_text, emphasis_words = self._extract_emphasis(text)
            ssml_text = self._build_ssml(clean_text, mood, emphasis_words)
            text_type = "ssml"
            request_text = ssml_text
            # SSML handles prosody — use neutral base params
            speed = 1.0
            pitch = 1.0
        else:
            text_type = "plain"
            request_text = text
            mood_cfg = self.mood_params.get(mood, {})
            speed = mood_cfg.get("speed_ratio", self.speed_ratio)
            pitch = mood_cfg.get("pitch_ratio", self.pitch_ratio)

        payload = {
            "app": {
                "appid": self.app_id,
                "token": "placeholder",
                "cluster": "volcano_tts",
            },
            "user": {
                "uid": "music_dj_user",
            },
            "audio": {
                "voice_type": self.voice_type,
                "encoding": self.encoding,
                "speed_ratio": speed,
                "volume_ratio": self.volume_ratio,
                "pitch_ratio": pitch,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": request_text,
                "text_type": text_type,
                "operation": "query",
                "silence_duration": 125,
            },
        }

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                self._api_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer;{self.token}",
                },
                json=payload,
                timeout=15,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as e:
            print(f"[TTS] Request failed: {e}")
            return None

        if resp.status_code != 200:
            print(f"[TTS] HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            result = resp.json()
        except Exception:
            print(f"[TTS] Invalid JSON response: {resp.text[:200]}")
            return None

        code = result.get("code")
        if code != 3000:
            print(f"[TTS] API error code={code}: {result.get('message', 'unknown')}")
            return None

        audio_b64 = result.get("data")
        if not audio_b64:
            print("[TTS] No audio data in response")
            return None

        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as e:
            print(f"[TTS] Base64 decode failed: {e}")
            return None

        duration = result.get("addition", {}).get("duration", "?")
        mode = "SSML" if self.ssml_enabled else "plain"
        print(f"[TTS] Synthesized {len(audio_bytes)} bytes ({mode}), {duration}ms, latency={elapsed_ms}ms, mood={mood}")
        return audio_bytes

    def synthesize_stream(self, text: str, mood: str = "chill",
                          callback: callable = None) -> None:
        """Stream TTS audio by splitting text into sentence groups.

        Each sentence group is synthesized independently via HTTP TTS.
        Results are sent via callback(audio_chunk: bytes) as they complete.
        The last callback sends b"__END__" to signal completion.

        This gives a "streaming" feel for longer texts without needing
        a true WebSocket TTS API — audio starts playing while later
        sentences are still being generated.
        """
        import threading

        if not self.app_id or not self.token or not text:
            if callback:
                callback(b"__END__")
            return

        # Split text into sentence groups
        groups = self._split_into_groups(text)
        if not groups:
            if callback:
                callback(b"__END__")
            return

        results = {}
        results_lock = threading.Lock()
        errors = []

        def synthesize_group(idx: int, group_text: str):
            audio = None
            try:
                audio = self.synthesize(group_text, mood)
            except Exception as e:
                errors.append(str(e))
            if audio is None:
                # Retry with plain text (SSML might have failed on short text)
                try:
                    self.ssml_enabled = False
                    audio = self.synthesize(group_text, mood)
                except Exception:
                    pass
                finally:
                    self.ssml_enabled = self.ssml_enabled

            with results_lock:
                results[idx] = audio

        threads = []
        for i, group in enumerate(groups):
            t = threading.Thread(target=synthesize_group, args=(i, group), daemon=True)
            threads.append(t)
            t.start()

        # Send results in order as they become available
        next_to_send = 0
        pending = {}
        all_done = False

        while not all_done:
            all_done = all(not t.is_alive() for t in threads)

            with results_lock:
                # Move completed results from results dict to pending (ordered)
                for idx in sorted(results.keys()):
                    if idx not in pending:
                        pending[idx] = results.pop(idx)

            # Send next sequential chunks
            while next_to_send in pending:
                chunk = pending.pop(next_to_send)
                if chunk and callback:
                    callback(chunk)
                next_to_send += 1

            if all_done:
                break
            time.sleep(0.1)

        # Send any remaining out-of-order chunks
        with results_lock:
            remaining = sorted(results.keys())
        for idx in remaining:
            chunk = results.pop(idx, None)
            if chunk and callback:
                callback(chunk)

        # Flush pending
        for idx in sorted(pending.keys()):
            chunk = pending.pop(idx, None)
            if chunk and callback:
                callback(chunk)

        if callback:
            callback(b"__END__")

    @staticmethod
    def _split_into_groups(text: str, max_chars: int = 50) -> list[str]:
        """Split text into sentence groups for streaming TTS.

        Each group is a complete sentence or fragment that sounds natural
        when spoken in isolation.
        """
        if not text:
            return []

        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[。！？])(?![。！？])', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return [text]

        # Group short sentences together
        groups = []
        current = ""
        for s in sentences:
            if len(current) + len(s) <= max_chars:
                current += s
            else:
                if current:
                    groups.append(current)
                current = s
        if current:
            groups.append(current)

        return groups

    def check_available(self) -> bool:
        return bool(self.app_id and self.token)

    # ── SSML Builder ───────────────────────────────────

    def _build_ssml(self, text: str, mood: str, emphasis_words: list[str] | None = None) -> str:
        """Wrap text in SSML with mood-based prosody and emphasis markers.

        Produces valid SSML compatible with 火山引擎 HTTP TTS API.
        Uses only tags documented by Volcano: <speak>, <break>, <emphasis>.
        Prosody is applied via <speak> root attributes (pitch/rate).
        """
        mood_cfg = self.ssml_mood_config.get(mood, self.ssml_mood_config.get("chill", {}))
        pitch = mood_cfg.get("pitch", "0%")
        rate = mood_cfg.get("rate", "0%")

        # Build SSML
        ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        ssml += f'xml:lang="zh-CN" pitch="{pitch}" rate="{rate}">\n'

        # Process text: convert punctuation to breaks, inject emphasis tags
        processed = self._insert_emotional_prosody(text, mood, emphasis_words)
        ssml += processed
        ssml += '\n</speak>'
        return ssml

    def _insert_emotional_prosody(self, text: str, mood: str,
                                  emphasis_words: list[str] | None = None) -> str:
        """Insert SSML break/emphasis tags based on punctuation and mood.

        Punctuation → break mapping:
          …… / …  → long pause (600ms)
          —— / —  → medium pause (400ms)
          。！？   → sentence-end pause (250ms)
          ，、；   → clause pause (100ms)
        """
        # Escape XML special chars first (except our markers)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Long pause: ellipsis (native Chinese …… or single …)
        text = re.sub(r'…{2,}', '<break time="600ms"/>', text)
        text = re.sub(r'(?<!<)…(?!>)', '<break time="500ms"/>', text)

        # Medium pause: em-dash
        text = re.sub(r'—{2,}', '<break time="400ms"/>', text)
        text = re.sub(r'(?<!<)—(?!>)', '<break time="350ms"/>', text)

        # Sentence boundary: 。！？
        text = re.sub(r'([。！？])', r'\1<break time="250ms"/>', text)

        # Clause boundary: ，、；
        text = re.sub(r'([，、；])', r'\1<break time="100ms"/>', text)

        # Apply emphasis words
        if emphasis_words:
            for word in emphasis_words:
                escaped = re.escape(word)
                # Only wrap if the word appears as a standalone term
                text = re.sub(
                    rf'(?<!<emphasis[^>]*>)(?<!["\w]){escaped}(?!["\w])(?!</emphasis>)',
                    f'<emphasis level="moderate">{word}</emphasis>',
                    text,
                    count=1,
                )

        # Mood-specific micro-adjustments
        if mood == "energetic":
            # Reduce pauses slightly for faster pace
            text = text.replace('<break time="250ms"/>', '<break time="150ms"/>')
        elif mood in ("melancholy", "dark", "nostalgic"):
            # Lengthen sentence pauses for slower, heavier feel
            text = text.replace('<break time="250ms"/>', '<break time="350ms"/>')

        return text

    @staticmethod
    def _extract_emphasis(text: str) -> tuple[str, list[str]]:
        """Extract [em:word] markers from LLM output.

        Returns (clean_text, emphasis_words_list).
        Example: "这首歌 [em:太绝了]" → ("这首歌 太绝了", ["太绝了"])
        """
        words = re.findall(r'\[em:([^\]]+)\]', text)
        clean = re.sub(r'\[em:[^\]]+\]', '', text)
        # Clean up double spaces from marker removal
        clean = re.sub(r'\s{2,}', ' ', clean).strip()
        return clean, words

    # ── Text Cleaner ───────────────────────────────────

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove parenthetical stage directions like (叹气), (笑), (停顿) etc."""
        # Remove （中文括号） content
        text = re.sub(r'（[^）]*）', '', text)
        # Remove (英文括号) content — stage directions, not acronyms
        text = re.sub(r'\([^)]{1,20}\)', '', text)
        # Remove multiple consecutive spaces
        text = re.sub(r'\s+', ' ', text)
        # Remove leading/trailing whitespace
        text = text.strip()
        # Remove duplicate punctuation
        text = re.sub(r'([。！？…])\1+', r'\1', text)
        return text
