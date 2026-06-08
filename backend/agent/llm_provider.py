"""LLM provider — DeepSeek API (OpenAI-compatible)."""

import json
import time
import requests


class LLMProvider:
    def __init__(self, config: dict):
        llm_cfg = config.get("agent", {}).get("llm", {})
        self.provider = llm_cfg.get("provider", "deepseek")
        self.api_key = llm_cfg.get("api_key", "")
        self.base_url = llm_cfg.get("base_url") or "https://api.deepseek.com"
        self.model = llm_cfg.get("model") or "deepseek-chat"
        self.temperature = llm_cfg.get("temperature", 0.95)
        self.max_tokens = llm_cfg.get("max_tokens", 400)

    def generate(self, system_prompt: str, user_prompt: str,
                 json_mode: bool = True) -> dict | None:
        """Generate response from DeepSeek API. Returns dict with result + metadata."""
        if not self.api_key or not self.base_url:
            return None

        t0 = time.perf_counter()
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            body = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}

            resp = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=30,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            if resp.status_code != 200:
                return None

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                return None

            return {"text": content.strip(), "model": self.model,
                    "latency_ms": elapsed_ms, "method": self.provider}
        except Exception:
            return None

    def generate_stream(self, system_prompt: str, user_prompt: str,
                        chat_history: list[dict] | None = None):
        """Stream tokens from DeepSeek API. Yields token strings."""
        if not self.api_key or not self.base_url:
            yield None
            return

        messages = [{"role": "system", "content": system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": user_prompt})

        try:
            resp = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "stream": True,
                },
                timeout=60,
                stream=True,
            )

            if resp.status_code != 200:
                yield None
                return

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue
        except Exception:
            yield None

    def check_available(self) -> bool:
        """Check if the DeepSeek API is reachable."""
        if not self.api_key or not self.base_url:
            return False
        try:
            resp = requests.get(
                f"{self.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=3,
            )
            return resp.status_code == 200
        except Exception:
            return False
