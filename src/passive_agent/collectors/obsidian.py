from __future__ import annotations

import re
from pathlib import Path

from passive_agent.storage.models import RawItem
from passive_agent.utils.logger import log


class ObsidianCollector:
    def __init__(self, inbox_path: str):
        self.inbox_path = Path(inbox_path).expanduser() if inbox_path else None

    def is_available(self) -> bool:
        return self._ensure_inbox_file()

    async def collect(self) -> list[RawItem]:
        if not self.is_available():
            log.warning(f"Obsidian inbox not available: {self.inbox_path}")
            return []

        assert self.inbox_path is not None
        content = self.inbox_path.read_text(encoding="utf-8")
        items = []

        for line in content.splitlines():
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("- "):
                continue

            text = stripped[2:].strip()

            if text.startswith("✓") or text.startswith("[x]") or text.endswith("✓"):
                continue
            raw_line = line  # 保留原始行（含缩进）用于后续标记

            link_match = re.search(r'\[([^\]]+)\]\(([^)]+)\)', text)
            url = link_match.group(2) if link_match else None
            title = link_match.group(1) if link_match else text

            # 清理 title 中的 tag
            title = re.sub(r'#\w+', '', title).strip()
            if not title:
                title = text

            tags = re.findall(r'#(\w+)', text)

            items.append(RawItem(
                source="obsidian_inbox",
                title=title,
                url=url,
                raw_text=stripped,
                metadata={"tags": tags, "full_text": text},
            ))

        log.info(f"Obsidian inbox: collected {len(items)} items")
        return items

    def _ensure_inbox_file(self) -> bool:
        if self.inbox_path is None:
            log.warning("Obsidian inbox_path is empty")
            return False

        if self.inbox_path.exists():
            if self.inbox_path.is_file():
                return True
            log.warning(f"Obsidian inbox path is not a file: {self.inbox_path}")
            return False

        self.inbox_path.parent.mkdir(parents=True, exist_ok=True)
        self.inbox_path.touch()
        log.info(f"Created Obsidian inbox file: {self.inbox_path}")
        return True
