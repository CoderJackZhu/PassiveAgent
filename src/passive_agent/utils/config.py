from dataclasses import dataclass, field
import os
from pathlib import Path

import yaml

from passive_agent.utils.logger import log


@dataclass
class RuntimeConfig:
    db_path: str = "data/workbench.db"
    reports_dir: str = "data/reports"
    prompts_dir: str = "prompts"


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    temperature: float = 0.3
    max_concurrency: int = 5
    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0


@dataclass
class RecommendationConfig:
    stale_after_days: int = 7
    related_zotero_limit: int = 3
    related_stars_limit: int = 3


@dataclass
class DisplayConfig:
    dashboard_limit: int = 10
    feedback_summary_limit: int = 5
    recent_cards_limit: int = 5
    weekly_processed_limit: int = 10
    manual_push_limit: int = 5


@dataclass
class FeishuConfig:
    async_timeout_seconds: float = 60.0


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
    topic_window: int = 10
    source_threshold: int = 5
    source_penalty: float = 0.20
    source_window: int = 15
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
    lookback_days: int = 365
    high_priority_collections: list[str] = field(default_factory=list)
    writeback_enabled: bool = False
    sqlite_timeout_seconds: float = 30.0
    db_retries: int = 3
    db_retry_sleep_seconds: float = 5.0
    writeback_timeout_seconds: float = 15.0
    local_api_timeout_seconds: float = 3.0


@dataclass
class ObsidianSourceConfig:
    enabled: bool = True
    inbox_path: str = "~/ObsidianVault/00-Inbox/inbox.md"
    vault_path: str = "~/ObsidianVault"
    read_paths: list[str] = field(default_factory=list)


@dataclass
class GitHubStarsConfig:
    enabled: bool = False
    max_pages: int = 10
    per_page: int = 100
    classification_batch_size: int = 10
    http_timeout_seconds: float = 30.0


@dataclass
class HFDailyConfig:
    enabled: bool = True
    max_papers: int = 30
    lookback_days: int = 30
    http_timeout_seconds: float = 30.0


@dataclass
class SourcesConfig:
    zotero: ZoteroSourceConfig = field(default_factory=ZoteroSourceConfig)
    obsidian: ObsidianSourceConfig = field(default_factory=ObsidianSourceConfig)
    github_stars: GitHubStarsConfig = field(default_factory=GitHubStarsConfig)
    hf_daily: HFDailyConfig = field(default_factory=HFDailyConfig)


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
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    recommendations: RecommendationConfig = field(default_factory=RecommendationConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    db_path: str = "data/workbench.db"
    reports_dir: str = "data/reports"
    prompts_dir: str = "prompts"
    project_root: str = ""


def load_config(config_dir: str = "config") -> AppConfig:
    explicit_config = os.environ.get("PASSIVE_AGENT_CONFIG")
    if explicit_config:
        config_file, project_root = _resolve_explicit_config(explicit_config)
        unified = _load_yaml(config_file)
    else:
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
    runtime_data = unified.get("runtime", {})
    llm_data = unified.get("llm", {})
    recommendations_data = unified.get("recommendations", {})
    display_data = unified.get("display", {})
    feishu_data = unified.get("feishu", {})

    goals = GoalsConfig(
        current_focus=goals_data.get("current_focus", ""),
        priority_topics=goals_data.get("priority_topics", []),
        low_priority_topics=goals_data.get("low_priority_topics", []),
        output_preference=goals_data.get("output_preference", "interview_card"),
    )

    zotero_raw = sources_data.get("zotero", {})
    obsidian_raw = sources_data.get("obsidian", {})
    github_raw = sources_data.get("github_stars", {})
    hf_daily_raw = sources_data.get("hf_daily", {})
    default_obsidian = ObsidianSourceConfig()

    sources = SourcesConfig(
        zotero=ZoteroSourceConfig(
            enabled=zotero_raw.get("enabled", True),
            db_path=zotero_raw.get("db_path", "~/Zotero/zotero.sqlite"),
            lookback_days=zotero_raw.get("lookback_days", 365),
            high_priority_collections=zotero_raw.get("high_priority_collections", []),
            writeback_enabled=zotero_raw.get("writeback_enabled", False),
            sqlite_timeout_seconds=zotero_raw.get("sqlite_timeout_seconds", 30.0),
            db_retries=zotero_raw.get("db_retries", 3),
            db_retry_sleep_seconds=zotero_raw.get("db_retry_sleep_seconds", 5.0),
            writeback_timeout_seconds=zotero_raw.get("writeback_timeout_seconds", 15.0),
            local_api_timeout_seconds=zotero_raw.get("local_api_timeout_seconds", 3.0),
        ),
        obsidian=ObsidianSourceConfig(
            enabled=obsidian_raw.get("enabled", True),
            inbox_path=obsidian_raw.get("inbox_path") or default_obsidian.inbox_path,
            vault_path=obsidian_raw.get("vault_path") or default_obsidian.vault_path,
            read_paths=_as_list(obsidian_raw.get("read_paths", obsidian_raw.get("read_path", []))),
        ),
        github_stars=GitHubStarsConfig(
            enabled=github_raw.get("enabled", False),
            max_pages=github_raw.get("max_pages", 10),
            per_page=github_raw.get("per_page", 100),
            classification_batch_size=github_raw.get("classification_batch_size", 10),
            http_timeout_seconds=github_raw.get("http_timeout_seconds", 30.0),
        ),
        hf_daily=HFDailyConfig(
            enabled=hf_daily_raw.get("enabled", True),
            max_papers=hf_daily_raw.get("max_papers", 30),
            lookback_days=hf_daily_raw.get("lookback_days", 30),
            http_timeout_seconds=hf_daily_raw.get("http_timeout_seconds", 30.0),
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

    runtime = RuntimeConfig(
        db_path=runtime_data.get("db_path", unified.get("db_path", "data/workbench.db")),
        reports_dir=runtime_data.get("reports_dir", unified.get("reports_dir", "data/reports")),
        prompts_dir=runtime_data.get("prompts_dir", unified.get("prompts_dir", "prompts")),
    )
    runtime = RuntimeConfig(
        db_path=_resolve_runtime_path(runtime.db_path, project_root),
        reports_dir=_resolve_runtime_path(runtime.reports_dir, project_root),
        prompts_dir=_resolve_runtime_path(runtime.prompts_dir, project_root),
    )

    llm = LLMConfig(
        provider=llm_data.get("provider", "deepseek"),
        api_key_env=llm_data.get("api_key_env", "DEEPSEEK_API_KEY"),
        base_url=llm_data.get("base_url", "https://api.deepseek.com"),
        model=llm_data.get("model", "deepseek-chat"),
        temperature=llm_data.get("temperature", 0.3),
        max_concurrency=llm_data.get("max_concurrency", 5),
        max_retries=llm_data.get("max_retries", 3),
        retry_backoff_base_seconds=llm_data.get("retry_backoff_base_seconds", 2.0),
    )

    recommendations = RecommendationConfig(
        stale_after_days=recommendations_data.get("stale_after_days", 7),
        related_zotero_limit=recommendations_data.get("related_zotero_limit", 3),
        related_stars_limit=recommendations_data.get("related_stars_limit", 3),
    )

    display = DisplayConfig(
        dashboard_limit=display_data.get("dashboard_limit", 10),
        feedback_summary_limit=display_data.get("feedback_summary_limit", 5),
        recent_cards_limit=display_data.get("recent_cards_limit", 5),
        weekly_processed_limit=display_data.get("weekly_processed_limit", 10),
        manual_push_limit=display_data.get("manual_push_limit", 5),
    )

    feishu = FeishuConfig(
        async_timeout_seconds=feishu_data.get("async_timeout_seconds", 60.0),
    )

    return AppConfig(
        goals=goals,
        sources=sources,
        scoring=scoring,
        runtime=runtime,
        llm=llm,
        recommendations=recommendations,
        display=display,
        feishu=feishu,
        db_path=runtime.db_path,
        reports_dir=runtime.reports_dir,
        prompts_dir=runtime.prompts_dir,
        project_root=str(project_root),
    )


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        log.warning(f"Ignoring config file with invalid top-level shape: {path}")
        return {}
    return data


def _resolve_runtime_path(value: str, project_root: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return str(path.expanduser().resolve())


def _resolve_explicit_config(config_location: str) -> tuple[Path, Path]:
    path = Path(config_location).expanduser()
    if path.is_dir() or path.suffix.lower() not in {".yaml", ".yml"}:
        return path / "config.yaml", path.resolve()
    return path, path.parent.resolve()


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
