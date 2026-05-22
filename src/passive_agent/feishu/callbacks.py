from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from passive_agent.actions.ignore import IgnoreAction
from passive_agent.actions.interview_card import InterviewCardAction
from passive_agent.actions.mark_read import MarkReadAction
from passive_agent.actions.tech_note import TechNoteAction
from passive_agent.feishu.cards import CardBuilder
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.integrations.obsidian_writer import ObsidianWriter
from passive_agent.storage.database import Database
from passive_agent.utils.config import AppConfig
from passive_agent.utils.logger import log


class CallbackHandler:
    """处理飞书卡片按钮回调"""

    def __init__(self, config: AppConfig, db: Database, llm: DeepSeekClient):
        self.config = config
        self.db = db
        self.llm = llm
        self.writer = ObsidianWriter(config.sources.obsidian.vault_path)
        self.jinja = Environment(loader=FileSystemLoader(config.prompts_dir))

    async def handle(self, action_value: dict) -> dict | None:
        action = action_value.get("action")
        item_id = action_value.get("item_id")

        if not action or not item_id:
            log.warning(f"Invalid callback value: {action_value}")
            return None

        log.info(f"Callback: action={action}, item_id={item_id}")

        if action == "expand":
            return await self._handle_expand(item_id)
        elif action == "card":
            return await self._handle_card(item_id)
        elif action == "note":
            return await self._handle_note(item_id)
        elif action == "ignore":
            return await self._handle_ignore(item_id)
        elif action == "weekend":
            return await self._handle_weekend(item_id)
        elif action == "read":
            return await self._handle_read(item_id)
        elif action == "link":
            return await self._handle_link(item_id)
        elif action == "mute":
            return await self._handle_mute(item_id)
        else:
            log.warning(f"Unknown action: {action}")
            return None

    async def _handle_expand(self, item_id: str) -> dict | None:
        item = self.db.get_item(item_id)
        if not item:
            return None

        prompt = (
            f"请为以下内容生成 500-800 字的详细摘要，侧重技术核心和面试价值。\n\n"
            f"标题：{item.title}\n"
            f"来源：{item.source}\n"
            f"简要摘要：{item.summary or ''}\n"
            f"面试关联：{item.interview_relevance or ''}\n"
            f"{'链接：' + item.url if item.url else ''}"
        )

        detail = await self.llm.generate(
            system="你是面试准备助手，生成详细的内容分析。使用中文。",
            user=prompt,
        )

        card = CardBuilder.build_expand_card(item, detail)
        return {"type": "new_message", "card": card}

    async def _handle_card(self, item_id: str) -> dict | None:
        handler = InterviewCardAction(self.db, self.llm, self.writer, self.config.goals)
        result = await handler.execute(item_id)

        if result.success:
            card = CardBuilder.build_result_card(
                "✓ 面试卡已生成",
                f"**{self.db.get_item(item_id).title if self.db.get_item(item_id) else item_id}**\n\n"
                f"路径：`{result.output_path}`",
            )
        else:
            card = CardBuilder.build_result_card("✗ 生成失败", result.message, success=False)

        return {"type": "new_message", "card": card}

    async def _handle_note(self, item_id: str) -> dict | None:
        handler = TechNoteAction(self.db, self.llm, self.writer, self.config.goals)
        result = await handler.execute(item_id)

        if result.success:
            card = CardBuilder.build_result_card(
                "✓ 技术笔记已生成",
                f"路径：`{result.output_path}`",
            )
        else:
            card = CardBuilder.build_result_card("✗ 生成失败", result.message, success=False)

        return {"type": "new_message", "card": card}

    async def _handle_ignore(self, item_id: str) -> dict | None:
        handler = IgnoreAction(self.db, self.config.scoring.negative_feedback)
        result = await handler.execute(item_id)
        return {"type": "toast", "text": result.message}

    async def _handle_weekend(self, item_id: str) -> dict | None:
        item = self.db.get_item(item_id)
        if not item:
            return None

        self.db.conn.execute(
            "UPDATE items SET is_weekend = 1 WHERE id = ?", (item_id,)
        )
        self.db.conn.commit()
        log.info(f"Added to weekend queue: {item.title}")
        return {"type": "toast", "text": f"已加入周末队列: {item.title[:20]}"}

    async def _handle_read(self, item_id: str) -> dict | None:
        handler = MarkReadAction(self.db, self.writer)
        result = await handler.execute(item_id)
        return {"type": "toast", "text": result.message}

    async def _handle_link(self, item_id: str) -> dict | None:
        from passive_agent.actions.link_notes import LinkNotesAction
        handler = LinkNotesAction(self.db, self.writer, self.config.sources.obsidian.read_paths)
        result = await handler.execute(item_id)
        if result.success and "未找到" not in result.message:
            card = CardBuilder.build_result_card("关联笔记", result.message)
            return {"type": "new_message", "card": card}
        return {"type": "toast", "text": result.message}

    async def _handle_mute(self, item_id: str) -> dict | None:
        from passive_agent.actions.mute_similar import MuteSimilarAction
        handler = MuteSimilarAction(self.db, self.config.scoring.negative_feedback)
        result = await handler.execute(item_id)
        return {"type": "toast", "text": result.message}
