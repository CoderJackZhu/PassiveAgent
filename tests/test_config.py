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
