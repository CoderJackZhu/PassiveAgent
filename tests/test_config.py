from passive_agent.utils.config import load_config


def test_load_config(config_dir):
    config = load_config(config_dir)

    assert config.goals.current_focus == "test"
    assert "Agent" in config.goals.priority_topics
    assert config.sources.zotero.enabled is False
    assert config.scoring.weights.goal_relevance == 0.30
    assert config.scoring.daily_limit == 3
    assert config.scoring.negative_feedback.topic_threshold == 3


def test_load_config_missing_dir(tmp_path):
    config = load_config(str(tmp_path / "nonexistent"))
    assert config.goals.current_focus == ""
    assert config.scoring.daily_limit == 3


def test_load_config_loads_dotenv(config_dir, monkeypatch):
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)

    from pathlib import Path

    env_path = Path(config_dir) / ".env"
    env_path.write_text('FEISHU_CHAT_ID="chat_123"\n', encoding="utf-8")

    load_config(config_dir)

    import os

    assert os.environ["FEISHU_CHAT_ID"] == "chat_123"


def test_load_config_does_not_override_exported_env(config_dir, monkeypatch):
    monkeypatch.setenv("FEISHU_CHAT_ID", "exported")

    from pathlib import Path

    env_path = Path(config_dir) / ".env"
    env_path.write_text("FEISHU_CHAT_ID=from_file\n", encoding="utf-8")

    load_config(config_dir)

    import os

    assert os.environ["FEISHU_CHAT_ID"] == "exported"
