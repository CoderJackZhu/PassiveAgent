from __future__ import annotations

import asyncio
import json
import os

from openai import AsyncOpenAI

from passive_agent.utils.logger import log


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
        self.model = "deepseek-chat"
        self._semaphore = asyncio.Semaphore(5)

    async def generate(self, system: str, user: str, expect_json: bool = False) -> str:
        async with self._semaphore:
            kwargs: dict = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
            }
            if expect_json:
                kwargs["response_format"] = {"type": "json_object"}

            for attempt in range(3):
                try:
                    response = await self.client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content or ""
                except Exception as e:
                    # 认证错误不重试
                    if "401" in str(e) or "authentication" in str(e).lower():
                        raise
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        log.warning(f"DeepSeek API error (retry in {wait}s): {e}")
                        await asyncio.sleep(wait)
                    else:
                        raise

    async def generate_json(self, system: str, user: str) -> dict:
        text = await self.generate(system, user, expect_json=True)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)
