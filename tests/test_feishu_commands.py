import asyncio

from passive_agent.feishu.commands import CommandHandler


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
