from __future__ import annotations

from datetime import date

from jinja2 import Environment, FileSystemLoader

from passive_agent.actions.base import ActionResult
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.integrations.obsidian_writer import ObsidianWriter
from passive_agent.storage.database import Database
from passive_agent.utils.config import GoalsConfig
from passive_agent.utils.logger import log


class InterviewCardAction:
    def __init__(self, db: Database, llm: DeepSeekClient, writer: ObsidianWriter,
                 goals: GoalsConfig, prompts_dir: str = "prompts"):
        self.db = db
        self.llm = llm
        self.writer = writer
        self.goals = goals
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))
        self.template = self.jinja.get_template("interview_card.md.j2")

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        prompt = self.template.render(
            title=item.title,
            source=item.source,
            summary=item.summary or "",
            interview_relevance=item.interview_relevance or "",
            url=item.url or "",
            topics=", ".join(item.topics) if item.topics else "General",
            priority_topics=self.goals.priority_topics,
            today=date.today().isoformat(),
        )

        card_content = await self.llm.generate(
            system="你是面试准备助手，生成高质量的面试问答卡片。直接输出 Markdown，不要包裹代码块。",
            user=prompt,
        )

        topic = item.topics[0] if item.topics else "General"
        output_path = self.writer.write_interview_card(topic, item.title, card_content)

        self.db.update_item_stage(item_id, "archived")

        if item.zotero_key:
            self.db.enqueue_zotero_write(item.zotero_key, "/done", remove_tag="/unread")

        # 标记 inbox 已处理
        if item.source == "obsidian_inbox" and item.raw_text:
            self.writer.mark_inbox_done(item.raw_text)

        log.info(f"Interview card generated: {output_path}")
        return ActionResult.ok(
            f"面试卡已生成: {output_path.name}",
            output_path=str(output_path),
            content=card_content,
        )