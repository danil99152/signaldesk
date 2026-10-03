from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, api_key: str, timeout: float = 600.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/market-analyst",
                "X-Title": "Market Analyst",
            },
        )
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        retries: int = 3,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await self._client.post(OPENROUTER_URL, json=payload)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    # Ошибки 4xx (неверный ключ/модель) повторять бессмысленно
                    raise SystemExit(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
                data = resp.json()
                if "error" in data:
                    raise LLMError(str(data["error"]))
                for key in self.usage:
                    self.usage[key] += (data.get("usage") or {}).get(key, 0)
                content = data["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    raise LLMError("пустой ответ модели")
                return content
            except (httpx.HTTPError, LLMError, KeyError, ValueError) as exc:
                last_exc = exc
                wait = 2 ** (attempt + 1)
                log.warning("%s: попытка %d не удалась (%s), жду %ds", model, attempt + 1, exc, wait)
                await asyncio.sleep(wait)
        raise LLMError(f"{model}: все попытки исчерпаны: {last_exc}")

    async def chat_json(self, model: str, messages: list[dict], **kwargs) -> Any:
        text = await self.chat(model, messages, json_mode=True, **kwargs)
        return extract_json(text)


def extract_json(text: str) -> Any:
    """Достаёт JSON из ответа модели (с учётом <think>-блоков и ```json-обёрток)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError(f"В ответе нет JSON: {text[:200]}")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])
