from __future__ import annotations

from passive_agent.storage.database import Database
from passive_agent.storage.models import EnrichedItem, Item
from passive_agent.utils.logger import log


class Ranker:
    def __init__(self, db: Database, daily_limit: int = 3):
        self.db = db
        self.daily_limit = daily_limit

    def select_top(self, items: list[Item], limit: int | None = None) -> list[Item]:
        limit = limit or self.daily_limit
        sorted_items = sorted(items, key=lambda x: x.priority_score or 0, reverse=True)
        top = sorted_items[:limit]
        log.info(f"Ranked: top {len(top)} from {len(items)} items")
        for i, item in enumerate(top, 1):
            log.info(f"  #{i} [{item.priority_score:.1f}] {item.title}")
        return top

    def enrich(self, items: list[Item]) -> list[EnrichedItem]:
        enriched = []
        for item in items:
            related_zotero = self._find_related_zotero(item)
            enriched.append(EnrichedItem(
                item=item,
                related_zotero=related_zotero,
            ))
        return enriched

    def _find_related_zotero(self, item: Item) -> list[str]:
        """查找 DB 中同 topic 的已有条目作为相关推荐"""
        if not item.topics:
            return []

        all_items = self.db.get_items_by_stage("archived")
        related = []
        for existing in all_items:
            if existing.id == item.id:
                continue
            if any(t in existing.topics for t in item.topics):
                related.append(existing.title)
                if len(related) >= 3:
                    break
        return related
