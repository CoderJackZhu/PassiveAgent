import sqlite3
from datetime import date, datetime, timedelta

import pytest

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item, Score


def test_database_initialize(db):
    tables = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r["name"] for r in tables}
    assert "items" in table_names
    assert "scores" in table_names
    assert "feedback" in table_names
    assert "topic_weights" in table_names
    assert "daily_log" in table_names
    assert "app_state" in table_names
    assert "item_events" in table_names
    assert "weekly_reports" in table_names


def test_save_and_get_item(db):
    item = Item(
        id="item_20260522_001",
        source="zotero",
        title="Test Article",
        url="https://example.com",
        collected_at=datetime(2026, 5, 22, 21, 0),
        topics=["Agent", "RAG"],
        stage="new",
        created_at=datetime(2026, 5, 22, 21, 0),
    )
    db.save_item(item)

    loaded = db.get_item("item_20260522_001")
    assert loaded is not None
    assert loaded.title == "Test Article"
    assert loaded.source == "zotero"
    assert loaded.topics == ["Agent", "RAG"]
    assert loaded.stage == "new"


def test_get_all_titles(db):
    item1 = Item(
        id="item_20260522_001", source="zotero", title="Article A",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    item2 = Item(
        id="item_20260522_002", source="obsidian_inbox", title="Article B",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_items([item1, item2])

    titles = db.get_all_titles()
    assert "Article A" in titles
    assert "Article B" in titles


def test_save_scored_items_rolls_back_items_when_a_score_insert_fails(db):
    item = Item(id="atomic-item", source="zotero", title="Atomic item")
    score = Score(
        item_id="missing-item",
        goal_relevance=80,
        novelty=70,
        actionability=75,
        difficulty_fit=65,
        source_quality=85,
        timeliness=70,
        weighted_total=75,
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.save_scored_items([item], [score])

    assert db.get_all_titles() == set()
    assert db.conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0


def test_update_stage(db):
    item = Item(
        id="item_20260522_001", source="zotero", title="Test",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_item(item)

    db.update_item_stage("item_20260522_001", "archived")
    loaded = db.get_item("item_20260522_001")
    assert loaded.stage == "archived"
    assert loaded.actioned_at is not None


def test_topic_weights(db):
    assert db.get_topic_weight("Agent") == 1.0

    db.set_topic_weight("Agent", 0.7)
    assert db.get_topic_weight("Agent") == 0.7


def test_count_items_by_date(db):
    item = Item(
        id="item_20260522_001", source="zotero", title="Test",
        collected_at=datetime.now(), created_at=datetime.now(),
    )
    db.save_item(item)

    assert db.count_items_by_date("20260522") == 1
    assert db.count_items_by_date("20260523") == 0


def test_paused_state_persists_across_database_instances(tmp_path):
    db_path = tmp_path / "state.db"
    first = Database(str(db_path))
    first.initialize()
    first.set_paused(True)
    first.close()

    second = Database(str(db_path))
    second.initialize()
    try:
        assert second.is_paused() is True

        second.set_paused(False)
        assert second.is_paused() is False
    finally:
        second.close()


def test_mark_stale_recommendations_only_marks_old_recommended(db):
    now = datetime.now()
    old_recommended = Item(
        id="old_recommended",
        source="zotero",
        title="Old Recommended",
        stage="recommended",
        collected_at=now - timedelta(days=8),
        created_at=now - timedelta(days=8),
    )
    recent_recommended = Item(
        id="recent_recommended",
        source="zotero",
        title="Recent Recommended",
        stage="recommended",
        collected_at=now - timedelta(days=2),
        created_at=now - timedelta(days=2),
    )
    old_archived = Item(
        id="old_archived",
        source="zotero",
        title="Old Archived",
        stage="archived",
        collected_at=now - timedelta(days=8),
        created_at=now - timedelta(days=8),
    )
    db.save_items([old_recommended, recent_recommended, old_archived])

    assert db.mark_stale_recommendations(days=7) == 1
    assert db.get_item("old_recommended").stage == "stale"
    assert db.get_item("recent_recommended").stage == "recommended"
    assert db.get_item("old_archived").stage == "archived"


def test_record_item_event_persists_metadata_and_timestamp(db):
    created_at = datetime(2026, 6, 8, 9, 30)

    db.record_item_event(
        "item_event",
        "pushed",
        surface="daily",
        metadata={"rank": 1, "title": "Agent Memory"},
        created_at=created_at,
    )

    events = db.get_item_events_between(
        datetime(2026, 6, 8),
        datetime(2026, 6, 9),
    )
    assert len(events) == 1
    event = events[0]
    assert event["item_id"] == "item_event"
    assert event["event_type"] == "pushed"
    assert event["surface"] == "daily"
    assert event["metadata"] == {"rank": 1, "title": "Agent Memory"}
    assert event["created_at"] == created_at


def test_get_item_events_between_uses_inclusive_start_exclusive_end(db):
    start = datetime(2026, 6, 2)
    end = datetime(2026, 6, 9)
    db.record_item_event("before", "pushed", created_at=start - timedelta(seconds=1))
    db.record_item_event("at_start", "pushed", created_at=start)
    db.record_item_event("middle", "read", created_at=start + timedelta(days=2))
    db.record_item_event("at_end", "ignore", created_at=end)

    events = db.get_item_events_between(start, end)

    assert [event["item_id"] for event in events] == ["at_start", "middle"]


def test_weekly_report_push_state_can_be_saved_and_read(db):
    week_start = date(2026, 6, 8)
    generated_at = datetime(2026, 6, 10, 12, 0)
    pushed_at = datetime(2026, 6, 14, 21, 31)

    db.save_weekly_report(
        week_start=week_start,
        report_path="/tmp/weekly.md",
        generated_at=generated_at,
        summary={"pushed_items": 3, "engaged_items": 2},
    )
    report = db.get_weekly_report(week_start)
    assert report["report_path"] == "/tmp/weekly.md"
    assert report["generated_at"] == generated_at
    assert report["pushed_at"] is None
    assert report["summary"] == {"pushed_items": 3, "engaged_items": 2}

    db.mark_weekly_report_pushed(week_start, pushed_at=pushed_at)
    report = db.get_weekly_report(week_start)
    assert report["pushed_at"] == pushed_at


def test_initialize_backfills_legacy_ignore_feedback_once(tmp_path):
    db_path = tmp_path / "legacy-v4.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
    CREATE TABLE items (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT,
        local_path TEXT,
        zotero_key TEXT,
        collected_at TEXT NOT NULL,
        content_type TEXT,
        topics TEXT,
        stage TEXT NOT NULL DEFAULT 'new',
        summary TEXT,
        interview_relevance TEXT,
        estimated_minutes INTEGER,
        priority_score REAL,
        recommended_action TEXT,
        ignored_count INTEGER DEFAULT 0,
        is_weekend INTEGER DEFAULT 0,
        raw_text TEXT,
        extra_meta TEXT,
        created_at TEXT NOT NULL,
        actioned_at TEXT
    );
    CREATE TABLE feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL,
        action TEXT NOT NULL,
        topic TEXT,
        source TEXT,
        created_at TEXT NOT NULL
    );
    PRAGMA user_version = 4;
    """)
    conn.execute(
        """INSERT INTO feedback (item_id, action, topic, source, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("legacy-ignore", "ignore", "Agent", "zotero", "2026-06-08T10:00:00"),
    )
    conn.execute(
        """INSERT INTO feedback (item_id, action, topic, source, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("legacy-card", "card", "Agent", "zotero", "2026-06-08T11:00:00"),
    )
    conn.commit()
    conn.close()

    first = Database(db_path)
    first.initialize()
    first.close()
    second = Database(db_path)
    second.initialize()

    events = second.get_item_events_between(
        datetime(2026, 6, 8),
        datetime(2026, 6, 9),
    )
    second.close()

    assert [(event["item_id"], event["event_type"]) for event in events] == [
        ("legacy-ignore", "ignore")
    ]
    assert events[0]["surface"] == "legacy_feedback"
    assert events[0]["metadata"]["feedback_id"] == 1
