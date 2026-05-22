from __future__ import annotations

import pytest

from passive_agent.processors.normalizer import Normalizer
from passive_agent.processors.summarizer import Summarizer
from passive_agent.storage.models import Item, RawItem
from passive_agent.utils.config import GoalsConfig


def test_zotero_abstract_and_collections_survive_normalization(db):
    raw = RawItem(
        source="zotero",
        title="Agent Memory Paper",
        url="https://example.com/paper",
        zotero_key="ABC123",
        metadata={
            "abstract": "This paper studies long-term memory for tool-using agents.",
            "tags": ["Agent"],
            "collections": ["Papers", "RAG"],
            "date_added": "2026-05-22 10:00:00",
        },
    )

    item = Normalizer(db).normalize([raw])[0]

    assert item.raw_text == "This paper studies long-term memory for tool-using agents."
    assert item.extra_meta is not None
    assert item.extra_meta["abstract"] == raw.metadata["abstract"]
    assert item.extra_meta["collections"] == ["Papers", "RAG"]
    assert item.extra_meta["date_added"] == "2026-05-22 10:00:00"
    assert item.topics == ["Agent", "Papers", "RAG"]


@pytest.mark.asyncio
async def test_summarizer_renders_zotero_abstract_and_collections_in_prompt():
    llm = RecordingLLM()
    item = Item(
        id="item_20260522_001",
        source="zotero",
        title="Agent Memory Paper",
        raw_text="This paper studies long-term memory for tool-using agents.",
        topics=["Agent"],
        extra_meta={"collections": ["Papers", "RAG"]},
    )
    summarizer = Summarizer(
        llm,
        GoalsConfig(current_focus="test", priority_topics=["Agent"]),
        prompts_dir="prompts",
    )

    await summarizer._summarize_one(item)

    assert "摘要：This paper studies long-term memory for tool-using agents." in llm.user_prompt
    assert "分类：Papers, RAG" in llm.user_prompt


class RecordingLLM:
    def __init__(self):
        self.user_prompt = ""

    async def generate_json(self, system: str, user: str) -> dict:
        self.user_prompt = user
        return {
            "summary": "Agent memory paper",
            "interview_relevance": "How do agents persist memory?",
            "recommended_action": "read",
            "estimated_minutes": 15,
            "topics": ["Agent"],
            "content_type": "paper",
        }
