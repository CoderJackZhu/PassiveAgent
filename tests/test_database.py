from datetime import datetime, timedelta

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item


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
