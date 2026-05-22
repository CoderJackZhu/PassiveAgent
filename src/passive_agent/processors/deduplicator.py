from __future__ import annotations

from difflib import SequenceMatcher

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item
from passive_agent.utils.logger import log


class Deduplicator:
    TITLE_SIMILARITY_THRESHOLD = 0.85

    def __init__(self, db: Database):
        self.db = db

    def filter(self, items: list[Item]) -> list[Item]:
        existing_titles = self.db.get_all_titles()
        existing_urls = self.db.get_all_urls()
        result = []
        seen_titles: set[str] = set()

        for item in items:
            # URL 精确去重
            if item.url and item.url in existing_urls:
                log.debug(f"Dedup (URL match): {item.title}")
                continue

            # 标题模糊去重 (对 DB 已有 + 本批内已见)
            all_known = existing_titles | seen_titles
            if self._title_exists(item.title, all_known):
                log.debug(f"Dedup (title match): {item.title}")
                continue

            result.append(item)
            seen_titles.add(item.title)
            if item.url:
                existing_urls.add(item.url)

        deduped = len(items) - len(result)
        if deduped > 0:
            log.info(f"Dedup: removed {deduped} duplicates, {len(result)} remaining")

        return result

    def _title_exists(self, title: str, existing: set[str]) -> bool:
        title_lower = title.lower().strip()
        for existing_title in existing:
            ratio = SequenceMatcher(None, title_lower, existing_title.lower().strip()).ratio()
            if ratio >= self.TITLE_SIMILARITY_THRESHOLD:
                return True
        return False
