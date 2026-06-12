import asyncio
from datetime import datetime, timedelta
from typing import Any, cast

from passive_agent.feishu.callbacks import CallbackHandler
from passive_agent.storage.models import Item


class FailingLLM:
    async def generate(self, system: str, user: str) -> str:
        raise TimeoutError("upstream too slow")


def test_callback_card_requires_llm(config_dir, db):
    from passive_agent.utils.config import load_config

    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=None)

    result = asyncio.run(handler.handle({"action": "card", "item_id": "missing"}))

    assert result == {"type": "toast", "text": "LLM 未配置，无法生成面试卡"}
    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"]) for event in events] == [
        ("missing", "generate_card")
    ]


def test_callback_records_read_event_after_success(config_dir, db):
    from passive_agent.utils.config import load_config

    db.save_item(Item(id="read-item", source="zotero", title="Read Item"))
    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=None)

    result = asyncio.run(handler.handle({"action": "read", "item_id": "read-item"}))

    assert result["type"] == "toast"
    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"]) for event in events] == [
        ("read-item", "read")
    ]


def test_callback_records_weekend_event_after_success(config_dir, db):
    from passive_agent.utils.config import load_config

    db.save_item(Item(id="weekend-item", source="zotero", title="Weekend Item"))
    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=None)

    result = asyncio.run(handler.handle({"action": "weekend", "item_id": "weekend-item"}))

    assert result["type"] == "toast"
    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"]) for event in events] == [
        ("weekend-item", "weekend")
    ]


def test_callback_expand_falls_back_to_local_card_when_llm_times_out(config_dir, db):
    from passive_agent.utils.config import load_config

    db.save_item(
        Item(
            id="slow-expand",
            source="hf_daily_papers",
            title="Slow Expand Paper",
            url="https://example.test/paper",
            topics=["Agent"],
            summary="已有短摘要",
            interview_relevance="面试相关点",
        )
    )
    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=cast(Any, FailingLLM()))

    result = asyncio.run(handler.handle({"action": "expand", "item_id": "slow-expand"}))

    assert result is not None
    assert result["type"] == "new_message"
    card_json = str(result["card"])
    assert "LLM 展开暂时不可用" in card_json
    assert "已有短摘要" in card_json
    assert "https://example.test/paper" in card_json


def test_callback_records_failed_known_click_once(config_dir, db, monkeypatch):
    from passive_agent.actions.mark_read import MarkReadAction
    from passive_agent.actions.base import ActionResult
    from passive_agent.utils.config import load_config

    async def fail_read(self, item_id):
        return ActionResult(success=False, message="read failed")

    monkeypatch.setattr(MarkReadAction, "execute", fail_read)
    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=None)

    result = asyncio.run(handler.handle({"action": "read", "item_id": "failed-read"}))

    assert result == {"type": "toast", "text": "read failed"}
    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"]) for event in events] == [
        ("failed-read", "read")
    ]
