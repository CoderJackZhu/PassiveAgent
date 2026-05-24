from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class RawItem:
    """收集器输出的原始条目"""

    source: str
    title: str
    url: str | None = None
    local_path: str | None = None
    zotero_key: str | None = None
    raw_text: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Item:
    """标准化后的条目"""

    id: str
    source: Literal["zotero", "obsidian_inbox", "github_star", "hf_daily_papers"]
    title: str
    url: str | None = None
    local_path: str | None = None
    zotero_key: str | None = None
    collected_at: datetime = field(default_factory=datetime.now)
    content_type: str | None = None
    topics: list[str] = field(default_factory=list)
    stage: str = "new"
    summary: str | None = None
    interview_relevance: str | None = None
    estimated_minutes: int | None = None
    priority_score: float | None = None
    recommended_action: str | None = None
    ignored_count: int = 0
    is_weekend: bool = False
    raw_text: str | None = None
    extra_meta: dict | None = None
    created_at: datetime = field(default_factory=datetime.now)
    actioned_at: datetime | None = None

    def to_dict(self) -> dict:
        import json

        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "local_path": self.local_path,
            "zotero_key": self.zotero_key,
            "collected_at": self.collected_at.isoformat(),
            "content_type": self.content_type,
            "topics": json.dumps(self.topics, ensure_ascii=False),
            "stage": self.stage,
            "summary": self.summary,
            "interview_relevance": self.interview_relevance,
            "estimated_minutes": self.estimated_minutes,
            "priority_score": self.priority_score,
            "recommended_action": self.recommended_action,
            "ignored_count": self.ignored_count,
            "is_weekend": int(self.is_weekend),
            "raw_text": self.raw_text,
            "extra_meta": json.dumps(self.extra_meta, ensure_ascii=False) if self.extra_meta else None,
            "created_at": self.created_at.isoformat(),
            "actioned_at": self.actioned_at.isoformat() if self.actioned_at else None,
        }

    @classmethod
    def from_row(cls, row: dict) -> Item:
        import json

        topics = row.get("topics")
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except (json.JSONDecodeError, TypeError):
                topics = []
        if not isinstance(topics, list):
            topics = []
        topics = [topic for topic in topics if isinstance(topic, str)]

        extra_meta = row.get("extra_meta")
        if isinstance(extra_meta, str):
            try:
                extra_meta = json.loads(extra_meta)
            except (json.JSONDecodeError, TypeError):
                extra_meta = {}
        if not isinstance(extra_meta, dict):
            extra_meta = {}

        return cls(
            id=row["id"],
            source=row["source"],
            title=row["title"],
            url=row.get("url"),
            local_path=row.get("local_path"),
            zotero_key=row.get("zotero_key"),
            collected_at=datetime.fromisoformat(row["collected_at"]),
            content_type=row.get("content_type"),
            topics=topics or [],
            stage=row["stage"],
            summary=row.get("summary"),
            interview_relevance=row.get("interview_relevance"),
            estimated_minutes=row.get("estimated_minutes"),
            priority_score=row.get("priority_score"),
            recommended_action=row.get("recommended_action"),
            ignored_count=row.get("ignored_count", 0),
            is_weekend=bool(row.get("is_weekend", 0)),
            raw_text=row.get("raw_text"),
            extra_meta=extra_meta,
            created_at=datetime.fromisoformat(row["created_at"]),
            actioned_at=datetime.fromisoformat(row["actioned_at"]) if row.get("actioned_at") else None,
        )


@dataclass
class Score:
    """条目的多维度评分"""

    item_id: str
    goal_relevance: float
    novelty: float
    actionability: float
    difficulty_fit: float
    source_quality: float
    timeliness: float
    weighted_total: float
    scored_at: datetime = field(default_factory=datetime.now)


@dataclass
class FeedbackRecord:
    """用户操作反馈"""

    id: int | None
    item_id: str
    action: str
    topic: str | None
    source: str | None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class EnrichedItem:
    """经过 Enrich 的推荐条目"""

    item: Item
    score: Score | None = None
    related_zotero: list[str] = field(default_factory=list)
    related_stars: list[str] = field(default_factory=list)
