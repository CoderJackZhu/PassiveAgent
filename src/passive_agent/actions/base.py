from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ActionResult:
    success: bool
    message: str
    output_path: str | None = None
    content: str | None = None

    @classmethod
    def ok(cls, message: str, output_path: str | None = None, content: str | None = None) -> ActionResult:
        return cls(success=True, message=message, output_path=output_path, content=content)

    @classmethod
    def error(cls, message: str) -> ActionResult:
        return cls(success=False, message=message)


class Action(Protocol):
    async def execute(self, item_id: str) -> ActionResult:
        ...
