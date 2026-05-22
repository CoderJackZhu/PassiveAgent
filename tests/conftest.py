import tempfile
from pathlib import Path

import pytest

from passive_agent.storage.database import Database
from passive_agent.utils.config import AppConfig, load_config


@pytest.fixture
def config_dir(tmp_path):
    goals = tmp_path / "goals.yaml"
    goals.write_text("""
current_focus: "test"
priority_topics:
  - Agent
  - RAG
low_priority_topics:
  - Frontend
output_preference: "interview_card"
""")

    sources = tmp_path / "sources.yaml"
    sources.write_text("""
zotero:
  enabled: false
  db_path: "/tmp/fake.sqlite"
  lookback_days: 7
obsidian:
  enabled: false
  inbox_path: "/tmp/fake_inbox.md"
  vault_path: "/tmp/fake_vault"
github_stars:
  enabled: false
""")

    scoring = tmp_path / "scoring.yaml"
    scoring.write_text("""
weights:
  goal_relevance: 0.30
  novelty: 0.20
  actionability: 0.20
  difficulty_fit: 0.10
  source_quality: 0.10
  timeliness: 0.10
daily_limit: 3
weekend_limit: 5
negative_feedback:
  topic_threshold: 3
  topic_penalty: 0.15
  source_threshold: 5
  source_penalty: 0.20
  min_weight: 0.30
  recovery_days: 30
  recovery_rate: 0.05
""")

    return str(tmp_path)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.initialize()
    yield database
    database.close()
