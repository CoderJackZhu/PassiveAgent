import asyncio

import passive_agent.feishu.commands as commands_module
from passive_agent.feishu.commands import CommandHandler
from passive_agent.storage.models import Item
from passive_agent.utils.config import load_config


def test_pause_resume_commands_persist_state(db):
    handler = CommandHandler(db)

    pause_text = asyncio.run(handler.handle("暂停"))
    assert "已暂停" in pause_text
    assert db.is_paused() is True

    status_text = asyncio.run(handler.handle("状态"))
    assert "已暂停推送" in status_text

    resume_text = asyncio.run(handler.handle("恢复"))
    assert "已恢复" in resume_text
    assert db.is_paused() is False


def test_push_command_returns_cli_guidance(db):
    handler = CommandHandler(db)

    text = asyncio.run(handler.handle("推送"))

    assert text == "请使用 CLI 运行 passive-agent daily"


def test_push_command_runs_pipeline_when_context_provided(config_dir, db, monkeypatch):
    config = load_config(config_dir)
    llm = object()
    bot = object()
    calls = []

    class FakeResult:
        status = "success"
        collected = 4
        processed = 3
        recommended = [object(), object()]
        pushed = 2

    class FakePipeline:
        def __init__(self, pipeline_config, pipeline_db, pipeline_llm, *, feishu_bot):
            calls.append((pipeline_config, pipeline_db, pipeline_llm, feishu_bot))

        async def run(self):
            calls.append("run")
            return FakeResult()

    monkeypatch.setattr(commands_module, "DailyPipeline", FakePipeline)
    handler = CommandHandler(db, config, llm, bot)

    text = asyncio.run(handler.handle("推送"))

    assert calls == [(config, db, llm, bot), "run"]
    assert "collected 4" in text
    assert "processed 3" in text
    assert "recommended 2" in text
    assert "pushed 2" in text


def test_detail_command_returns_known_item(db):
    db.save_items([
        Item(
            id="item_detail",
            source="zotero",
            title="Agent Paper",
            url="https://example.com/paper",
            topics=["Agent"],
            stage="recommended",
            summary="Summary here.",
            interview_relevance="Good interview fit.",
            estimated_minutes=12,
            priority_score=88.5,
            recommended_action="card",
        ),
        Item(
            id="related_zotero",
            source="zotero",
            title="Related Zotero",
            topics=["Agent"],
            stage="archived",
        ),
        Item(
            id="related_star",
            source="github_star",
            title="Related Star",
            topics=["Agent"],
            extra_meta={"stars": 100},
        ),
    ])
    handler = CommandHandler(db)

    text = asyncio.run(handler.handle("详情 item_detail"))

    assert "Agent Paper" in text
    assert "zotero" in text
    assert "88.5" in text
    assert "Summary here." in text
    assert "Good interview fit." in text
    assert "Agent" in text
    assert "card" in text
    assert "12" in text
    assert "https://example.com/paper" in text
    assert "Related Star" in text
    assert "Related Zotero" in text
