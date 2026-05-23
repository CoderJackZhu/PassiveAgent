from pathlib import Path

from passive_agent.utils.config import load_config


def test_load_config(config_dir):
    config = load_config(config_dir)

    assert config.runtime.db_path == "data/workbench.db"
    assert config.db_path == "data/workbench.db"
    assert config.llm.provider == "deepseek"
    assert config.llm.api_key_env == "DEEPSEEK_API_KEY"
    assert config.recommendations.stale_after_days == 7
    assert config.display.dashboard_limit == 10
    assert config.feishu.async_timeout_seconds == 60.0
    assert config.goals.current_focus == "test"
    assert "Agent" in config.goals.priority_topics
    assert config.sources.zotero.enabled is False
    assert config.sources.zotero.sqlite_timeout_seconds == 30.0
    assert config.sources.hf_daily.enabled is False
    assert config.sources.hf_daily.max_papers == 30
    assert config.sources.hf_daily.lookback_days == 30
    assert config.scoring.weights.goal_relevance == 0.30
    assert config.scoring.daily_limit == 3
    assert config.scoring.negative_feedback.topic_threshold == 3
    assert config.scoring.negative_feedback.topic_window == 10


def test_load_config_explicit_runtime_knobs(tmp_path):
    Path(tmp_path / "config.yaml").write_text("""
runtime:
  db_path: "custom/workbench.db"
  reports_dir: "custom/reports"
  prompts_dir: "custom/prompts"
llm:
  provider: "deepseek"
  api_key_env: "CUSTOM_DEEPSEEK_KEY"
  base_url: "https://llm.example.test"
  model: "custom-model"
  temperature: 0.1
  max_concurrency: 2
  max_retries: 4
  retry_backoff_base_seconds: 1.5
recommendations:
  stale_after_days: 11
  related_zotero_limit: 1
  related_stars_limit: 2
display:
  dashboard_limit: 4
  feedback_summary_limit: 3
  recent_cards_limit: 2
  weekly_processed_limit: 6
  manual_push_limit: 7
feishu:
  async_timeout_seconds: 12.5
sources:
  zotero:
    sqlite_timeout_seconds: 8.0
    db_retries: 5
    db_retry_sleep_seconds: 0.25
    writeback_timeout_seconds: 9.0
    local_api_timeout_seconds: 1.0
  github_stars:
    max_pages: 6
    per_page: 50
    classification_batch_size: 4
    http_timeout_seconds: 13.0
  hf_daily:
    lookback_days: 9
    http_timeout_seconds: 14.0
scoring:
  negative_feedback:
    topic_window: 8
    source_window: 12
""", encoding="utf-8")

    config = load_config(str(tmp_path))

    assert config.runtime.db_path == "custom/workbench.db"
    assert config.db_path == "custom/workbench.db"
    assert config.runtime.reports_dir == "custom/reports"
    assert config.reports_dir == "custom/reports"
    assert config.prompts_dir == "custom/prompts"
    assert config.llm.api_key_env == "CUSTOM_DEEPSEEK_KEY"
    assert config.llm.base_url == "https://llm.example.test"
    assert config.llm.model == "custom-model"
    assert config.llm.temperature == 0.1
    assert config.llm.max_concurrency == 2
    assert config.llm.max_retries == 4
    assert config.llm.retry_backoff_base_seconds == 1.5
    assert config.recommendations.stale_after_days == 11
    assert config.recommendations.related_zotero_limit == 1
    assert config.recommendations.related_stars_limit == 2
    assert config.display.dashboard_limit == 4
    assert config.display.feedback_summary_limit == 3
    assert config.display.recent_cards_limit == 2
    assert config.display.weekly_processed_limit == 6
    assert config.display.manual_push_limit == 7
    assert config.feishu.async_timeout_seconds == 12.5
    assert config.sources.zotero.sqlite_timeout_seconds == 8.0
    assert config.sources.zotero.db_retries == 5
    assert config.sources.zotero.db_retry_sleep_seconds == 0.25
    assert config.sources.zotero.writeback_timeout_seconds == 9.0
    assert config.sources.zotero.local_api_timeout_seconds == 1.0
    assert config.sources.github_stars.max_pages == 6
    assert config.sources.github_stars.per_page == 50
    assert config.sources.github_stars.classification_batch_size == 4
    assert config.sources.github_stars.http_timeout_seconds == 13.0
    assert config.sources.hf_daily.lookback_days == 9
    assert config.sources.hf_daily.http_timeout_seconds == 14.0
    assert config.scoring.negative_feedback.topic_window == 8
    assert config.scoring.negative_feedback.source_window == 12


def test_load_config_missing_dir(tmp_path):
    config = load_config(str(tmp_path / "nonexistent"))
    assert config.goals.current_focus == ""
    assert config.scoring.daily_limit == 3


def test_load_config_uses_passive_agent_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "custom-config.yaml"
    config_path.write_text("""
goals:
  current_focus: "from explicit file"
runtime:
  db_path: "explicit-file.db"
""", encoding="utf-8")
    (tmp_path / ".env").write_text("FEISHU_CHAT_ID=from_explicit_file\n", encoding="utf-8")
    monkeypatch.delenv("FEISHU_CHAT_ID", raising=False)
    monkeypatch.setenv("PASSIVE_AGENT_CONFIG", str(config_path))

    config = load_config(str(tmp_path / "ignored"))

    import os

    assert config.goals.current_focus == "from explicit file"
    assert config.db_path == "explicit-file.db"
    assert config.project_root == str(tmp_path.resolve())
    assert os.environ["FEISHU_CHAT_ID"] == "from_explicit_file"


def test_load_config_uses_passive_agent_config_directory(tmp_path, monkeypatch):
    config_dir = tmp_path / "custom-dir"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("""
runtime:
  db_path: "explicit-dir.db"
""", encoding="utf-8")
    monkeypatch.setenv("PASSIVE_AGENT_CONFIG", str(config_dir))

    config = load_config(str(tmp_path / "ignored"))

    assert config.db_path == "explicit-dir.db"
    assert config.project_root == str(config_dir.resolve())


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
