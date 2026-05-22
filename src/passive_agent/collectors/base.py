from __future__ import annotations

from typing import Protocol

from passive_agent.storage.models import RawItem


class Collector(Protocol):
    """数据源收集器协议"""

    async def collect(self) -> list[RawItem]:
        ...

    def is_available(self) -> bool:
        ...
