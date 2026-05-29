from __future__ import annotations

import asyncio

from jinja2 import Environment, FileSystemLoader

from passive_agent.integrations.llm_client import LLMClient
from passive_agent.storage.models import Item
from passive_agent.utils.config import GoalsConfig
from passive_agent.utils.logger import log


class Summarizer:
    def __init__(self, llm: LLMClient, goals: GoalsConfig, prompts_dir: str = "prompts"):
        self.llm = llm
        self.goals = goals
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))
        self.template = self.jinja.get_template("summarize.md.j2")

    async def summarize_batch(self, items: list[Item]) -> list[Item]:
        log.info(f"Summarizing {len(items)} items...")
        tasks = [self._summarize_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded = []
        for item, result in zip(items, results):
            if isinstance(result, Exception):
                log.warning(f"Failed to summarize '{item.title}': {result}")
                succeeded.append(item)  # 保留但不更新摘要
            else:
                succeeded.append(result)

        summarized_count = sum(1 for i in succeeded if i.summary is not None)
        log.info(f"Summarized {summarized_count}/{len(items)} items successfully")
        return succeeded

    async def _summarize_one(self, item: Item) -> Item:
        metadata = item.extra_meta or {}
        if hasattr(item, '_metadata'):
            metadata = {**metadata, **item._metadata}

        collections = metadata.get("collections") or ""
        if isinstance(collections, list):
            collections = ", ".join(str(c) for c in collections if c)

        prompt = self.template.render(
            title=item.title,
            source=item.source,
            abstract=item.raw_text or metadata.get("abstract") or "",
            url=item.url or "",
            tags=", ".join(item.topics) if item.topics else "",
            collections=collections,
            priority_topics=self.goals.priority_topics,
        )

        data = await self.llm.generate_json(
            system="你是面试准备助手，帮助用户筛选 Agent 算法岗相关内容。",
            user=prompt,
        )

        if not isinstance(data, dict):
            log.warning(f"Summary LLM returned non-object for '{item.title}': {type(data).__name__}")
            data = {}

        item.summary = _as_string(data.get("summary"), "")
        item.interview_relevance = _as_string(data.get("interview_relevance"), "")
        item.recommended_action = _as_string(data.get("recommended_action"), "read")
        item.estimated_minutes = _as_int(data.get("estimated_minutes"), 15, item.title)
        item.content_type = _as_string(data.get("content_type"), "article")
        item.stage = "summarized"

        if "topics" in data:
            item.topics = _as_string_list(data.get("topics"), item.topics, item.title)

        return item


def _as_string(value, default: str) -> str:
    return value if isinstance(value, str) else default


def _as_int(value, default: int, title: str) -> int:
    if isinstance(value, bool):
        log.warning(f"Invalid estimated_minutes for '{title}': bool")
        return default
    if isinstance(value, int):
        return value
    log.warning(f"Invalid estimated_minutes for '{title}': {value!r}")
    return default


def _as_string_list(value, default: list[str], title: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(topic, str) for topic in value):
        log.warning(f"Invalid topics for '{title}': {value!r}")
        return default
    return value
