from __future__ import annotations

import httpx

from passive_agent.storage.database import Database
from passive_agent.utils.logger import log

ZOTERO_LOCAL_API = "http://localhost:23119/api"


class ZoteroWriteBack:
    """通过 Zotero local HTTP API (port 23119) 将 tag 写回 Zotero

    注意：此功能会修改 Zotero 条目的 tag，默认 dry_run=True 仅打印不执行。
    确认测试通过后设置 dry_run=False 正式启用。
    """

    def __init__(self, db: Database, dry_run: bool = True):
        self.db = db
        self.dry_run = dry_run

    async def flush_queue(self) -> int:
        pending = self.db.get_pending_zotero_writes()
        if not pending:
            log.info("Zotero write queue: empty")
            return 0

        if self.dry_run:
            log.info(f"Zotero write-back DRY RUN: {len(pending)} pending writes:")
            for entry in pending:
                log.info(f"  [dry-run] would add tag '{entry['tag']}' to item {entry['item_key']}")
            return 0

        success_count = 0
        async with httpx.AsyncClient(timeout=10) as client:
            for entry in pending:
                try:
                    ok = await self._add_tag(client, entry["item_key"], entry["tag"])
                    if ok:
                        self.db.mark_zotero_write_done(entry["id"])
                        success_count += 1
                except Exception as e:
                    log.warning(f"Zotero write-back failed for {entry['item_key']}: {e}")

        log.info(f"Zotero write-back: {success_count}/{len(pending)} tags written")
        return success_count

    async def _add_tag(self, client: httpx.AsyncClient, item_key: str, tag: str) -> bool:
        resp = await client.get(f"{ZOTERO_LOCAL_API}/users/0/items/{item_key}")
        if resp.status_code != 200:
            log.warning(f"Zotero API: item {item_key} not found ({resp.status_code})")
            return False

        item_data = resp.json()
        tags = item_data.get("data", {}).get("tags", [])

        if any(t.get("tag") == tag for t in tags):
            log.info(f"Zotero: tag '{tag}' already on {item_key}, skipping")
            return True

        tags.append({"tag": tag})
        version = item_data.get("version", 0)

        patch_resp = await client.patch(
            f"{ZOTERO_LOCAL_API}/users/0/items/{item_key}",
            json={"tags": tags},
            headers={"If-Unmodified-Since-Version": str(version)},
        )

        if patch_resp.status_code in (200, 204):
            log.info(f"Zotero: added tag '{tag}' to {item_key}")
            return True
        else:
            log.warning(f"Zotero patch failed for {item_key}: {patch_resp.status_code}")
            return False

    @staticmethod
    def is_available() -> bool:
        try:
            resp = httpx.get(f"{ZOTERO_LOCAL_API}/users/0/items?limit=1", timeout=3)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
