from __future__ import annotations

from datetime import date, datetime

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item, RawItem


class Normalizer:
    def __init__(self, db: Database):
        self.db = db

    def normalize(self, raw_items: list[RawItem]) -> list[Item]:
        today = date.today()
        date_str = today.strftime("%Y%m%d")
        existing_count = self.db.count_items_by_date(date_str)
        items = []

        for i, raw in enumerate(raw_items, start=existing_count + 1):
            item_id = f"item_{date_str}_{i:03d}"
            now = datetime.now()

            items.append(Item(
                id=item_id,
                source=raw.source,
                title=raw.title,
                url=raw.url,
                local_path=raw.local_path,
                zotero_key=raw.zotero_key,
                collected_at=now,
                content_type=None,
                topics=raw.metadata.get("tags", []),
                stage="new",
                raw_text=raw.raw_text,
                created_at=now,
            ))

        return items
