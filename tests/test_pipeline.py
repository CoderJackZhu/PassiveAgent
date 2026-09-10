from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

import passive_agent.main as main_module
from passive_agent.collectors.hf_daily import HFDailyPapersCollector
from passive_agent.collectors.zotero import ZoteroCollector
from passive_agent.feishu.cards import CardBuilder
from passive_agent.pipeline import DailyPipeline, generate_weekly_report
from passive_agent.processors.ranker import Ranker
from passive_agent.storage.models import EnrichedItem, Item, RawItem
from passive_agent.utils.config import load_config


class FakeCollector:
    def __init__(self, items: list[RawItem]):
        self.items = items

    def is_available(self) -> bool:
        return True

    async def collect(self) -> list[RawItem]:
        return self.items


class FakeLLM:
    async def generate_json(self, system: str, user: str) -> dict:
        if "评分" in system:
            return {
                "goal_relevance": 80,
                "novelty": 70,
                "actionability": 75,
                "difficulty_fit": 65,
                "source_quality": 85,
                "timeliness": 70,
            }

        return {
            "summary": "Agent memory summary",
            "interview_relevance": "Useful for agent memory interviews.",
            "recommended_action": "read",
            "estimated_minutes": 12,
            "topics": ["Agent"],
            "content_type": "article",
        }


class FakeBot:
    def __init__(self, result: bool):
        self.result = result
        self.calls = 0

    def send_daily_card(self, items: list[EnrichedItem], *, respect_pause: bool = True) -> bool:
        self.calls += 1
        return self.result


class SelectiveFailingLLM(FakeLLM):
    def __init__(self, failure_stage: str, failed_title: str):
        self.failure_stage = failure_stage
        self.failed_title = failed_title

    async def generate_json(self, system: str, user: str) -> dict:
        stage = "score" if "评分" in system else "summary"
        if stage == self.failure_stage and self.failed_title in user:
            raise ValueError(f"simulated {stage} failure")
        return await super().generate_json(system, user)


class RecordingBot:
    def __init__(self):
        self.batches: list[list[EnrichedItem]] = []

    def send_daily_card(self, items: list[EnrichedItem], *, respect_pause: bool = True) -> bool:
        self.batches.append(items)
        return True


def test_feishu_bot_records_pushed_events_only_after_success(db):
    from passive_agent.feishu.bot import FeishuBot

    bot = object.__new__(FeishuBot)
    bot.db = db
    bot.chat_id = "chat"
    send_results = [True, False]
    bot._send_card = lambda _chat_id, _card: send_results.pop(0)
    item = Item(id="daily-push", source="zotero", title="Daily Push")

    assert bot.send_daily_card([EnrichedItem(item=item)], surface="manual") is True
    assert bot.send_daily_card([EnrichedItem(item=item)], surface="manual") is False

    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"], event["surface"]) for event in events] == [
        ("daily-push", "pushed", "manual")
    ]


def test_feishu_bot_records_weekend_pushed_events(db):
    from passive_agent.feishu.bot import FeishuBot

    bot = object.__new__(FeishuBot)
    bot.db = db
    bot.chat_id = "chat"
    bot._send_card = lambda _chat_id, _card: True
    item = Item(id="weekend-push", source="zotero", title="Weekend Push")

    assert bot.send_weekend_card([EnrichedItem(item=item)]) is True

    events = db.get_item_events_between(
        datetime.now() - timedelta(minutes=1),
        datetime.now() + timedelta(minutes=1),
    )
    assert [(event["item_id"], event["event_type"], event["surface"]) for event in events] == [
        ("weekend-push", "pushed", "weekend")
    ]


def test_feishu_bot_background_timeout_error_message_is_actionable():
    import asyncio

    from passive_agent.feishu.bot import _format_background_action_error

    assert _format_background_action_error(asyncio.TimeoutError(), 180.0) == (
        "处理超时：后台操作超过 180 秒未完成，请稍后重试或调高 "
        "feishu.background_action_timeout_seconds"
    )


def test_pipeline_initializes_collectors_with_configured_knobs(config_dir, db):
    config = load_config(config_dir)
    config.sources.zotero.enabled = True
    config.sources.zotero.db_path = "/tmp/custom-zotero.sqlite"
    config.sources.zotero.lookback_days = 14
    config.sources.zotero.sqlite_timeout_seconds = 7.0
    config.sources.zotero.db_retries = 4
    config.sources.zotero.db_retry_sleep_seconds = 0.5
    config.sources.hf_daily.enabled = True
    config.sources.hf_daily.max_papers = 12
    config.sources.hf_daily.lookback_days = 6
    config.sources.hf_daily.http_timeout_seconds = 9.0

    collectors = DailyPipeline(config, db)._init_collectors()

    zotero = next(c for c in collectors if isinstance(c, ZoteroCollector))
    hf_daily = next(c for c in collectors if isinstance(c, HFDailyPapersCollector))
    assert str(zotero.db_path) == "/tmp/custom-zotero.sqlite"
    assert zotero.lookback_days == 14
    assert zotero.sqlite_timeout_seconds == 7.0
    assert zotero.db_retries == 4
    assert zotero.db_retry_sleep_seconds == 0.5
    assert hf_daily.max_papers == 12
    assert hf_daily.days == 6
    assert hf_daily.timeout_seconds == 9.0


@pytest.mark.asyncio
async def test_daily_pipeline_skips_when_persistently_paused(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    db.set_paused(True)

    pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=FakeBot(True))
    collector_called = False

    def fail_if_called():
        nonlocal collector_called
        collector_called = True
        return [FakeCollector([])]

    pipeline._init_collectors = fail_if_called

    result = await pipeline.run()

    assert result.status == "paused"
    assert collector_called is False

    row = db.conn.execute(
        "SELECT status, pushed_count, errors FROM daily_log WHERE date = ?",
        (date.today().isoformat(),),
    ).fetchone()
    assert row["status"] == "paused"
    assert row["pushed_count"] == 0
    assert json.loads(row["errors"]) == []


def test_feishu_push_bypasses_persisted_pause_for_manual_validation(config_dir, db, monkeypatch):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    db.set_paused(True)
    db.save_item(Item(id="manual", source="zotero", title="Manual push", stage="recommended"))

    calls = []

    class RecordingBot:
        def send_daily_card(
            self,
            items: list[EnrichedItem],
            *,
            respect_pause: bool = True,
            surface: str = "daily",
        ) -> bool:
            calls.append((len(items), respect_pause, surface))
            return True

    monkeypatch.setattr(main_module, "load_config", lambda _config_dir: config)
    monkeypatch.setattr(main_module, "_init_feishu_bot", lambda *_args, **_kwargs: RecordingBot())

    result = CliRunner().invoke(
        main_module.cli,
        ["--config-dir", config_dir, "feishu-push", "--limit", "1"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(1, False, "manual")]
    assert db.is_paused() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bot_result", "expected_pushed", "expect_error"),
    [(True, 1, False), (False, 0, True)],
)
async def test_daily_pipeline_records_actual_push_count(
    config_dir, db, tmp_path, bot_result, expected_pushed, expect_error
):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")

    raw = RawItem(source="zotero", title=f"Agent Memory {bot_result}", url="https://example.com/a")
    bot = FakeBot(bot_result)
    pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=bot)
    pipeline._init_collectors = lambda: [FakeCollector([raw])]

    result = await pipeline.run()

    assert result.status == "success"
    assert bot.calls == 1
    assert result.pushed == expected_pushed

    row = db.conn.execute(
        "SELECT pushed_count, errors FROM daily_log WHERE date = ?",
        (date.today().isoformat(),),
    ).fetchone()
    errors = json.loads(row["errors"])
    assert row["pushed_count"] == expected_pushed
    assert bool(errors) is expect_error


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["summary", "score"])
async def test_daily_pipeline_total_llm_failure_is_error_and_items_remain_retryable(
    config_dir, db, tmp_path, failure_stage
):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")

    title = f"Retry after {failure_stage} failure"
    raw = RawItem(source="zotero", title=title, url=f"https://example.com/{failure_stage}")
    bot = RecordingBot()
    pipeline = DailyPipeline(
        config,
        db,
        llm=SelectiveFailingLLM(failure_stage, title),
        feishu_bot=bot,
    )
    pipeline._init_collectors = lambda: [FakeCollector([raw])]

    failed = await pipeline.run()

    assert failed.status == "error"
    assert failed.recommended == []
    assert failed.pushed == 0
    assert bot.batches == []
    pending = db.get_items_by_stage("retry_pending")
    assert [item.title for item in pending] == [title]
    assert not (Path(config.reports_dir) / f"daily_review_{date.today().isoformat()}.md").exists()
    assert any(failure_stage in error and "retry" in error.lower() for error in failed.errors)

    row = db.conn.execute(
        "SELECT status, pushed_count, errors FROM daily_log WHERE date = ?",
        (date.today().isoformat(),),
    ).fetchone()
    assert row["status"] == "error"
    assert row["pushed_count"] == 0
    assert title in " ".join(json.loads(row["errors"]))

    pipeline.llm = FakeLLM()
    pipeline._init_collectors = lambda: [FakeCollector([])]
    retried = await pipeline.run()

    assert retried.status == "success"
    assert [item.item.title for item in retried.recommended] == [title]
    assert db.get_all_titles() == {title}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["summary", "score"])
async def test_daily_pipeline_partial_llm_failure_only_processes_successes(
    config_dir, db, tmp_path, failure_stage
):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")

    good_title = f"Good item for {failure_stage}"
    failed_title = f"Failed item for {failure_stage}"
    raw_items = [
        RawItem(source="zotero", title=good_title, url=f"https://example.com/good-{failure_stage}"),
        RawItem(source="zotero", title=failed_title, url=f"https://example.com/bad-{failure_stage}"),
    ]
    bot = RecordingBot()
    pipeline = DailyPipeline(
        config,
        db,
        llm=SelectiveFailingLLM(failure_stage, failed_title),
        feishu_bot=bot,
    )
    pipeline._init_collectors = lambda: [FakeCollector(raw_items)]

    result = await pipeline.run()

    assert result.status == "success"
    assert [item.item.title for item in result.recommended] == [good_title]
    assert [[item.item.title for item in batch] for batch in bot.batches] == [[good_title]]
    pending = db.get_items_by_stage("retry_pending")
    assert [item.title for item in pending] == [failed_title]
    assert db.get_all_titles() == {good_title, failed_title}
    assert all(item.item.priority_score != 50.0 for item in result.recommended)
    assert any(failure_stage in error and failed_title in error for error in result.errors)

    report = Path(config.reports_dir) / f"daily_review_{date.today().isoformat()}.md"
    report_text = report.read_text(encoding="utf-8")
    assert good_title in report_text
    assert failed_title not in report_text

    retry_bot = RecordingBot()
    retry_pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=retry_bot)
    retry_pipeline._init_collectors = lambda: [FakeCollector([])]

    retried = await retry_pipeline.run()

    assert retried.status == "success"
    assert [item.item.title for item in retried.recommended] == [failed_title]


@pytest.mark.asyncio
async def test_daily_pipeline_does_not_treat_github_star_index_as_retry_queue(
    config_dir, db, tmp_path
):
    config = load_config(config_dir)
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")
    star = Item(
        id="indexed-star",
        source="github_star",
        title="Indexed GitHub Star",
        url="https://github.com/example/indexed",
        stage="new",
    )
    db.save_item(star)
    bot = RecordingBot()
    pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=bot)  # type: ignore[arg-type]
    pipeline._init_collectors = lambda: [FakeCollector([])]

    result = await pipeline.run()

    assert result.status == "empty"
    assert bot.batches == []
    assert db.get_item(star.id).stage == "new"


@pytest.mark.asyncio
async def test_daily_pipeline_enrich_failure_leaves_scored_item_retryable(
    config_dir, db, tmp_path, monkeypatch
):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")

    title = "Retry after enrich failure"
    raw = RawItem(source="zotero", title=title, url="https://example.com/enrich-failure")
    bot = RecordingBot()
    pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=bot)
    pipeline._init_collectors = lambda: [FakeCollector([raw])]
    original_enrich = Ranker.enrich

    def fail_enrich(_self, _items):
        raise RuntimeError("simulated enrich failure")

    monkeypatch.setattr(Ranker, "enrich", fail_enrich)

    failed = await pipeline.run()

    assert failed.status == "error"
    assert failed.recommended == []
    assert failed.pushed == 0
    assert bot.batches == []
    pending = db.get_items_by_stage("retry_pending")
    assert [item.title for item in pending] == [title]
    assert db.conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0
    assert not (Path(config.reports_dir) / f"daily_review_{date.today().isoformat()}.md").exists()

    monkeypatch.setattr(Ranker, "enrich", original_enrich)
    pipeline._init_collectors = lambda: [FakeCollector([])]
    retried = await pipeline.run()

    assert retried.status == "success"
    assert [item.item.title for item in retried.recommended] == [title]
    assert db.get_all_titles() == {title}
    assert db.conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_daily_pipeline_deduplicates_related_zotero_across_new_push_batch(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.project_root = ""
    config.reports_dir = str(tmp_path / "reports")
    config.prompts_dir = str(Path.cwd() / "prompts")
    config.scoring.daily_limit = 3
    config.recommendations.related_zotero_limit = 1

    db.save_item(Item(
        id="archived-sft-rl",
        source="zotero",
        title="探索为什么要融合SFT和RL，以及应该怎么融合",
        topics=["Agent"],
        stage="archived",
    ))

    class RecordingBot:
        def __init__(self):
            self.items: list[EnrichedItem] = []

        def send_daily_card(self, items: list[EnrichedItem], *, respect_pause: bool = True) -> bool:
            self.items = items
            return True

    raw_items = [
        RawItem(source="zotero", title=title, url=f"https://example.com/{i}")
        for i, title in enumerate([
            "Agent Memory Architecture",
            "Retrieval Evaluation Playbook",
            "Alignment Training Recipe",
        ])
    ]
    bot = RecordingBot()
    pipeline = DailyPipeline(config, db, llm=FakeLLM(), feishu_bot=bot)
    pipeline._init_collectors = lambda: [FakeCollector(raw_items)]

    result = await pipeline.run()

    assert result.status == "success"
    related = [title for enriched in bot.items for title in enriched.related_zotero]
    assert related == ["探索为什么要融合SFT和RL，以及应该怎么融合"]


def test_daily_review_includes_structured_metrics(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.reports_dir = str(tmp_path / "reports")
    item_a = Item(
        id="a",
        source="zotero",
        title="Agent Memory",
        topics=["Agent"],
        estimated_minutes=10,
        priority_score=82.0,
        recommended_action="read",
        summary="Memory summary.",
    )
    item_b = Item(
        id="b",
        source="obsidian_inbox",
        title="RAG Note",
        topics=["RAG"],
        estimated_minutes=5,
        priority_score=68.0,
        recommended_action="note",
    )

    DailyPipeline(config, db)._output_daily_review(
        [
            EnrichedItem(item=item_a, related_stars=["mem0"]),
            EnrichedItem(item=item_b),
        ]
    )

    output = tmp_path / "reports" / f"daily_review_{date.today().isoformat()}.md"
    text = output.read_text(encoding="utf-8")

    assert "## 概览" in text
    assert "- 推荐数量：2 条" in text
    assert "- 总预计时间：15 分钟" in text
    assert "zotero: 1" in text
    assert "obsidian_inbox: 1" in text
    assert "评分范围：68.0 ~ 82.0，平均 75.0" in text
    assert "## 今日行动建议" in text
    assert "## 条目详情" in text
    assert "相关 GitHub Star" in text


def test_weekly_report_includes_daily_log_and_backlog_metrics(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.reports_dir = str(tmp_path / "reports")
    today = date.today()
    now = datetime.now()

    db.log_daily_run(today, 3, 2, 1, [], status="success")
    db.log_daily_run(today - timedelta(days=1), 1, 1, 0, ["Feishu push: returned False"], status="success")
    db.log_daily_run(today - timedelta(days=2), 0, 0, 0, ["pipeline paused"], status="paused")
    db.save_items([
        Item(id="rec", source="zotero", title="Recommended", stage="recommended"),
        Item(id="stale", source="zotero", title="Stale", stage="stale"),
        Item(
            id="arch",
            source="obsidian_inbox",
            title="Archived",
            stage="archived",
            topics=["Agent"],
            actioned_at=now,
        ),
    ])

    path = generate_weekly_report(config, db)
    text = Path(path).read_text(encoding="utf-8")

    assert "- 本周收集：4 条" in text
    assert "- 本周处理：3 条" in text
    assert "- 本周推送：1 条" in text
    assert "- 异常天数：1 天" in text
    assert "- 当前待处理：1 条" in text
    assert "- 已过期推荐：1 条" in text
    assert "## Topic 分布" in text
    assert "- Agent: 1" in text
    assert "## Source 分布" in text
    assert "- obsidian_inbox: 1" in text


def test_ranker_enriches_items_with_related_github_stars_and_card_wording(db):
    item = Item(id="item", source="zotero", title="Agent Paper", topics=["Agent"])
    star = Item(
        id="star",
        source="github_star",
        title="agent-framework",
        topics=["Agent"],
        extra_meta={"stars": 1200},
    )
    second_star = Item(
        id="star2",
        source="github_star",
        title="agent-runner",
        topics=["Agent"],
        extra_meta={"stars": 900},
    )
    db.save_items([star, second_star])

    enriched = Ranker(db, related_stars_limit=1).enrich([item])

    assert enriched[0].related_stars == ["agent-framework"]
    card = CardBuilder.build_daily_card(enriched)
    content = "\n".join(element.get("content", "") for element in card["elements"])
    assert "相关 GitHub Star" in content


def test_daily_card_deduplicates_related_zotero_footer():
    duplicate_title = "探索为什么要融合SFT和RL，以及应该怎么融合"
    items = [
        EnrichedItem(
            item=Item(id=f"item-{i}", source="zotero", title=f"Recommended {i}"),
            related_zotero=[duplicate_title],
        )
        for i in range(3)
    ]

    card = CardBuilder.build_daily_card(items)
    content = "\n".join(element.get("content", "") for element in card["elements"])

    assert content.count(duplicate_title) == 1
