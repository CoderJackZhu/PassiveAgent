from __future__ import annotations

from datetime import datetime

from passive_agent.actions.base import ActionResult
from passive_agent.processors.feedback_engine import FeedbackEngine
from passive_agent.storage.database import Database
from passive_agent.storage.models import FeedbackRecord
from passive_agent.utils.config import NegativeFeedbackConfig
from passive_agent.utils.logger import log


class IgnoreAction:
    def __init__(self, db: Database, feedback_config: NegativeFeedbackConfig | None = None):
        self.db = db
        self.feedback_engine = (
            FeedbackEngine(db, feedback_config) if feedback_config else None
        )

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        self.db.update_item_stage(item_id, "ignored")

        item.ignored_count += 1
        self.db.conn.execute(
            "UPDATE items SET ignored_count = ? WHERE id = ?",
            (item.ignored_count, item_id),
        )
        self.db.conn.commit()

        for topic in item.topics:
            self.db.save_feedback(FeedbackRecord(
                id=None,
                item_id=item_id,
                action="ignore",
                topic=topic,
                source=None,
                created_at=datetime.now(),
            ))
        self.db.save_feedback(FeedbackRecord(
            id=None,
            item_id=item_id,
            action="ignore",
            topic=None,
            source=item.source,
            created_at=datetime.now(),
        ))

        if self.feedback_engine:
            self.feedback_engine.update_on_ignore(item)

        log.info(f"Ignored: {item.title}")
        return ActionResult.ok(f"已忽略: {item.title}")
