"""Real-time voice dialogue client for Volcano Engine real-time dialogue API.

Uses WebSocket bidirectional streaming (wss://openspeech.bytedance.com/api/v3/realtime/dialogue).
Text-in, audio-out mode — send DJ commentary text, receive streaming OGG/Opus audio.

This gives phone-call quality voice for the Chat feature, with natural prosody,
emotional expression, breathing, and rhythm — similar to GPT-4o / Grok / 豆包电话.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

try:
    import websocket
    HAS_WS = True
except ImportError:
    HAS_WS = False


class RealtimeVoiceClient:
    """WebSocket client for Volcano Engine real-time dialogue (text→voice).

    Usage:
        client = RealtimeVoiceClient(config)
        if client.connect(system_prompt="You are a friendly DJ..."):
            client.send_text("Hey there! Ready for some music?")
            client.start_receiving(audio_callback, done_callback)
            # ... audio chunks arrive via audio_callback(bytes)
            client.close()
    """

    def __init__(self, config: dict):
        tts_cfg = config.get("tts", {})
        volcano_cfg = tts_cfg.get("volcano", tts_cfg)
        rt_cfg = tts_cfg.get("realtime_voice", {})

        self.app_id = volcano_cfg.get("app_id", "")
        self.token = volcano_cfg.get("token", "")
        self.voice_type = volcano_cfg.get("voice_type", "BV700_V2_streaming")
        self.encoding = volcano_cfg.get("encoding", "mp3")

        self.enabled = rt_cfg.get("enabled", True)
        self.ws_url = rt_cfg.get(
            "ws_url", "wss://openspeech.bytedance.com/api/v3/realtime/dialogue")
        self.model = rt_cfg.get("model", "O2.0")
        self.speech_rate = rt_cfg.get("speech_rate", 0)
        self.loudness_rate = rt_cfg.get("loudness_rate", 0)

        self._ws = None
        self._is_connected = False
        self._session_id = None
        self._receive_thread = None
        self._stop_receiving = False

    def connect(self, system_prompt: str,
                greeting_text: str = "") -> bool:
        """Connect to real-time dialogue WebSocket and start a session.

        Args:
            system_prompt: DJ personality prompt injected into the voice model
            greeting_text: Optional initial greeting spoken by the model
        Returns: True if connected successfully
        """
        if not HAS_WS:
            print("[RealtimeVoice] websocket-client not installed")
            return False
        if not self.app_id or not self.token or not self.enabled:
            return False

        try:
            self._ws = websocket.create_connection(
                self.ws_url,
                header={
                    "X-Api-App-ID": self.app_id,
                    "X-Api-Access-Key": self.token,
                    "X-Api-Resource-Id": "volc.speech.dialog",
                    "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
                },
                timeout=15,
            )
        except Exception as e:
            print(f"[RealtimeVoice] WebSocket connection failed: {e}")
            self._ws = None
            return False

        # Send session start with configuration
        session_id = str(uuid.uuid4())
        config_msg = {
            "session_id": session_id,
            "model": self.model,
            "voice": self.voice_type,
            "system_prompt": system_prompt,
            "audio_config": {
                "format": self.encoding,
                "speech_rate": self.speech_rate,
                "loudness_rate": self.loudness_rate,
            },
        }

        if greeting_text:
            config_msg["greeting"] = greeting_text

        try:
            self._ws.send(json.dumps(config_msg))
            # Wait for session ready acknowledgment
            ack_raw = self._ws.recv()
            ack = json.loads(ack_raw) if isinstance(ack_raw, str) else {}
            code = ack.get("code", -1)
            if code == 0 or code == 3000:
                self._is_connected = True
                self._session_id = session_id
                print(f"[RealtimeVoice] Session started: {session_id[:8]}... "
                      f"model={self.model}, voice={self.voice_type}")
                return True
            else:
                print(f"[RealtimeVoice] Session start failed: {ack}")
                self._ws.close()
                self._ws = None
                return False
        except Exception as e:
            print(f"[RealtimeVoice] Session negotiation failed: {e}")
            self._ws.close()
            self._ws = None
            return False

    def send_text(self, text: str) -> bool:
        """Send text for the voice model to speak.

        The model generates natural speech with the configured voice and
        personality (system prompt). Audio chunks arrive via the callback
        registered in start_receiving().
        """
        if not self._is_connected or not self._ws or not text:
            return False

        try:
            msg = {
                "session_id": self._session_id,
                "type": "text",
                "text": text,
            }
            self._ws.send(json.dumps(msg))
            return True
        except Exception as e:
            print(f"[RealtimeVoice] Send text failed: {e}")
            return False

    def start_receiving(self, audio_callback: callable,
                        done_callback: callable | None = None,
                        error_callback: callable | None = None):
        """Start background thread to receive audio chunks.

        Args:
            audio_callback: Called with bytes (audio chunk) as they arrive
            done_callback: Called when the utterance is complete
            error_callback: Called with error string on failure
        """
        if not self._is_connected or not self._ws:
            if error_callback:
                error_callback("Not connected")
            return

        self._stop_receiving = False

        def _run():
            while not self._stop_receiving and self._is_connected:
                try:
                    self._ws.settimeout(1.0)
                    message = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    if self._is_connected and not self._stop_receiving:
                        print(f"[RealtimeVoice] Receive error: {e}")
                        if error_callback:
                            error_callback(str(e))
                    break

                if isinstance(message, bytes):
                    # Audio data chunk (OGG/Opus or MP3 depending on config)
                    audio_callback(message)
                elif isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type", "")
                        if msg_type == "done" or msg_type == "end":
                            if done_callback:
                                done_callback()
                            break
                        elif msg_type == "error":
                            err = data.get("message", "Unknown error")
                            print(f"[RealtimeVoice] Server error: {err}")
                            if error_callback:
                                error_callback(err)
                            break
                    except json.JSONDecodeError:
                        pass

        self._receive_thread = threading.Thread(target=_run, daemon=True)
        self._receive_thread.start()

    def wait_for_completion(self, timeout: float = 30.0):
        """Block until the current utterance finishes or timeout."""
        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=timeout)

    def close(self):
        """End the session and close the WebSocket connection."""
        self._stop_receiving = True
        self._is_connected = False

        if self._ws:
            try:
                end_msg = {
                    "session_id": self._session_id,
                    "type": "end",
                }
                self._ws.send(json.dumps(end_msg))
                time.sleep(0.3)
                self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=2.0)

    def check_available(self) -> bool:
        """Check if real-time voice is configured and websocket is available."""
        return bool(HAS_WS and self.app_id and self.token and self.enabled)
