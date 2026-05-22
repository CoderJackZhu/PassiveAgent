from dataclasses import dataclass, field
import os
from pathlib import Path

import yaml


@dataclass
class ScoringWeights:
    goal_relevance: float = 0.30
    novelty: float = 0.20
    actionability: float = 0.20
    difficulty_fit: float = 0.10
    source_quality: float = 0.10
    timeliness: float = 0.10


@dataclass
class NegativeFeedbackConfig:
    topic_threshold: int = 3
    topic_penalty: float = 0.15
    source_threshold: int = 5
    source_penalty: float = 0.20
    min_weight: float = 0.30
    recovery_days: int = 30
    recovery_rate: float = 0.05


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    daily_limit: int = 3
    weekend_limit: int = 5
    negative_feedback: NegativeFeedbackConfig = field(default_factory=NegativeFeedbackConfig)


@dataclass
class ZoteroSourceConfig:
    enabled: bool = True
    db_path: str = "~/Zotero/zotero.sqlite"
    lookback_days: int = 7
    high_priority_collections: list[str] = field(default_factory=list)
    writeback_enabled: bool = False


@dataclass
class ObsidianSourceConfig:
    enabled: bool = True
    inbox_path: str = "~/ObsidianVault/00-Inbox/inbox.md"
    vault_path: str = "~/ObsidianVault"
    read_paths: list[str] = field(default_factory=list)


@dataclass
class GitHubStarsConfig:
    enabled: bool = False


@dataclass
class SourcesConfig:
    zotero: ZoteroSourceConfig = field(default_factory=ZoteroSourceConfig)
    obsidian: ObsidianSourceConfig = field(default_factory=ObsidianSourceConfig)
    github_stars: GitHubStarsConfig = field(default_factory=GitHubStarsConfig)


@dataclass
class GoalsConfig:
    current_focus: str = ""
    priority_topics: list[str] = field(default_factory=list)
    low_priority_topics: list[str] = field(default_factory=list)
    output_preference: str = "interview_card"


@dataclass
class AppConfig:
    goals: GoalsConfig
    sources: SourcesConfig
    scoring: ScoringConfig
    db_path: str = "data/workbench.db"
    reports_dir: str = "data/reports"
    prompts_dir: str = "prompts"
    project_root: str = ""


def load_config(config_dir: str = "config") -> AppConfig:
    config_path = Path(config_dir)
    unified = _load_yaml(config_path / "config.yaml")
    project_root = config_path.resolve()
    if not unified:
        unified = _load_yaml(config_path.parent / "config.yaml")
        project_root = config_path.parent.resolve()
    if not unified:
        unified = {}

    _load_env_file(project_root / ".env")

    goals_data = unified.get("goals", {})
    sources_data = unified.get("sources", {})
    scoring_data = unified.get("scoring", {})

    goals = GoalsConfig(
        current_focus=goals_data.get("current_focus", ""),
        priority_topics=goals_data.get("priority_topics", []),
        low_priority_topics=goals_data.get("low_priority_topics", []),
        output_preference=goals_data.get("output_preference", "interview_card"),
    )

    zotero_raw = sources_data.get("zotero", {})
    obsidian_raw = sources_data.get("obsidian", {})
    github_raw = sources_data.get("github_stars", {})
    default_obsidian = ObsidianSourceConfig()

    sources = SourcesConfig(
        zotero=ZoteroSourceConfig(
            enabled=zotero_raw.get("enabled", True),
            db_path=zotero_raw.get("db_path", "~/Zotero/zotero.sqlite"),
            lookback_days=zotero_raw.get("lookback_days", 7),
            high_priority_collections=zotero_raw.get("high_priority_collections", []),
            writeback_enabled=zotero_raw.get("writeback_enabled", False),
        ),
        obsidian=ObsidianSourceConfig(
            enabled=obsidian_raw.get("enabled", True),
            inbox_path=obsidian_raw.get("inbox_path") or default_obsidian.inbox_path,
            vault_path=obsidian_raw.get("vault_path") or default_obsidian.vault_path,
            read_paths=_as_list(obsidian_raw.get("read_paths", obsidian_raw.get("read_path", []))),
        ),
        github_stars=GitHubStarsConfig(
            enabled=github_raw.get("enabled", False),
        ),
    )

    weights_raw = scoring_data.get("weights", {})
    feedback_raw = scoring_data.get("negative_feedback", {})

    scoring = ScoringConfig(
        weights=ScoringWeights(**weights_raw),
        daily_limit=scoring_data.get("daily_limit", 3),
        weekend_limit=scoring_data.get("weekend_limit", 5),
        negative_feedback=NegativeFeedbackConfig(**feedback_raw),
    )

    return AppConfig(goals=goals, sources=sources, scoring=scoring,
                     project_root=str(project_root))


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _as_list(val) -> list[str]:
    if isinstance(val, str):
        return [val] if val else []
    return val or []


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if "#" in value and not value.startswith(("'", '"')):
            value = value.split("#", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        os.environ[key] = value
