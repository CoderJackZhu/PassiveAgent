from __future__ import annotations

from pathlib import Path

from passive_agent.actions.base import ActionResult
from passive_agent.integrations.obsidian_writer import ObsidianWriter
from passive_agent.storage.database import Database
from passive_agent.utils.logger import log


class LinkNotesAction:
    """搜索 Obsidian vault 中与当前 item 相关的已有笔记"""

    def __init__(self, db: Database, writer: ObsidianWriter):
        self.db = db
        self.vault = writer.vault

    async def execute(self, item_id: str) -> ActionResult:
        item = self.db.get_item(item_id)
        if item is None:
            return ActionResult.error(f"Item not found: {item_id}")

        keywords = self._extract_keywords(item)
        if not keywords:
            return ActionResult.error("No keywords to search")

        matches = self._search_vault(keywords)

        if not matches:
            return ActionResult.ok(f"未找到与「{item.title[:30]}」相关的笔记")

        lines = [f"与「{item.title[:30]}」相关的笔记："]
        for path, score in matches[:5]:
            rel = path.relative_to(self.vault)
            lines.append(f"  · {rel} (匹配 {score} 个关键词)")

        message = "\n".join(lines)
        log.info(message)
        return ActionResult.ok(message)

    def _extract_keywords(self, item) -> list[str]:
        keywords = list(item.topics) if item.topics else []
        title_words = [w for w in item.title.split() if len(w) > 2]
        keywords.extend(title_words[:5])
        return keywords

    def _search_vault(self, keywords: list[str]) -> list[tuple[Path, int]]:
        results: list[tuple[Path, int]] = []
        search_dirs = ["01-Interview", "03-Tech-Notes", "03-Source-Notes"]

        for dir_name in search_dirs:
            search_path = self.vault / dir_name
            if not search_path.exists():
                continue
            for md_file in search_path.rglob("*.md"):
                score = self._match_score(md_file, keywords)
                if score > 0:
                    results.append((md_file, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _match_score(self, file_path: Path, keywords: list[str]) -> int:
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0

        content_lower = content.lower()
        filename_lower = file_path.stem.lower()
        score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in filename_lower:
                score += 2
            elif kw_lower in content_lower:
                score += 1
        return score
