from __future__ import annotations

import pytest

from passive_agent.integrations.zotero_writeback import ZoteroWriteBack
from passive_agent.storage.database import Database


@pytest.fixture
def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    yield db
    db.close()


def test_is_available_detects_zotero():
    result = ZoteroWriteBack.is_available()
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_flush_queue_empty(db):
    wb = ZoteroWriteBack(db, dry_run=True)
    count = await wb.flush_queue()
    assert count == 0


@pytest.mark.asyncio
async def test_flush_queue_dry_run_does_not_execute(db):
    db.enqueue_zotero_write("ABC123", "recommended")
    wb = ZoteroWriteBack(db, dry_run=True)
    count = await wb.flush_queue()
    assert count == 0
    pending = db.get_pending_zotero_writes()
    assert len(pending) == 1
