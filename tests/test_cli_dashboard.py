from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import passive_agent.main as main_module
from passive_agent.storage.models import Item
from passive_agent.utils.config import load_config


def test_dashboard_command_shows_expected_sections(config_dir, db, monkeypatch):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    db.save_items([
        Item(
            id="rec",
            source="zotero",
            title="Recommended Item",
            topics=["Agent"],
            stage="recommended",
            estimated_minutes=10,
            priority_score=91.2,
            recommended_action="read",
        ),
        Item(id="new", source="obsidian_inbox", title="New Item", stage="new"),
    ])

    monkeypatch.setattr(main_module, "load_config", lambda _config_dir: config)

    result = CliRunner().invoke(main_module.cli, ["--config-dir", config_dir, "dashboard"])

    assert result.exit_code == 0
    assert "Stage counts" in result.output
    assert "Today's recommendations" in result.output
    assert "Source health" in result.output
    assert "Pause status" in result.output
    assert "Feedback summary" in result.output


def test_open_daily_generates_valid_html_file(config_dir, db, tmp_path, monkeypatch):
    config = load_config(config_dir)
    config.db_path = str(db.db_path)
    config.reports_dir = str(tmp_path / "reports")
    reports_dir = Path(config.reports_dir)
    reports_dir.mkdir()
    daily_report = reports_dir / "daily_review_2026-05-23.md"
    daily_report.write_text("# 今日推荐\n\n- **来源**: Zotero\n", encoding="utf-8")
    opened_urls = []

    monkeypatch.setattr(main_module, "load_config", lambda _config_dir: config)
    monkeypatch.setattr(main_module.webbrowser, "open", lambda url: opened_urls.append(url))

    result = CliRunner().invoke(main_module.cli, ["--config-dir", config_dir, "open-daily"])

    assert result.exit_code == 0
    html_path = daily_report.with_suffix(".html")
    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<html" in html
    assert "<h1>今日推荐</h1>" in html
    assert "</html>" in html
    assert opened_urls == [html_path.resolve().as_uri()]
