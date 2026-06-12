from __future__ import annotations

import asyncio
import json
import os
import time

from openai import AsyncOpenAI

from passive_agent.utils.logger import log


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_key_env: str = "DEEPSEEK_API_KEY",
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        max_concurrency: int = 5,
        temperature: float = 0.3,
        max_retries: int = 3,
        retry_backoff_base_seconds: float = 2.0,
        request_timeout_seconds: float = 45.0,
    ):
        self.api_key_env = api_key_env
        self.api_key = api_key or os.environ.get(api_key_env, "")
        if not self.api_key:
            raise ValueError(f"{api_key_env} not set")

        self.base_url = base_url
        self.request_timeout_seconds = max(1.0, request_timeout_seconds)
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=self.request_timeout_seconds,
            # The SDK has its own retry loop by default. PassiveAgent already
            # retries explicitly below; disabling SDK retries keeps one Feishu
            # button click bounded by llm.request_timeout_seconds × max_retries
            # instead of silently multiplying slow upstream calls.
            max_retries=0,
        )
        self.model = model
        self.max_concurrency = max(1, max_concurrency)
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
        self.retry_backoff_base_seconds = max(0.0, retry_backoff_base_seconds)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def generate(self, system: str, user: str, expect_json: bool = False) -> str:
        async with self._semaphore:
            kwargs: dict = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
            }
            if expect_json:
                kwargs["response_format"] = {"type": "json_object"}

            for attempt in range(self.max_retries):
                start = time.perf_counter()
                try:
                    response = await self.client.chat.completions.create(**kwargs)
                    elapsed = time.perf_counter() - start
                    log.info(f"LLM request completed in {elapsed:.1f}s (model={self.model})")
                    return response.choices[0].message.content or ""
                except Exception as e:
                    elapsed = time.perf_counter() - start
                    if "401" in str(e) or "authentication" in str(e).lower():
                        raise
                    if attempt < self.max_retries - 1:
                        wait = self.retry_backoff_base_seconds * (2 ** attempt)
                        log.warning(
                            f"LLM API error after {elapsed:.1f}s "
                            f"(attempt {attempt + 1}/{self.max_retries}, retry in {wait:g}s): {e}"
                        )
                        await asyncio.sleep(wait)
                    else:
                        log.warning(
                            f"LLM API failed after {elapsed:.1f}s "
                            f"(attempt {attempt + 1}/{self.max_retries}): {e}"
                        )
                        raise

    async def generate_json(self, system: str, user: str) -> dict:
        text = await self.generate(system, user, expect_json=True)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
