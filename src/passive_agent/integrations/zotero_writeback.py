from __future__ import annotations

import os

import httpx

from passive_agent.storage.database import Database
from passive_agent.utils.logger import log

ZOTERO_LOCAL_API = "http://localhost:23119/api"
ZOTERO_WEB_API = "https://api.zotero.org"


class ZoteroWriteBack:
    """通过 Zotero Web API 将 tag 写回 Zotero

    本地 API (23119) 只读，写入需通过 api.zotero.org + API key。
    默认 dry_run=True 仅打印不执行，确认测试通过后设置 dry_run=False 正式启用。
    """

    def __init__(
        self,
        db: Database,
        dry_run: bool = True,
        writeback_timeout_seconds: float = 15.0,
        local_api_timeout_seconds: float = 3.0,
    ):
        self.db = db
        self.dry_run = dry_run
        self.writeback_timeout_seconds = max(0.1, writeback_timeout_seconds)
        self.local_api_timeout_seconds = max(0.1, local_api_timeout_seconds)
        self.api_key = os.environ.get("ZOTERO_API_KEY", "")
        self.user_id = ""

    async def _resolve_user_id(self, client: httpx.AsyncClient) -> str:
        """从本地 API 获取 user ID"""
        if self.user_id:
            return self.user_id
        try:
            resp = await client.get(
                f"{ZOTERO_LOCAL_API}/users/0/items?limit=1",
                timeout=self.local_api_timeout_seconds,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    href = data[0].get("links", {}).get("self", {}).get("href", "")
                    # href like http://localhost:23119/api/users/9496887/items/KEY
                    parts = href.split("/users/")
                    if len(parts) > 1:
                        self.user_id = parts[1].split("/")[0]
        except Exception:
            pass
        return self.user_id

    async def flush_queue(self) -> int:
        pending = self.db.get_pending_zotero_writes()
        if not pending:
            log.info("Zotero write queue: empty")
            return 0

        if self.dry_run:
            log.info(f"Zotero write-back DRY RUN: {len(pending)} pending writes:")
            for entry in pending:
                remove = entry.get("remove_tag")
                if remove:
                    log.info(f"  [dry-run] would replace tag '{remove}' → '{entry['tag']}' on item {entry['item_key']}")
                else:
                    log.info(f"  [dry-run] would add tag '{entry['tag']}' to item {entry['item_key']}")
            return 0

        if not self.api_key:
            log.warning("Zotero write-back: ZOTERO_API_KEY not set, skipping")
            return 0

        success_count = 0
        async with httpx.AsyncClient(timeout=self.writeback_timeout_seconds) as client:
            user_id = await self._resolve_user_id(client)
            if not user_id:
                log.warning("Zotero write-back: could not resolve user ID")
                return 0

            for entry in pending:
                try:
                    ok = await self._update_tags(
                        client, user_id, entry["item_key"],
                        add_tag=entry["tag"],
                        remove_tag=entry.get("remove_tag"),
                    )
                    if ok:
                        self.db.mark_zotero_write_done(entry["id"])
                        success_count += 1
                except Exception as e:
                    log.warning(f"Zotero write-back failed for {entry['item_key']}: {e}")

        log.info(f"Zotero write-back: {success_count}/{len(pending)} tags written")
        return success_count

    async def _update_tags(self, client: httpx.AsyncClient, user_id: str,
                           item_key: str, add_tag: str, remove_tag: str | None = None) -> bool:
        headers = {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
        }

        resp = await client.get(
            f"{ZOTERO_WEB_API}/users/{user_id}/items/{item_key}",
            headers=headers,
        )
        if resp.status_code != 200:
            log.warning(f"Zotero Web API: item {item_key} not found ({resp.status_code})")
            return False

        item_data = resp.json()
        tags = item_data.get("data", {}).get("tags", [])
        version = item_data.get("version", 0)

        changed = False

        if remove_tag:
            new_tags = [t for t in tags if t.get("tag") != remove_tag]
            if len(new_tags) != len(tags):
                changed = True
                tags = new_tags

        if not any(t.get("tag") == add_tag for t in tags):
            tags.append({"tag": add_tag})
            changed = True

        if not changed:
            log.info(f"Zotero: tags already correct on {item_key}, skipping")
            return True

        patch_resp = await client.patch(
            f"{ZOTERO_WEB_API}/users/{user_id}/items/{item_key}",
            json={"tags": tags},
            headers={**headers, "If-Unmodified-Since-Version": str(version)},
        )

        if patch_resp.status_code in (200, 204):
            if remove_tag:
                log.info(f"Zotero: replaced '{remove_tag}' → '{add_tag}' on {item_key}")
            else:
                log.info(f"Zotero: added tag '{add_tag}' to {item_key}")
            return True
        else:
            log.warning(f"Zotero patch failed for {item_key}: {patch_resp.status_code} {patch_resp.text[:100]}")
            return False

    @staticmethod
    def is_available(local_api_timeout_seconds: float = 3.0) -> bool:
        try:
            resp = httpx.get(
                f"{ZOTERO_LOCAL_API}/users/0/items?limit=1",
                timeout=max(0.1, local_api_timeout_seconds),
            )
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
