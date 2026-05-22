from __future__ import annotations

from datetime import datetime

from passive_agent.actions.base import ActionResult
from passive_agent.processors.feedback_engine import FeedbackEngine
from passive_agent.storage.database import Database
from passive_agent.storage.models import FeedbackRecord
from passive_agent.utils.config import NegativeFeedbackConfig
from passive_agent.utils.logger import log


class MuteSimilarAction:
    """少推类似内容 — 不归档 item，仅对 topic/source 施加强负反馈"""

    def __init__(self, db: Database, feedback_config: NegativeFeedbackConfig):
        self.db = db
        self.feedback_engine = FeedbackEngine(db, feedback_config)

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        for topic in item.topics:
            self.db.save_feedback(FeedbackRecord(
                id=None,
                item_id=item_id,
                action="mute",
                topic=topic,
                source=item.source,
                created_at=datetime.now(),
            ))
            # Directly apply double penalty (stronger than ignore)
            current = self.db.get_topic_weight(topic)
            new_weight = max(current * 0.7, self.feedback_engine.config.min_weight)
            self.db.set_topic_weight(topic, new_weight)
            log.info(f"Muted topic '{topic}': {current:.2f} → {new_weight:.2f}")

        topics_text = ", ".join(item.topics[:3]) if item.topics else item.source
        log.info(f"Mute similar: {item.title} (topics: {topics_text})")
        return ActionResult.ok(f"已降低「{topics_text}」类内容推送权重")
