from __future__ import annotations

import asyncio

import httpx

from passive_agent.collectors.base import Collector
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.storage.database import Database
from passive_agent.storage.models import RawItem
from passive_agent.utils.logger import log

GITHUB_API = "https://api.github.com"


class GitHubStarsCollector(Collector):
    """被动索引模式：仅在 init-stars 时一次性导入，daily pipeline 不自动触发"""

    def __init__(self, token: str, db: Database):
        self.token = token
        self.db = db
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def is_available(self) -> bool:
        return False

    async def collect(self) -> list[RawItem]:
        return []


class GitHubStarsInitializer:
    """一次性导入 GitHub Stars 并通过 LLM 批量分类"""

    def __init__(self, token: str, db: Database, llm: DeepSeekClient):
        self.token = token
        self.db = db
        self.llm = llm
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.star+json",
        }

    async def run(self, max_pages: int = 10) -> int:
        log.info("Fetching GitHub starred repos...")
        repos = await self._fetch_all_stars(max_pages)
        log.info(f"Fetched {len(repos)} starred repos")

        existing_urls = self.db.get_all_urls()
        new_repos = [r for r in repos if r["url"] not in existing_urls]
        log.info(f"New repos (not in DB): {len(new_repos)}")

        if not new_repos:
            return 0

        items = await self._classify_batch(new_repos)
        from passive_agent.processors.normalizer import Normalizer
        normalizer = Normalizer(self.db)
        normalized = normalizer.normalize(items)
        self.db.save_items(normalized)
        log.info(f"Imported {len(normalized)} GitHub stars")
        return len(normalized)

    async def refresh_metadata(self, max_pages: int = 10) -> int:
        """Re-fetch star counts and language for existing github_star items."""
        log.info("Refreshing GitHub Stars metadata...")
        repos = await self._fetch_all_stars(max_pages)
        url_to_repo = {r["url"]: r for r in repos}

        existing_items = self.db.get_items_by_source("github_star")
        updated = 0
        for item in existing_items:
            repo = url_to_repo.get(item.url)
            if repo:
                meta = {
                    "language": repo["language"],
                    "stars": repo["stars"],
                    "github_topics": repo["topics"],
                }
                self.db.update_item_extra_meta(item.id, meta)
                updated += 1

        log.info(f"Refreshed metadata for {updated} items")
        return updated

    async def _fetch_all_stars(self, max_pages: int) -> list[dict]:
        repos = []
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as client:
            for page in range(1, max_pages + 1):
                resp = await client.get(
                    f"{GITHUB_API}/user/starred",
                    params={"page": page, "per_page": 100},
                )
                if resp.status_code != 200:
                    log.error(f"GitHub API error: {resp.status_code}")
                    break

                data = resp.json()
                if not data:
                    break

                for entry in data:
                    repo = entry.get("repo", entry)
                    repos.append({
                        "name": repo["full_name"],
                        "url": repo["html_url"],
                        "description": repo.get("description") or "",
                        "language": repo.get("language") or "",
                        "topics": repo.get("topics", []),
                        "stars": repo.get("stargazers_count", 0),
                        "starred_at": entry.get("starred_at", ""),
                    })

                log.info(f"  Page {page}: {len(data)} repos")
                if len(data) < 100:
                    break

        return repos

    async def _classify_batch(self, repos: list[dict]) -> list[RawItem]:
        batch_size = 10
        items: list[RawItem] = []

        for i in range(0, len(repos), batch_size):
            batch = repos[i:i + batch_size]
            batch_text = "\n".join(
                f"{j+1}. {r['name']}: {r['description'][:100]} (lang: {r['language']}, topics: {','.join(r['topics'][:5])})"
                for j, r in enumerate(batch)
            )

            prompt = (
                f"以下是 {len(batch)} 个 GitHub 仓库。请判断每个是否和 AI Agent / LLM / RAG / "
                f"Tool Use / Multi-Agent / 面试准备 相关。\n\n{batch_text}\n\n"
                f"对每个仓库输出 JSON 数组，格式：\n"
                f'[{{"index": 1, "relevant": true, "topics": ["Agent", "RAG"], "content_type": "repo"}}]\n'
                f"不相关的设 relevant: false。"
            )

            try:
                result = await self.llm.generate_json(
                    system="你是技术内容分类器，判断 GitHub 仓库是否和面试准备相关。输出 JSON 数组。",
                    user=prompt,
                )
                if not isinstance(result, list):
                    result = [result]

                for entry in result:
                    idx = entry.get("index", 0) - 1
                    if 0 <= idx < len(batch) and entry.get("relevant", False):
                        repo = batch[idx]
                        items.append(RawItem(
                            source="github_star",
                            title=repo["name"],
                            url=repo["url"],
                            raw_text=repo["description"],
                            metadata={
                                "topics": entry.get("topics", []),
                                "language": repo["language"],
                                "stars": repo["stars"],
                                "github_topics": repo["topics"],
                            },
                        ))
            except Exception as e:
                log.warning(f"Failed to classify batch {i//batch_size + 1}: {e}")

        log.info(f"Classified {len(items)} relevant repos from {len(repos)} total")
        return items
