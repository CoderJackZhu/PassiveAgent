from datetime import datetime

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
