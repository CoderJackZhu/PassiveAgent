from datetime import datetime

import pytest

from passive_agent.processors.deduplicator import Deduplicator
from passive_agent.storage.models import Item


def test_dedup_by_url(db):
    # 先存一个已有条目
    existing = Item(
        id="item_20260521_001", source="zotero", title="Old Article",
        url="https://example.com/article", collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_item(existing)

    dedup = Deduplicator(db)
    new_items = [
        Item(
            id="item_20260522_001", source="obsidian_inbox", title="New but same URL",
            url="https://example.com/article", collected_at=datetime.now(), created_at=datetime.now(),
        ),
        Item(
            id="item_20260522_002", source="zotero", title="Unique Article",
            url="https://example.com/unique", collected_at=datetime.now(), created_at=datetime.now(),
        ),
    ]

    result = dedup.filter(new_items)
    assert len(result) == 1
    assert result[0].title == "Unique Article"


def test_dedup_by_title_fuzzy(db):
    existing = Item(
        id="item_20260521_001", source="zotero", title="LangGraph Checkpoint 机制详解",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_item(existing)

    dedup = Deduplicator(db)
    new_items = [
        Item(
            id="item_20260522_001", source="obsidian_inbox",
            title="LangGraph Checkpoint 机制详解",  # 完全相同
            collected_at=datetime.now(), created_at=datetime.now(),
        ),
        Item(
            id="item_20260522_002", source="obsidian_inbox",
            title="ReAct vs Plan-and-Execute",  # 不同
            collected_at=datetime.now(), created_at=datetime.now(),
        ),
    ]

    result = dedup.filter(new_items)
    assert len(result) == 1
    assert "ReAct" in result[0].title


def test_dedup_within_batch(db):
    dedup = Deduplicator(db)
    new_items = [
        Item(
            id="item_20260522_001", source="zotero", title="Same Article",
            url="https://a.com", collected_at=datetime.now(), created_at=datetime.now(),
        ),
        Item(
            id="item_20260522_002", source="obsidian_inbox", title="Same Article",
            url="https://a.com", collected_at=datetime.now(), created_at=datetime.now(),
        ),
    ]

    result = dedup.filter(new_items)
    assert len(result) == 1


def test_dedup_no_url_items(db):
    existing = Item(
        id="item_20260521_001", source="obsidian_inbox",
        title="微信看到一篇 Tool Calling 失败分析",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_item(existing)

    dedup = Deduplicator(db)
    new_items = [
        Item(
            id="item_20260522_001", source="obsidian_inbox",
            title="微信看到一篇 Tool Calling 失败分析，搜xxx能找到",  # 相似但不完全相同
            collected_at=datetime.now(), created_at=datetime.now(),
        ),
    ]

    result = dedup.filter(new_items)
    # 相似度 > 0.85，应该被去重
    assert len(result) == 0
