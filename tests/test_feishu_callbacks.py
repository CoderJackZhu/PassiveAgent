import asyncio

from passive_agent.feishu.callbacks import CallbackHandler


def test_callback_card_requires_llm(config_dir, db):
    from passive_agent.utils.config import load_config

    config = load_config(config_dir)
    handler = CallbackHandler(config, db, llm=None)

    result = asyncio.run(handler.handle({"action": "card", "item_id": "missing"}))

    assert result == {"type": "toast", "text": "LLM 未配置，无法生成面试卡"}
