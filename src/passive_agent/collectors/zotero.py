from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from passive_agent.storage.models import RawItem
from passive_agent.utils.logger import log


class ZoteroCollector:
    def __init__(
        self,
        db_path: str,
        lookback_days: int = 7,
        sqlite_timeout_seconds: float = 30.0,
        db_retries: int = 3,
        db_retry_sleep_seconds: float = 5.0,
    ):
        self.db_path = Path(db_path).expanduser()
        self.lookback_days = lookback_days
        self.sqlite_timeout_seconds = max(0.1, sqlite_timeout_seconds)
        self.db_retries = max(1, db_retries)
        self.db_retry_sleep_seconds = max(0.0, db_retry_sleep_seconds)

    def is_available(self) -> bool:
        return self.db_path.exists()

    async def collect(self) -> list[RawItem]:
        if not self.is_available():
            log.warning(f"Zotero database not found: {self.db_path}")
            return []

        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        for attempt in range(self.db_retries):
            try:
                return self._read_items(cutoff)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < self.db_retries - 1:
                    log.warning(f"Zotero DB locked, retrying ({attempt + 1}/{self.db_retries})...")
                    import asyncio
                    await asyncio.sleep(self.db_retry_sleep_seconds)
                else:
                    log.error(f"Failed to read Zotero DB: {e}")
                    return []

        return []

    def _read_items(self, cutoff: datetime) -> list[RawItem]:
        conn = sqlite3.connect(
            f"file:{self.db_path}?immutable=1",
            uri=True,
            timeout=self.sqlite_timeout_seconds,
        )
        conn.row_factory = sqlite3.Row

        try:
            rows = conn.execute("""
                SELECT
                    i.key,
                    (SELECT idv.value
                     FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'title'
                    ) as title,
                    (SELECT idv.value
                     FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'abstractNote'
                    ) as abstract,
                    (SELECT idv.value
                     FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'url'
                    ) as url,
                    i.dateAdded,
                    (SELECT GROUP_CONCAT(t.name, '||')
                     FROM itemTags it JOIN tags t ON it.tagID = t.tagID
                     WHERE it.itemID = i.itemID
                    ) as tags,
                    (SELECT GROUP_CONCAT(c.collectionName, '||')
                     FROM collectionItems ci JOIN collections c ON ci.collectionID = c.collectionID
                     WHERE ci.itemID = i.itemID
                    ) as collections
                FROM items i
                WHERE i.dateAdded > ?
                  AND i.itemTypeID NOT IN (
                      SELECT itemTypeID FROM itemTypes
                      WHERE typeName IN ('attachment', 'note')
                  )
                  AND i.key IS NOT NULL
            """, (cutoff.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()

            items = []
            for row in rows:
                title = row["title"]
                if not title:
                    continue

                tags = row["tags"].split("||") if row["tags"] else []
                collections = row["collections"].split("||") if row["collections"] else []

                items.append(RawItem(
                    source="zotero",
                    title=title,
                    url=row["url"],
                    zotero_key=row["key"],
                    metadata={
                        "abstract": row["abstract"],
                        "tags": tags,
                        "collections": collections,
                        "date_added": row["dateAdded"],
                    },
                ))

            log.info(f"Zotero: collected {len(items)} items (lookback {self.lookback_days} days)")
            return items

        finally:
            conn.close()
