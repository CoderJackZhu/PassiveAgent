from __future__ import annotations

from datetime import date, datetime

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item, RawItem


class Normalizer:
    def __init__(self, db: Database, high_priority_collections: list[str] | None = None):
        self.db = db
        self.high_priority_collections = high_priority_collections or []

    def normalize(self, raw_items: list[RawItem]) -> list[Item]:
        today = date.today()
        date_str = today.strftime("%Y%m%d")
        existing_count = self.db.count_items_by_date(date_str)
        items = []

        for i, raw in enumerate(raw_items, start=existing_count + 1):
            item_id = f"item_{date_str}_{i:03d}"
            now = datetime.now()

            topics = raw.metadata.get("tags") or raw.metadata.get("topics") or []
            collections = raw.metadata.get("collections") or []
            # Merge collections into topics for scoring
            for c in collections:
                if c not in topics:
                    topics.append(c)

            # Extract extra metadata (language, stars, Zotero fields, etc.) for persistence
            extra_meta = None
            extra_keys = (
                "language", "stars", "github_topics", "abstract", "collections", "date_added",
                "paper_id", "upvotes",
            )
            extra = {k: raw.metadata[k] for k in extra_keys if k in raw.metadata}
            if extra:
                extra_meta = extra

            raw_text = raw.raw_text or raw.metadata.get("abstract")

            items.append(Item(
                id=item_id,
                source=raw.source,
                title=raw.title,
                url=raw.url,
                local_path=raw.local_path,
                zotero_key=raw.zotero_key,
                collected_at=now,
                content_type=None,
                topics=topics,
                stage="new",
                raw_text=raw_text,
                extra_meta=extra_meta,
                created_at=now,
            ))

        return items
