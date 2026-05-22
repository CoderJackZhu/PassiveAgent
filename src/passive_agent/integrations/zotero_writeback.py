from __future__ import annotations

import httpx

from passive_agent.storage.database import Database
from passive_agent.utils.logger import log

ZOTERO_LOCAL_API = "http://localhost:23119/api"


class ZoteroWriteBack:
    """通过 Zotero local HTTP API (port 23119) 将 tag 写回 Zotero"""

    def __init__(self, db: Database):
        self.db = db

    async def flush_queue(self) -> int:
        pending = self.db.get_pending_zotero_writes()
        if not pending:
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
        # Get current item data
        resp = await client.get(f"{ZOTERO_LOCAL_API}/users/0/items/{item_key}")
        if resp.status_code != 200:
            log.warning(f"Zotero API: item {item_key} not found ({resp.status_code})")
            return False

        item_data = resp.json()
        tags = item_data.get("data", {}).get("tags", [])

        if any(t.get("tag") == tag for t in tags):
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
            log.warning(f"Zotero patch failed: {patch_resp.status_code}")
            return False

    @staticmethod
    def is_available() -> bool:
        try:
            resp = httpx.get(f"{ZOTERO_LOCAL_API}/users/0/items?limit=1", timeout=3)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
