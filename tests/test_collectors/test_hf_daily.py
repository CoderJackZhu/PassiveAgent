from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from passive_agent.collectors.hf_daily import HFDailyPapersCollector


@pytest.mark.asyncio
async def test_hf_daily_collects_recent_papers_across_days():
    requests: list[httpx.Request] = []
    today = date.today()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=[
                {
                    "title": "Paper A",
                    "paper": {"id": "2401.00001", "title": "Paper A", "summary": "Summary A"},
                    "upvotes": 42,
                },
                {
                    "title": "Paper B",
                    "paper": {"id": "2401.00002", "title": "Paper B", "summary": "Summary B"},
                    "upvotes": 7,
                },
            ])

        return httpx.Response(200, json=[
            {
                "title": "Paper C",
                "paper": {"id": "2401.00003", "title": "Paper C", "summary": "Summary C"},
                "upvotes": 3,
            }
        ])

    collector = HFDailyPapersCollector(
        max_papers=3,
        transport=httpx.MockTransport(handler),
    )

    items = await collector.collect()

    assert collector.is_available() is True
    assert len(items) == 3
    assert requests[0].url.params["date"] == today.isoformat()
    assert requests[1].url.params["date"] == (today - timedelta(days=1)).isoformat()
    assert items[0].source == "hf_daily_papers"
    assert items[0].title == "Paper A"
    assert items[0].url == "https://huggingface.co/papers/2401.00001"
    assert items[0].raw_text == "Summary A"
    assert items[0].metadata["upvotes"] == 42
    assert items[0].metadata["paper_id"] == "2401.00001"


@pytest.mark.asyncio
async def test_hf_daily_deduplicates_papers_and_skips_bad_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {
                "title": "Paper A",
                "paper": {"id": "2401.00001", "title": "Paper A", "summary": "Summary A"},
                "upvotes": 42,
            },
            {
                "title": "Paper A Duplicate",
                "paper": {"id": "2401.00001", "title": "Paper A", "summary": "Summary A"},
                "upvotes": 42,
            },
            {
                "title": "Missing ID",
                "paper": {"title": "Missing ID", "summary": "No id"},
                "upvotes": 1,
            },
        ])

    collector = HFDailyPapersCollector(
        max_papers=5,
        days=1,
        transport=httpx.MockTransport(handler),
    )

    items = await collector.collect()

    assert [item.title for item in items] == ["Paper A"]
