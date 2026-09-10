from __future__ import annotations

import asyncio

from jinja2 import Environment, FileSystemLoader

from passive_agent.integrations.llm_client import LLMClient
from passive_agent.storage.models import Item
from passive_agent.utils.config import GoalsConfig
from passive_agent.utils.logger import log

VALID_ACTIONS = frozenset({"read", "make_card", "make_note", "ignore"})
VALID_CONTENT_TYPES = frozenset({"paper", "article", "note", "repo", "doc"})


class Summarizer:
    def __init__(self, llm: LLMClient, goals: GoalsConfig, prompts_dir: str = "prompts"):
        self.llm = llm
        self.goals = goals
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))
        self.template = self.jinja.get_template("summarize.md.j2")
        self.errors: list[str] = []

    async def summarize_batch(self, items: list[Item]) -> list[Item]:
        log.info(f"Summarizing {len(items)} items...")
        self.errors = []
        tasks = [self._summarize_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded = []
        for item, result in zip(items, results):
            if isinstance(result, Exception):
                msg = (
                    f"LLM summary failed for '{item.title}': {result}; "
                    "item kept retry_pending and will retry on the next pipeline run"
                )
                log.warning(msg)
                self.errors.append(msg)
            else:
                succeeded.append(result)

        log.info(f"Summarized {len(succeeded)}/{len(items)} items successfully")
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
            raise ValueError(
                f"Summary LLM returned non-object for '{item.title}': {type(data).__name__}"
            )

        summary = _required_string(data, "summary", item.title)
        interview_relevance = _required_string(data, "interview_relevance", item.title)
        recommended_action = _required_choice(
            data, "recommended_action", VALID_ACTIONS, item.title
        )
        estimated_minutes = _required_positive_int(data, "estimated_minutes", item.title)
        topics = _required_string_list(data, "topics", item.title)
        content_type = _required_choice(data, "content_type", VALID_CONTENT_TYPES, item.title)

        item.summary = summary
        item.interview_relevance = interview_relevance
        item.recommended_action = recommended_action
        item.estimated_minutes = estimated_minutes
        item.topics = topics
        item.content_type = content_type
        item.stage = "summarized"

        return item


def _required_string(data: dict, field: str, title: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid summary {field} for '{title}': expected non-empty string")
    return value.strip()


def _required_choice(data: dict, field: str, choices: frozenset[str], title: str) -> str:
    value = _required_string(data, field, title)
    if value not in choices:
        raise ValueError(f"Invalid summary {field} for '{title}': {value!r}")
    return value


def _required_positive_int(data: dict, field: str, title: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Invalid summary {field} for '{title}': expected positive integer")
    return value


def _required_string_list(data: dict, field: str, title: str) -> list[str]:
    # topics 空列表是合法输出（M3 对与面试无关的内容返回 action=ignore + topics=[]），
    # 只拒绝类型错误（非列表 / 含非字符串元素）。
    value = data.get(field)
    if not isinstance(value, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in value
    ):
        raise ValueError(
            f"Invalid summary {field} for '{title}': expected a list of non-empty strings"
        )
    return [entry.strip() for entry in value]
