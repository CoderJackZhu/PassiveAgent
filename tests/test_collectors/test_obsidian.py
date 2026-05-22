import asyncio

import pytest

from passive_agent.collectors.obsidian import ObsidianCollector


@pytest.fixture
def inbox_file(tmp_path):
    content = """## 2026-05-22
- [LangGraph 新文档](https://docs.langgraph.dev) #agent
- 微信看到一篇 Tool Calling 失败分析，搜"tool calling failure"能找到
- [RAGAS 评测](https://arxiv.org/abs/xxx) #rag #evaluation

## 2026-05-21
- 同事推荐的一个 workflow 框架，叫 Prefect
- [已处理的条目](https://example.com) ✓
"""
    inbox = tmp_path / "inbox.md"
    inbox.write_text(content, encoding="utf-8")
    return str(inbox)


def test_obsidian_collector_basic(inbox_file):
    collector = ObsidianCollector(inbox_path=inbox_file)
    assert collector.is_available()
    items = asyncio.run(collector.collect())

    assert len(items) == 4  # 5 条 - 1 条已处理 = 4 条

    # 有链接的条目
    langgraph = items[0]
    assert langgraph.title == "LangGraph 新文档"
    assert langgraph.url == "https://docs.langgraph.dev"
    assert "agent" in langgraph.metadata["tags"]

    # 无链接的条目
    tool_calling = items[1]
    assert "Tool Calling" in tool_calling.title
    assert tool_calling.url is None

    # raw_text 保留
    assert all(item.raw_text is not None for item in items)


def test_obsidian_collector_skips_done(inbox_file):
    collector = ObsidianCollector(inbox_path=inbox_file)
    items = asyncio.run(collector.collect())
    titles = [i.title for i in items]
    assert "已处理的条目" not in titles


def test_obsidian_collector_not_available(tmp_path):
    collector = ObsidianCollector(inbox_path=str(tmp_path / "nonexistent.md"))
    assert not collector.is_available()
    items = asyncio.run(collector.collect())
    assert items == []


def test_obsidian_collector_empty_file(tmp_path):
    inbox = tmp_path / "inbox.md"
    inbox.write_text("## 2026-05-22\n", encoding="utf-8")
    collector = ObsidianCollector(inbox_path=str(inbox))
    items = asyncio.run(collector.collect())
    assert items == []
