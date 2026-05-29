from __future__ import annotations

import asyncio

from jinja2 import Environment, FileSystemLoader

from passive_agent.integrations.llm_client import LLMClient
from passive_agent.storage.database import Database
from passive_agent.storage.models import Item, Score
from passive_agent.utils.config import GoalsConfig, ScoringConfig
from passive_agent.utils.logger import log

COLLECTION_BOOST = 1.15


class Scorer:
    def __init__(self, llm: LLMClient, goals: GoalsConfig, scoring: ScoringConfig,
                 db: Database, prompts_dir: str = "prompts",
                 high_priority_collections: list[str] | None = None):
        self.llm = llm
        self.goals = goals
        self.scoring = scoring
        self.db = db
        self.high_priority_collections = high_priority_collections or []
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))
        self.template = self.jinja.get_template("score.md.j2")

    async def score_batch(self, items: list[Item]) -> list[Item]:
        existing_cards = self.db.get_archived_titles()
        log.info(f"Scoring {len(items)} items (existing cards: {len(existing_cards)})...")

        tasks = [self._score_one(item, existing_cards) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for item, result in zip(items, results):
            if isinstance(result, Exception):
                log.warning(f"Failed to score '{item.title}': {result}")
                item.priority_score = 50.0  # 默认中等分
                scored.append(item)
            else:
                scored.append(result)

        # 应用 topic/source 动态权重
        for item in scored:
            adjustment = self._calc_weight_adjustment(item)
            if item.priority_score:
                item.priority_score *= adjustment

        scored_count = sum(1 for i in scored if i.priority_score and i.priority_score != 50.0)
        log.info(f"Scored {scored_count}/{len(items)} items via LLM")
        return scored

    async def _score_one(self, item: Item, existing_cards: list[str]) -> Item:
        prompt = self.template.render(
            title=item.title,
            summary=item.summary or "",
            interview_relevance=item.interview_relevance or "",
            source=item.source,
            content_type=item.content_type or "article",
            existing_cards=existing_cards[-20:],
            priority_topics=self.goals.priority_topics,
        )

        data = await self.llm.generate_json(
            system="你是面试内容评分器，严格输出 JSON 评分。",
            user=prompt,
        )
        if not isinstance(data, dict):
            log.warning(f"Score LLM returned non-object for '{item.title}': {type(data).__name__}")
            data = {}

        goal_relevance = _as_score(data.get("goal_relevance"), "goal_relevance", item.title)
        novelty = _as_score(data.get("novelty"), "novelty", item.title)
        actionability = _as_score(data.get("actionability"), "actionability", item.title)
        difficulty_fit = _as_score(data.get("difficulty_fit"), "difficulty_fit", item.title)
        source_quality = _as_score(data.get("source_quality"), "source_quality", item.title)
        timeliness = _as_score(data.get("timeliness"), "timeliness", item.title)

        w = self.scoring.weights
        weighted_total = (
            goal_relevance * w.goal_relevance +
            novelty * w.novelty +
            actionability * w.actionability +
            difficulty_fit * w.difficulty_fit +
            source_quality * w.source_quality +
            timeliness * w.timeliness
        )

        score = Score(
            item_id=item.id,
            goal_relevance=goal_relevance,
            novelty=novelty,
            actionability=actionability,
            difficulty_fit=difficulty_fit,
            source_quality=source_quality,
            timeliness=timeliness,
            weighted_total=weighted_total,
        )
        self.db.save_score(score)

        item.priority_score = weighted_total
        return item

    def _calc_weight_adjustment(self, item: Item) -> float:
        adjustment = 1.0
        # Boost for high-priority collections
        if self.high_priority_collections:
            for topic in item.topics:
                if topic in self.high_priority_collections:
                    adjustment *= COLLECTION_BOOST
                    break
        # Penalty for low-weight topics/sources
        for topic in item.topics:
            tw = self.db.get_topic_weight(topic)
            if tw < 1.0:
                adjustment *= tw
        sw = self.db.get_source_weight(item.source)
        adjustment *= sw
        return adjustment


def _as_score(value, field: str, title: str) -> float:
    if isinstance(value, bool):
        log.warning(f"Invalid score {field} for '{title}': bool")
        return 50.0
    if isinstance(value, int | float):
        return float(value)
    log.warning(f"Invalid score {field} for '{title}': {value!r}")
    return 50.0
