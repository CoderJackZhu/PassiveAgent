from __future__ import annotations

from pathlib import Path


class ObsidianWriter:
    def __init__(self, vault_path: str):
        if not vault_path:
            raise ValueError("vault_path is required")
        self.vault = Path(vault_path).expanduser()
        self.vault.mkdir(parents=True, exist_ok=True)

    def write_interview_card(self, topic: str, title: str, content: str) -> Path:
        dir_path = self.vault / "01-Interview" / self._safe_dirname(topic)
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{self._safe_filename(title)}.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def write_tech_note(self, topic: str, title: str, content: str) -> Path:
        dir_path = self.vault / "03-Tech-Notes" / self._safe_dirname(topic)
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{self._safe_filename(title)}.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def mark_inbox_done(self, raw_text: str) -> bool:
        inbox_path = self.vault / "00-Inbox" / "inbox.md"
        if not inbox_path.exists():
            return False

        content = inbox_path.read_text(encoding="utf-8")
        target = raw_text.rstrip()

        if target not in content:
            return False

        if target + " ✓" in content:
            return True

        content = content.replace(target, target + " ✓", 1)
        inbox_path.write_text(content, encoding="utf-8")
        return True

    def _safe_dirname(self, name: str) -> str:
        return name.replace("/", "-").replace("\\", "-").replace(" ", "-").strip("-")

    def _safe_filename(self, title: str) -> str:
        safe = "".join(c for c in title if c.isalnum() or c in " -_（）()·：").strip()
        return safe[:80] if safe else "untitled"
