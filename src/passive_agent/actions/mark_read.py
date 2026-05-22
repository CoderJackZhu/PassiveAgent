from __future__ import annotations

from passive_agent.actions.base import ActionResult
from passive_agent.integrations.obsidian_writer import ObsidianWriter
from passive_agent.storage.database import Database
from passive_agent.utils.logger import log


class MarkReadAction:
    def __init__(self, db: Database, writer: ObsidianWriter):
        self.db = db
        self.writer = writer

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        self.db.update_item_stage(item_id, "archived")

        # Zotero tag 写回入队: /unread → /done
        if item.zotero_key:
            self.db.enqueue_zotero_write(item.zotero_key, "/done", remove_tag="/unread")

        # Obsidian inbox 标记
        if item.source == "obsidian_inbox" and item.raw_text:
            self.writer.mark_inbox_done(item.raw_text)

        log.info(f"Marked as read: {item.title}")
        return ActionResult.ok(f"已标记已读: {item.title}")
