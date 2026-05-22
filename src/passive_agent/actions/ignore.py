from __future__ import annotations

from datetime import datetime

from passive_agent.actions.base import ActionResult
from passive_agent.storage.database import Database
from passive_agent.storage.models import FeedbackRecord
from passive_agent.utils.logger import log


class IgnoreAction:
    def __init__(self, db: Database):
        self.db = db

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        self.db.update_item_stage(item_id, "ignored")

        # 更新忽略计数
        item.ignored_count += 1
        self.db.conn.execute(
            "UPDATE items SET ignored_count = ? WHERE id = ?",
            (item.ignored_count, item_id),
        )
        self.db.conn.commit()

        # 记录反馈
        for topic in item.topics:
            self.db.save_feedback(FeedbackRecord(
                id=None,
                item_id=item_id,
                action="ignore",
                topic=topic,
                source=item.source,
                created_at=datetime.now(),
            ))

        log.info(f"Ignored: {item.title}")
        return ActionResult.ok(f"已忽略: {item.title}")
