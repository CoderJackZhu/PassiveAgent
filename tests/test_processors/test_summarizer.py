from __future__ import annotations

import pytest

from passive_agent.processors.summarizer import Summarizer
from passive_agent.storage.models import Item
from passive_agent.utils.config import GoalsConfig


VALID_SUMMARY = {
    "summary": "Agent memory overview",
    "interview_relevance": "How should an agent persist memory?",
    "recommended_action": "read",
    "estimated_minutes": 12,
    "topics": ["Agent", "Memory"],
    "content_type": "article",
}


class PayloadLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, system: str, user: str) -> dict:
        return self.payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {key: value for key, value in VALID_SUMMARY.items() if key != "summary"},
        {**VALID_SUMMARY, "summary": "   "},
        {**VALID_SUMMARY, "interview_relevance": []},
        {**VALID_SUMMARY, "recommended_action": "later"},
        {**VALID_SUMMARY, "estimated_minutes": True},
        {**VALID_SUMMARY, "estimated_minutes": 0},
        {**VALID_SUMMARY, "topics": ["Agent", 1]},
        {**VALID_SUMMARY, "topics": ["Agent", "  "]},
        {**VALID_SUMMARY, "topics": "Agent"},
        {**VALID_SUMMARY, "content_type": "video"},
    ],
    ids=[
        "empty-object",
        "missing-field",
        "empty-string",
        "wrong-string-type",
        "invalid-action",
        "bool-minutes",
        "non-positive-minutes",
        "wrong-topic-type",
        "blank-topic-entry",
        "topics-not-a-list",
        "invalid-content-type",
    ],
)
async def test_summarize_batch_rejects_malformed_objects_before_mutating_item(payload):
    item = Item(
        id="malformed-summary",
        source="zotero",
        title="Malformed summary",
        topics=["Original"],
    )
    summarizer = Summarizer(
        PayloadLLM(payload),
        GoalsConfig(priority_topics=["Agent"]),
        prompts_dir="prompts",
    )

    result = await summarizer.summarize_batch([item])

    assert result == []
    assert item.stage == "new"
    assert item.summary is None
    assert item.interview_relevance is None
    assert item.recommended_action is None
    assert item.estimated_minutes is None
    assert item.content_type is None
    assert item.topics == ["Original"]
    assert len(summarizer.errors) == 1


@pytest.mark.asyncio
async def test_summarize_batch_accepts_empty_topics_for_ignore_action():
    # M3 对与面试无关的内容返回 action=ignore + topics=[]，这是合法输出而非 malformed。
    payload = {**VALID_SUMMARY, "recommended_action": "ignore", "topics": []}
    item = Item(
        id="ignore-with-empty-topics",
        source="hf_daily_papers",
        title="Unrelated CV paper",
        topics=["Original"],
    )
    summarizer = Summarizer(
        PayloadLLM(payload),
        GoalsConfig(priority_topics=["Agent"]),
        prompts_dir="prompts",
    )

    result = await summarizer.summarize_batch([item])

    assert result == [item]
    assert item.stage == "summarized"
    assert item.recommended_action == "ignore"
    assert item.topics == []
    assert item.summary == VALID_SUMMARY["summary"]
    assert summarizer.errors == []
