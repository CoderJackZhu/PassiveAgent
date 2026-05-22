from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.storage.models import Item
from passive_agent.utils.config import GoalsConfig
from passive_agent.utils.logger import log


class Summarizer:
    def __init__(self, llm: DeepSeekClient, goals: GoalsConfig, prompts_dir: str = "prompts"):
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
        metadata = {}
        if hasattr(item, '_metadata'):
            metadata = item._metadata

        prompt = self.template.render(
            title=item.title,
            source=item.source,
            abstract=item.raw_text or "",
            url=item.url or "",
            tags=", ".join(item.topics) if item.topics else "",
            collections="",
            priority_topics=self.goals.priority_topics,
        )

        data = await self.llm.generate_json(
            system="你是面试准备助手，帮助用户筛选 Agent 算法岗相关内容。",
            user=prompt,
        )

        item.summary = data.get("summary", "")
        item.interview_relevance = data.get("interview_relevance", "")
        item.recommended_action = data.get("recommended_action", "read")
        item.estimated_minutes = data.get("estimated_minutes", 15)
        item.content_type = data.get("content_type", "article")
        item.stage = "summarized"

        if data.get("topics"):
            item.topics = data["topics"]

        return item
