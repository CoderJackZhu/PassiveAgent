from __future__ import annotations

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item
from passive_agent.utils.config import NegativeFeedbackConfig
from passive_agent.utils.logger import log


class FeedbackEngine:
    """滑动窗口负反馈权重计算"""

    def __init__(self, db: Database, config: NegativeFeedbackConfig):
        self.db = db
        self.config = config

    def update_on_ignore(self, item: Item):
        for topic in item.topics:
            self._update_topic_weight(topic)
        self._update_source_weight(item.source)

    def _update_topic_weight(self, topic: str):
        recent = self.db.get_recent_feedback_for_topic(topic, window=10)
        ignore_count = sum(1 for f in recent if f.action == "ignore")

        if ignore_count >= self.config.topic_threshold:
            current = self.db.get_topic_weight(topic)
            new_weight = max(
                current * (1 - self.config.topic_penalty),
                self.config.min_weight,
            )
            self.db.set_topic_weight(topic, new_weight)
            log.info(f"Topic '{topic}' weight: {current:.2f} → {new_weight:.2f} "
                     f"(ignored {ignore_count}/10)")

    def _update_source_weight(self, source: str):
        recent = self.db.get_recent_feedback_for_source(source, window=15)
        ignore_count = sum(1 for f in recent if f.action == "ignore")

        if ignore_count >= self.config.source_threshold:
            current = self.db.get_source_weight(source)
            new_weight = max(
                current * (1 - self.config.source_penalty),
                self.config.min_weight,
            )
            self.db.set_source_weight(source, new_weight)
            log.info(f"Source '{source}' weight: {current:.2f} → {new_weight:.2f} "
                     f"(ignored {ignore_count}/15)")

    def recover_weights(self):
        """每日调用：对超过 recovery_days 未更新的权重进行自然恢复"""
        self.db.recover_stale_weights(
            days=self.config.recovery_days,
            rate=self.config.recovery_rate,
        )
