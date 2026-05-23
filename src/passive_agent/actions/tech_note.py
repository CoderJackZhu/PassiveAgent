from __future__ import annotations

from datetime import date

from jinja2 import Environment, FileSystemLoader

from passive_agent.actions.base import ActionResult
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.integrations.obsidian_writer import ObsidianWriter
from passive_agent.storage.database import Database
from passive_agent.utils.config import GoalsConfig
from passive_agent.utils.logger import log


class TechNoteAction:
    def __init__(self, db: Database, llm: DeepSeekClient, writer: ObsidianWriter,
                 goals: GoalsConfig, prompts_dir: str = "prompts"):
        self.db = db
        self.llm = llm
        self.writer = writer
        self.goals = goals
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))
        self.template = self.jinja.get_template("tech_note.md.j2")

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
            today=date.today().isoformat(),
        )

        note_content = await self.llm.generate(
            system="你是技术写作助手，生成结构化的技术笔记。直接输出 Markdown，不要包裹代码块。",
            user=prompt,
        )

        topic = item.topics[0] if item.topics else "General"
        output_path = self.writer.write_tech_note(topic, item.title, note_content)

        self.db.update_item_stage(item_id, "archived")

        if item.zotero_key:
            self.db.enqueue_zotero_write(item.zotero_key, "/done", remove_tag="/unread")

        if item.source == "obsidian_inbox" and item.raw_text:
            self.writer.mark_inbox_done(item.raw_text)

        log.info(f"Tech note generated: {output_path}")
        return ActionResult.ok(
            f"技术笔记已生成: {output_path.name}",
            output_path=str(output_path),
            content=note_content,
        )