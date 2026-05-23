from __future__ import annotations

from datetime import date, timedelta

import httpx

from passive_agent.collectors.base import Collector
from passive_agent.storage.models import RawItem
from passive_agent.utils.logger import log


HF_DAILY_PAPERS_API = "https://huggingface.co/api/daily_papers"
HF_PAPER_URL = "https://huggingface.co/papers/{paper_id}"


class HFDailyPapersCollector(Collector):
    def __init__(
        self,
        max_papers: int = 30,
        days: int = 30,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.max_papers = max(0, max_papers)
        self.days = max(1, days)
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.transport = transport

    def is_available(self) -> bool:
        return True

    async def collect(self) -> list[RawItem]:
        if self.max_papers == 0:
            return []

        today = date.today()
        items: list[RawItem] = []
        seen_paper_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            for offset in range(self.days):
                paper_date = today - timedelta(days=offset)
                entries = await self._fetch_day(client, paper_date)

                for entry in entries:
                    item = self._entry_to_raw_item(entry, paper_date)
                    if item is None:
                        continue

                    paper_id = item.metadata["paper_id"]
                    if paper_id in seen_paper_ids:
                        continue

                    seen_paper_ids.add(paper_id)
                    items.append(item)
                    if len(items) >= self.max_papers:
                        log.info(f"HF Daily Papers: collected {len(items)} items")
                        return items

        log.info(f"HF Daily Papers: collected {len(items)} items")
        return items

    async def _fetch_day(self, client: httpx.AsyncClient, paper_date: date) -> list[dict]:
        try:
            response = await client.get(
                HF_DAILY_PAPERS_API,
                params={"date": paper_date.isoformat()},
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return _extract_entries(response.json())
        except (httpx.HTTPError, ValueError) as e:
            log.warning(f"HF Daily Papers fetch failed for {paper_date.isoformat()}: {e}")
            return []

    def _entry_to_raw_item(self, entry: dict, paper_date: date) -> RawItem | None:
        paper = entry.get("paper") or {}
        paper_id = paper.get("id") or entry.get("paper_id") or entry.get("id")
        title = entry.get("title") or paper.get("title")
        if not paper_id or not title:
            return None

        summary = paper.get("summary") or entry.get("summary") or ""
        upvotes = _as_int(entry.get("upvotes", entry.get("upvotes_count", 0)))

        return RawItem(
            source="hf_daily_papers",
            title=title,
            url=HF_PAPER_URL.format(paper_id=paper_id),
            raw_text=summary,
            metadata={
                "upvotes": upvotes,
                "paper_id": paper_id,
                "daily_date": paper_date.isoformat(),
            },
        )


def _extract_entries(data) -> list[dict]:
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]

    if isinstance(data, dict):
        for key in ("dailyPapers", "papers", "data"):
            entries = data.get(key)
            if isinstance(entries, list):
                return [entry for entry in entries if isinstance(entry, dict)]

    return []


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
