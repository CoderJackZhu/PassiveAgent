from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner

import passive_agent.main as main_module
from passive_agent.feishu.cards import CardBuilder
from passive_agent.pipeline import generate_weekly_report
from passive_agent.storage.models import Item
from passive_agent.utils.config import load_config


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def test_weekly_report_aggregates_item_events_and_renders_markdown(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    config.reports_dir = str(tmp_path / "reports")
    today = date.today()
    week_start = _week_start(today)
    start_dt = datetime.combine(week_start, datetime.min.time())

    db.log_daily_run(week_start, 5, 4, 3, [], status="success")
    db.save_items([
        Item(
            id="engaged",
            source="zotero",
            title="Clicked Agent Paper",
            topics=["Agent"],
            stage="recommended",
            priority_score=92,
            estimated_minutes=10,
        ),
        Item(
            id="read",
            source="obsidian_inbox",
            title="Read RAG Note",
            topics=["RAG"],
            stage="archived",
            actioned_at=start_dt + timedelta(days=1, hours=2),
        ),
        Item(
            id="ignored",
            source="github_star",
            title="Ignored Frontend Repo",
            topics=["Frontend"],
            stage="ignored",
        ),
        Item(
            id="passive",
            source="hf_daily_papers",
            title="Passive Paper",
            topics=["Agent"],
            stage="recommended",
        ),
    ])
    for offset, item_id in enumerate(["engaged", "read", "ignored", "passive"]):
        db.record_item_event(
            item_id,
            "pushed",
            surface="daily",
            created_at=start_dt + timedelta(hours=offset),
        )
    db.record_item_event("engaged", "expand", created_at=start_dt + timedelta(hours=2))
    db.record_item_event("read", "read", created_at=start_dt + timedelta(days=1))
    db.record_item_event("ignored", "ignore", created_at=start_dt + timedelta(days=2))

    path = generate_weekly_report(config, db)
    text = Path(path).read_text(encoding="utf-8")

    assert "- Distinct pushed items: 4" in text
    assert "- Clicked/engaged: 2 (50%)" in text
    assert "- Read: 1" in text
    assert "- Explicitly ignored: 1" in text
    assert "- Passive no-response: 1" in text
    assert "## Pushed Topic Distribution" in text
    assert "- Agent: 2" in text
    assert "## Engaged Source Distribution" in text
    assert "- zotero: 1" in text
    assert "- obsidian_inbox: 1" in text
    assert "## Top Clicked/Read Items" in text
    assert "Clicked Agent Paper" in text
    assert "Read RAG Note" in text
    assert "## Top Ignored/No-Response Items" in text
    assert "Ignored Frontend Repo" in text
    assert "Passive Paper" in text
    assert "## Next Week Suggestions" in text

    report = db.get_weekly_report(week_start)
    assert report["report_path"] == path
    assert report["summary"]["pushed_items"] == 4
    assert report["summary"]["engaged_items"] == 2
    assert report["summary"]["passive_items"] == 1


def test_weekly_report_card_contains_compact_metrics_and_path():
    report = {
        "week_start": date(2026, 6, 8),
        "week_end": date(2026, 6, 14),
        "report_path": "/tmp/weekly_review_2026-06-14.md",
        "summary": {
            "pushed_items": 4,
            "engaged_items": 2,
            "engagement_rate": 0.5,
            "read_items": 1,
            "ignored_items": 1,
            "passive_items": 1,
        },
        "suggestions": ["Keep Agent topics prominent.", "Reduce passive HF pushes."],
    }

    card = CardBuilder.build_weekly_report_card(report)
    content = "\n".join(element.get("content", "") for element in card["elements"])

    assert card["header"]["title"]["content"] == "周报 · 2026-06-08 ~ 2026-06-14"
    assert "Pushed: 4" in content
    assert "Engaged: 2 (50%)" in content
    assert "Read: 1" in content
    assert "Ignored: 1" in content
    assert "Passive: 1" in content
    assert "/tmp/weekly_review_2026-06-14.md" in content
    assert "Keep Agent topics prominent." in content


def test_weekly_report_passive_status_only_considers_actions_after_first_push(config_dir, db, tmp_path):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    config.reports_dir = str(tmp_path / "reports")
    week_start = _week_start(date.today())
    start_dt = datetime.combine(week_start, datetime.min.time())
    db.save_item(Item(id="late-push", source="zotero", title="Late Push", topics=["Agent"]))
    db.record_item_event("late-push", "ignore", created_at=start_dt + timedelta(hours=1))
    db.record_item_event("late-push", "pushed", created_at=start_dt + timedelta(hours=2))

    path = generate_weekly_report(config, db)
    text = Path(path).read_text(encoding="utf-8")

    assert "- Explicitly ignored: 1" in text
    assert "- Passive no-response: 1" in text


def test_weekly_report_push_is_idempotent_unless_forced(config_dir, db, tmp_path, monkeypatch):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    config.reports_dir = str(tmp_path / "reports")
    today = date.today()
    week_start = _week_start(today)
    db.save_item(Item(id="pushed", source="zotero", title="Pushed", topics=["Agent"]))
    db.record_item_event("pushed", "pushed", created_at=datetime.combine(week_start, datetime.min.time()))

    calls = []

    class RecordingBot:
        def send_weekly_report_card(self, report):
            calls.append(report)
            return True

    monkeypatch.setattr(main_module, "load_config", lambda _config_dir: config)
    monkeypatch.setattr(main_module, "_init_feishu_bot", lambda *_args, **_kwargs: RecordingBot())

    runner = CliRunner()
    first = runner.invoke(main_module.cli, ["--config-dir", config_dir, "weekly-report", "--push"])
    second = runner.invoke(main_module.cli, ["--config-dir", config_dir, "weekly-report", "--push"])
    forced = runner.invoke(main_module.cli, ["--config-dir", config_dir, "weekly-report", "--push", "--force"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert forced.exit_code == 0, forced.output
    assert len(calls) == 2
    assert "already pushed" in second.output
    assert db.get_weekly_report(week_start)["pushed_at"] is not None
    events = db.get_item_events_between(
        datetime.combine(week_start, datetime.min.time()),
        datetime.combine(week_start + timedelta(days=7), datetime.min.time()),
    )
    assert [event["event_type"] for event in events].count("weekly_report_pushed") == 2


def test_weekly_report_push_failure_does_not_mark_pushed(config_dir, db, tmp_path, monkeypatch):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    config.reports_dir = str(tmp_path / "reports")
    today = date.today()
    week_start = _week_start(today)
    db.save_item(Item(id="pushed", source="zotero", title="Pushed", topics=["Agent"]))
    db.record_item_event("pushed", "pushed", created_at=datetime.combine(week_start, datetime.min.time()))

    class FailingBot:
        def send_weekly_report_card(self, report):
            return False

    monkeypatch.setattr(main_module, "load_config", lambda _config_dir: config)
    monkeypatch.setattr(main_module, "_init_feishu_bot", lambda *_args, **_kwargs: FailingBot())

    result = CliRunner().invoke(main_module.cli, ["--config-dir", config_dir, "weekly-report", "--push"])

    assert result.exit_code == 1
    assert "Feishu weekly report push failed" in result.output
    assert db.get_weekly_report(week_start)["pushed_at"] is None
    events = db.get_item_events_between(
        datetime.combine(week_start, datetime.min.time()),
        datetime.combine(week_start + timedelta(days=7), datetime.min.time()),
    )
    assert [event["event_type"] for event in events].count("weekly_report_pushed") == 0
