# Passive Agent Workbench — 技术方案

## 1. 技术选型

| 层面 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | LLM SDK 生态最好，SQLite 原生支持，快速迭代 |
| 数据库 | SQLite (标准库 sqlite3) | 本地单进程场景，零运维 |
| LLM | DeepSeek V4 Pro (OpenAI 兼容接口) | 性价比高，中文理解好，结构化输出稳定 |
| 飞书 SDK | `lark-oapi` (官方 Python SDK) | 长连接模式无需公网 IP |
| 调度 | launchd (macOS 原生) | 稳定可靠，不引入额外依赖 |
| 配置 | PyYAML | 简洁，人类可读 |
| HTTP 客户端 | httpx | 支持 async，用于 Zotero local API 和 LLM 调用 |
| CLI | click | 轻量，适合多子命令 |
| 模板 | Jinja2 | Prompt 模板渲染 |

---

## 2. 项目结构

```
PassiveAgent/
├── config/
│   ├── goals.yaml                 # 当前目标与 topic 定义
│   ├── sources.yaml               # 数据源配置
│   └── scoring.yaml               # 打分权重与负反馈参数
├── src/
│   ├── __init__.py
│   ├── main.py                    # CLI 入口 (daily / serve / init-stars)
│   ├── pipeline.py                # 每日流水线编排
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py                # Collector 协议定义
│   │   ├── zotero.py              # Zotero SQLite 只读收集
│   │   ├── obsidian.py            # Obsidian inbox.md 解析
│   │   └── github_stars.py        # GitHub Stars 初始化与被动索引
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── normalizer.py          # 原始数据 → Item 结构
│   │   ├── deduplicator.py        # 去重 (标题+URL / 模糊匹配)
│   │   ├── summarizer.py          # LLM 生成面试相关度摘要
│   │   ├── scorer.py              # 多维度打分
│   │   └── ranker.py              # 排序 + Top N + Enrich
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── base.py                # Action 协议定义
│   │   ├── expand.py              # 生成 500-800 字详细摘要
│   │   ├── interview_card.py      # 生成面试卡 → Obsidian
│   │   ├── tech_note.py           # 生成技术笔记 → Obsidian
│   │   ├── weekend.py             # 加入周末队列
│   │   ├── ignore.py              # 忽略 + 负反馈记录
│   │   └── mark_read.py           # 标记已读 + Zotero tag
│   ├── feishu/
│   │   ├── __init__.py
│   │   ├── bot.py                 # 飞书 Bot 长连接服务主循环
│   │   ├── cards.py               # 飞书卡片 JSON 模板构建
│   │   ├── callbacks.py           # 按钮回调路由与分发
│   │   └── commands.py            # 文本命令处理 (本周总结等)
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite 连接、迁移、事务管理
│   │   ├── models.py              # dataclass 数据模型
│   │   └── queries.py             # 封装的查询方法
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── zotero_api.py          # Zotero local HTTP API 写入
│   │   ├── obsidian_writer.py     # Obsidian vault 文件写入
│   │   └── deepseek.py            # DeepSeek API 客户端封装
│   └── utils/
│       ├── __init__.py
│       ├── config.py              # YAML 配置加载与校验
│       └── logger.py              # 结构化日志
├── prompts/
│   ├── summarize.md.j2            # 摘要生成 prompt
│   ├── score.md.j2                # 打分 prompt
│   ├── interview_card.md.j2       # 面试卡生成 prompt
│   ├── tech_note.md.j2            # 技术笔记生成 prompt
│   └── expand.md.j2               # 展开详细摘要 prompt
├── data/
│   ├── workbench.db               # SQLite 主数据库
│   ├── raw/                       # 原始内容缓存
│   ├── reports/                   # 每日/每周日志
│   └── backups/                   # 周备份
├── scripts/
│   ├── install_launchd.sh         # 安装 launchd plist
│   ├── com.passive-agent.daily.plist
│   └── com.passive-agent.serve.plist
├── tests/
│   ├── conftest.py
│   ├── test_collectors/
│   ├── test_processors/
│   ├── test_actions/
│   └── fixtures/
├── pyproject.toml
├── design.md
└── technical_plan.md
```

---

## 3. 数据库详细设计

### 3.1 完整 Schema

```sql
-- 主表：所有收集到的条目
CREATE TABLE items (
    id TEXT PRIMARY KEY,                -- item_{YYYYMMDD}_{seq:03d}
    source TEXT NOT NULL,               -- zotero / obsidian_inbox / github_star
    title TEXT NOT NULL,
    url TEXT,
    local_path TEXT,
    zotero_key TEXT,
    collected_at TEXT NOT NULL,          -- ISO 8601
    content_type TEXT,                   -- paper / article / note / repo / doc
    topics TEXT,                         -- JSON array: ["Agent", "RAG"]
    stage TEXT NOT NULL DEFAULT 'new',   -- new/summarized/recommended/actioned/archived/ignored
    summary TEXT,
    interview_relevance TEXT,
    estimated_minutes INTEGER,
    priority_score REAL,
    recommended_action TEXT,             -- read / make_card / make_note / ignore
    ignored_count INTEGER DEFAULT 0,
    is_weekend INTEGER DEFAULT 0,
    raw_text TEXT,                       -- 收集时原始文本 (用于 inbox 行匹配)
    created_at TEXT NOT NULL,
    actioned_at TEXT
);

-- 各维度评分记录
CREATE TABLE scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id),
    goal_relevance REAL NOT NULL,
    novelty REAL NOT NULL,
    actionability REAL NOT NULL,
    difficulty_fit REAL NOT NULL,
    source_quality REAL NOT NULL,
    timeliness REAL NOT NULL,
    weighted_total REAL NOT NULL,
    scored_at TEXT NOT NULL
);

-- 用户操作反馈记录
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,                -- ignore / expand / card / note / weekend / read
    topic TEXT,
    source TEXT,
    created_at TEXT NOT NULL
);

-- Topic 动态权重
CREATE TABLE topic_weights (
    topic TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 1.0,
    last_updated_at TEXT,
    ignore_count_window INTEGER DEFAULT 0  -- 滑动窗口内忽略次数
);

-- Source 动态权重
CREATE TABLE source_weights (
    source TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 1.0,
    last_updated_at TEXT,
    ignore_count_window INTEGER DEFAULT 0
);

-- 每日运行日志
CREATE TABLE daily_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    collected_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    pushed_count INTEGER DEFAULT 0,
    user_actions TEXT,                   -- JSON: {"expand": 1, "card": 2, ...}
    errors TEXT,                         -- JSON array of error messages
    created_at TEXT NOT NULL
);

-- Zotero 写回待执行队列 (API 不可用时暂存)
CREATE TABLE zotero_write_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    executed_at TEXT                     -- NULL 表示待执行
);

-- 索引
CREATE INDEX idx_items_stage ON items(stage);
CREATE INDEX idx_items_collected_at ON items(collected_at);
CREATE INDEX idx_items_source ON items(source);
CREATE INDEX idx_items_topics ON items(topics);
CREATE INDEX idx_feedback_topic_time ON feedback(topic, created_at);
CREATE INDEX idx_feedback_source_time ON feedback(source, created_at);
CREATE INDEX idx_scores_item ON scores(item_id);
CREATE INDEX idx_daily_log_date ON daily_log(date);
```

### 3.2 ID 生成策略

```python
def generate_item_id(date: date, db: Database) -> str:
    """生成唯一 item ID: item_YYYYMMDD_NNN"""
    date_str = date.strftime("%Y%m%d")
    existing_count = db.count_items_by_date(date_str)
    return f"item_{date_str}_{existing_count + 1:03d}"
```

### 3.3 迁移策略

使用简单的版本号机制：`PRAGMA user_version` 记录当前 schema 版本，启动时检查并执行增量 DDL。

---

## 4. 核心模块设计

### 4.1 数据模型 (`src/storage/models.py`)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass
class Item:
    id: str
    source: Literal["zotero", "obsidian_inbox", "github_star"]
    title: str
    url: str | None = None
    local_path: str | None = None
    zotero_key: str | None = None
    collected_at: datetime = field(default_factory=datetime.now)
    content_type: Literal["paper", "article", "note", "repo", "doc"] | None = None
    topics: list[str] = field(default_factory=list)
    stage: str = "new"
    summary: str | None = None
    interview_relevance: str | None = None
    estimated_minutes: int | None = None
    priority_score: float | None = None
    recommended_action: str | None = None
    ignored_count: int = 0
    is_weekend: bool = False
    raw_text: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    actioned_at: datetime | None = None

@dataclass
class Score:
    item_id: str
    goal_relevance: float
    novelty: float
    actionability: float
    difficulty_fit: float
    source_quality: float
    timeliness: float
    weighted_total: float
    scored_at: datetime = field(default_factory=datetime.now)

@dataclass
class RawItem:
    """收集器输出的原始条目，尚未标准化"""
    source: str
    title: str
    url: str | None = None
    local_path: str | None = None
    zotero_key: str | None = None
    raw_text: str | None = None
    metadata: dict = field(default_factory=dict)

@dataclass
class EnrichedItem:
    """经过 Enrich 阶段的完整推荐条目"""
    item: Item
    score: Score
    related_zotero: list[str] = field(default_factory=list)
    related_stars: list[str] = field(default_factory=list)
```

### 4.2 Collector 协议 (`src/collectors/base.py`)

```python
from typing import Protocol

class Collector(Protocol):
    async def collect(self) -> list[RawItem]:
        """从数据源收集新条目"""
        ...

    def is_available(self) -> bool:
        """检查数据源是否可用"""
        ...
```

### 4.3 Zotero Collector (`src/collectors/zotero.py`)

```python
import sqlite3
from datetime import datetime, timedelta

class ZoteroCollector:
    def __init__(self, db_path: str, lookback_days: int = 7):
        self.db_path = db_path
        self.lookback_days = lookback_days

    def is_available(self) -> bool:
        return Path(self.db_path).exists()

    async def collect(self) -> list[RawItem]:
        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        try:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=30
            )
            conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError:
            # 数据库被锁定，返回空列表
            return []

        try:
            rows = conn.execute("""
                SELECT
                    i.key,
                    (SELECT value FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'title'
                    ) as title,
                    (SELECT value FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'abstractNote'
                    ) as abstract,
                    (SELECT value FROM itemData id
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'url'
                    ) as url,
                    i.dateAdded,
                    GROUP_CONCAT(DISTINCT t.name) as tags,
                    GROUP_CONCAT(DISTINCT c.collectionName) as collections
                FROM items i
                LEFT JOIN itemTags it ON i.itemID = it.itemID
                LEFT JOIN tags t ON it.tagID = t.tagID
                LEFT JOIN collectionItems ci ON i.itemID = ci.itemID
                LEFT JOIN collections c ON ci.collectionID = c.collectionID
                WHERE i.dateAdded > ?
                  AND i.itemTypeID NOT IN (
                      SELECT itemTypeID FROM itemTypes
                      WHERE typeName IN ('attachment', 'note')
                  )
                GROUP BY i.itemID
            """, (cutoff.isoformat(),))

            items = []
            for row in rows:
                if not row["title"]:
                    continue
                items.append(RawItem(
                    source="zotero",
                    title=row["title"],
                    url=row["url"],
                    zotero_key=row["key"],
                    metadata={
                        "abstract": row["abstract"],
                        "tags": row["tags"].split(",") if row["tags"] else [],
                        "collections": row["collections"].split(",") if row["collections"] else [],
                        "date_added": row["dateAdded"],
                    }
                ))
            return items
        finally:
            conn.close()
```

### 4.4 Obsidian Collector (`src/collectors/obsidian.py`)

```python
import re
from pathlib import Path

class ObsidianCollector:
    def __init__(self, inbox_path: str):
        self.inbox_path = Path(inbox_path)

    def is_available(self) -> bool:
        return self.inbox_path.exists()

    async def collect(self) -> list[RawItem]:
        content = self.inbox_path.read_text(encoding="utf-8")
        items = []

        for line in content.splitlines():
            line = line.strip()
            # 跳过空行、日期标题、已处理的行
            if not line or line.startswith("##") or line.endswith("✓"):
                continue
            # 跳过非列表项
            if not line.startswith("- "):
                continue

            text = line[2:]  # 去掉 "- " 前缀

            # 提取链接
            link_match = re.search(r'\[([^\]]+)\]\(([^)]+)\)', text)
            url = link_match.group(2) if link_match else None
            title = link_match.group(1) if link_match else text

            # 提取 tags
            tags = re.findall(r'#(\w+)', text)

            items.append(RawItem(
                source="obsidian_inbox",
                title=title,
                url=url,
                raw_text=line,  # 保留原始行文本用于后续标记
                metadata={"tags": tags, "full_text": text}
            ))

        return items
```

### 4.5 每日流水线 (`src/pipeline.py`)

```python
import asyncio
from datetime import date

class DailyPipeline:
    def __init__(self, config: AppConfig, db: Database, llm: DeepSeekClient):
        self.config = config
        self.db = db
        self.llm = llm
        self.collectors = self._init_collectors()
        self.normalizer = Normalizer()
        self.deduplicator = Deduplicator(db)
        self.summarizer = Summarizer(llm, config.goals)
        self.scorer = Scorer(llm, config.scoring, db)
        self.ranker = Ranker(db, config.scoring)

    async def run(self) -> PipelineResult:
        errors = []
        raw_items: list[RawItem] = []

        # 1. Collect — 各源独立，一个失败不影响其他
        for collector in self.collectors:
            if not collector.is_available():
                continue
            try:
                items = await collector.collect()
                raw_items.extend(items)
            except Exception as e:
                errors.append(f"{collector.__class__.__name__}: {e}")

        if not raw_items and not errors:
            # 无新内容，正常结束
            return PipelineResult(status="empty")

        if not raw_items and errors:
            # 所有源都失败
            await self._handle_all_failed(errors)
            return PipelineResult(status="error", errors=errors)

        # 2. Normalize
        items = self.normalizer.normalize(raw_items)

        # 3. Dedup
        new_items = self.deduplicator.filter(items)
        if not new_items:
            return PipelineResult(status="all_duplicates")

        # 4. Summarize (并发, 限流)
        summarized = await self.summarizer.summarize_batch(new_items)

        # 5. Score
        scored = await self.scorer.score_batch(summarized)

        # 6. Rank + Top N
        top_items = self.ranker.select_top(scored, limit=self.config.scoring.daily_limit)

        # 7. Enrich
        enriched = await self.ranker.enrich(top_items)

        # 8. 持久化
        self.db.save_items(scored)  # 保存所有已打分条目
        self.db.update_stages(top_items, "recommended")
        self.db.log_daily_run(date.today(), len(raw_items), len(new_items), len(top_items), errors)

        # 9. 输出
        return PipelineResult(
            status="success",
            recommended=enriched,
            collected=len(raw_items),
            processed=len(new_items),
            errors=errors
        )
```

### 4.6 去重器 (`src/processors/deduplicator.py`)

```python
from difflib import SequenceMatcher

class Deduplicator:
    TITLE_SIMILARITY_THRESHOLD = 0.85

    def __init__(self, db: Database):
        self.db = db

    def filter(self, items: list[Item]) -> list[Item]:
        existing_titles = self.db.get_all_titles()
        existing_urls = self.db.get_all_urls()
        result = []

        for item in items:
            # URL 精确匹配
            if item.url and item.url in existing_urls:
                continue

            # 标题模糊匹配 (处理无 URL 的 inbox 条目)
            if self._title_exists(item.title, existing_titles):
                continue

            result.append(item)
            existing_titles.add(item.title)
            if item.url:
                existing_urls.add(item.url)

        return result

    def _title_exists(self, title: str, existing: set[str]) -> bool:
        for existing_title in existing:
            ratio = SequenceMatcher(None, title.lower(), existing_title.lower()).ratio()
            if ratio >= self.TITLE_SIMILARITY_THRESHOLD:
                return True
        return False
```

### 4.7 打分器 (`src/processors/scorer.py`)

```python
class Scorer:
    def __init__(self, llm: DeepSeekClient, scoring_config: ScoringConfig, db: Database):
        self.llm = llm
        self.config = scoring_config
        self.db = db

    async def score_batch(self, items: list[Item]) -> list[Item]:
        # 获取已有面试卡标题 (供新颖性判断)
        existing_cards = self.db.get_archived_titles()
        # 获取 topic/source 当前权重
        topic_weights = self.db.get_topic_weights()
        source_weights = self.db.get_source_weights()

        tasks = [self._score_one(item, existing_cards) for item in items]
        scored_items = await asyncio.gather(*tasks)

        # 应用动态权重调整
        for item in scored_items:
            adjustment = self._calc_weight_adjustment(item, topic_weights, source_weights)
            item.priority_score *= adjustment

        return scored_items

    async def _score_one(self, item: Item, existing_cards: list[str]) -> Item:
        prompt = self._render_score_prompt(item, existing_cards)
        response = await self.llm.generate(
            system="你是一个面试准备助手，负责为内容打分。",
            user=prompt,
            response_format={"type": "json_object"}
        )
        scores = json.loads(response)

        score = Score(
            item_id=item.id,
            goal_relevance=scores["goal_relevance"],
            novelty=scores["novelty"],
            actionability=scores["actionability"],
            difficulty_fit=scores["difficulty_fit"],
            source_quality=scores["source_quality"],
            timeliness=scores["timeliness"],
            weighted_total=self._weighted_sum(scores),
        )
        item.priority_score = score.weighted_total
        self.db.save_score(score)
        return item

    def _weighted_sum(self, scores: dict) -> float:
        w = self.config.weights
        return (
            scores["goal_relevance"] * w.goal_relevance +
            scores["novelty"] * w.novelty +
            scores["actionability"] * w.actionability +
            scores["difficulty_fit"] * w.difficulty_fit +
            scores["source_quality"] * w.source_quality +
            scores["timeliness"] * w.timeliness
        )
```

### 4.8 LLM 客户端 (`src/integrations/deepseek.py`)

```python
import asyncio
from openai import AsyncOpenAI

class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = "deepseek-chat"
        self._semaphore = asyncio.Semaphore(5)  # 并发限制

    async def generate(self, system: str, user: str, response_format=None) -> str:
        async with self._semaphore:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

    async def batch_generate(self, requests: list[dict], concurrency: int = 5) -> list[str]:
        self._semaphore = asyncio.Semaphore(concurrency)
        tasks = [self.generate(**req) for req in requests]
        return await asyncio.gather(*tasks)
```

### 4.9 Zotero 写入集成 (`src/integrations/zotero_api.py`)

```python
import httpx

class ZoteroLocalAPI:
    BASE_URL = "http://localhost:23119/api/users/0"

    def __init__(self, db: Database):
        self.db = db

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.BASE_URL}/items?limit=1")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def add_tag(self, item_key: str, tag: str):
        if not await self.is_available():
            # API 不可用，入队待执行
            self.db.enqueue_zotero_write(item_key, tag)
            return

        async with httpx.AsyncClient() as client:
            # 获取 item 当前数据
            resp = await client.get(f"{self.BASE_URL}/items/{item_key}")
            if resp.status_code != 200:
                self.db.enqueue_zotero_write(item_key, tag)
                return

            item_data = resp.json()
            version = item_data["version"]
            tags = item_data["data"].get("tags", [])

            # 避免重复
            if any(t["tag"] == tag for t in tags):
                return

            tags.append({"tag": tag})

            # 写回
            patch_resp = await client.patch(
                f"{self.BASE_URL}/items/{item_key}",
                json={"tags": tags},
                headers={"If-Unmodified-Since-Version": str(version)}
            )
            if patch_resp.status_code != 204:
                self.db.enqueue_zotero_write(item_key, tag)

    async def flush_queue(self):
        """尝试执行队列中的待写入操作"""
        if not await self.is_available():
            return

        pending = self.db.get_pending_zotero_writes()
        for entry in pending:
            try:
                await self.add_tag(entry.item_key, entry.tag)
                self.db.mark_zotero_write_done(entry.id)
            except Exception:
                break  # API 又不可用了，停止
```

### 4.10 Obsidian 写入 (`src/integrations/obsidian_writer.py`)

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

class ObsidianWriter:
    def __init__(self, vault_path: str, prompts_dir: str):
        self.vault = Path(vault_path)
        self.jinja = Environment(loader=FileSystemLoader(prompts_dir))

    def write_interview_card(self, item: Item, card_content: str) -> Path:
        topic = self._primary_topic(item.topics)
        dir_path = self.vault / "01-Interview" / self._safe_dirname(topic)
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{self._safe_filename(item.title)}.md"
        file_path.write_text(card_content, encoding="utf-8")
        return file_path

    def write_tech_note(self, item: Item, note_content: str) -> Path:
        topic = self._primary_topic(item.topics)
        dir_path = self.vault / "03-Tech-Notes" / self._safe_dirname(topic)
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{self._safe_filename(item.title)}.md"
        file_path.write_text(note_content, encoding="utf-8")
        return file_path

    def mark_inbox_done(self, raw_text: str) -> bool:
        """在 inbox.md 中标记对应行为已处理，返回是否成功"""
        inbox_path = self.vault / "00-Inbox" / "inbox.md"
        if not inbox_path.exists():
            return False

        content = inbox_path.read_text(encoding="utf-8")
        target = raw_text.rstrip()

        if target not in content:
            return False  # 原始行已被编辑或删除，跳过

        if target + " ✓" in content:
            return True  # 已经标记过

        content = content.replace(target, target + " ✓", 1)
        inbox_path.write_text(content, encoding="utf-8")
        return True

    def _primary_topic(self, topics: list[str]) -> str:
        return topics[0] if topics else "General"

    def _safe_dirname(self, name: str) -> str:
        return name.replace("/", "-").replace(" ", "-")

    def _safe_filename(self, title: str) -> str:
        safe = "".join(c for c in title if c.isalnum() or c in " -_（）()").strip()
        return safe[:80]  # 限制文件名长度
```

### 4.11 负反馈引擎 (`src/processors/scorer.py` 内)

```python
class FeedbackEngine:
    """滑动窗口负反馈权重计算"""

    def __init__(self, db: Database, config: NegativeFeedbackConfig):
        self.db = db
        self.config = config

    def update_on_ignore(self, item: Item):
        """记录忽略操作并更新权重"""
        for topic in item.topics:
            self._update_topic_weight(topic)
        self._update_source_weight(item.source)

    def _update_topic_weight(self, topic: str):
        # 查看最近 10 次该 topic 的推荐中忽略次数
        recent = self.db.get_recent_feedback_for_topic(topic, window=10)
        ignore_count = sum(1 for f in recent if f.action == "ignore")

        if ignore_count >= self.config.topic_threshold:
            current = self.db.get_topic_weight(topic)
            new_weight = max(
                current * (1 - self.config.topic_penalty),
                self.config.min_weight
            )
            self.db.set_topic_weight(topic, new_weight)

    def _update_source_weight(self, source: str):
        recent = self.db.get_recent_feedback_for_source(source, window=15)
        ignore_count = sum(1 for f in recent if f.action == "ignore")

        if ignore_count >= self.config.source_threshold:
            current = self.db.get_source_weight(source)
            new_weight = max(
                current * (1 - self.config.source_penalty),
                self.config.min_weight
            )
            self.db.set_source_weight(source, new_weight)

    def recover_weights(self):
        """每 30 天自然恢复权重，由 daily pipeline 调用"""
        self.db.recover_stale_topic_weights(
            days=self.config.recovery_days,
            rate=self.config.recovery_rate
        )
        self.db.recover_stale_source_weights(
            days=self.config.recovery_days,
            rate=self.config.recovery_rate
        )
```

---

## 5. 飞书 Bot 设计

### 5.1 服务入口 (`src/feishu/bot.py`)

```python
import lark_oapi as lark
from lark_oapi.adapter.websocket import WebSocketClient

class FeishuBot:
    def __init__(self, app_id: str, app_secret: str, db: Database, llm: DeepSeekClient):
        self.app_id = app_id
        self.app_secret = app_secret
        self.db = db
        self.llm = llm
        self.action_dispatcher = ActionDispatcher(db, llm)
        self.command_handler = CommandHandler(db)

    def start(self):
        """启动飞书长连接 Bot"""
        event_handler = (
            lark.EventDispatcherHandler.builder("")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )

        cli = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .build()

        ws_cli = WebSocketClient(cli, event_handler, card_handler=self._on_card_action)
        ws_cli.start()

    async def _on_card_action(self, data: dict) -> dict:
        """飞书卡片按钮回调"""
        action_value = data["action"]["value"]
        # action_value 格式: {"action": "expand", "item_id": "item_20260522_001"}
        result = await self.action_dispatcher.dispatch(
            action=action_value["action"],
            item_id=action_value["item_id"]
        )
        # 返回卡片更新或新消息
        return result.to_feishu_response()

    async def _on_message(self, data):
        """处理文本消息 (固定关键词命令)"""
        text = self._extract_text(data)
        response = await self.command_handler.handle(text)
        await self._reply(data, response)

    async def send_daily_card(self, items: list[EnrichedItem]):
        """发送每日推荐卡片"""
        card_json = CardBuilder.build_daily_card(items)
        # 发送到指定用户/群
        ...

    async def send_error_notification(self, error: str, impact: str):
        """发送错误通知"""
        ...
```

### 5.2 卡片构建 (`src/feishu/cards.py`)

```python
class CardBuilder:
    @staticmethod
    def build_daily_card(items: list[EnrichedItem]) -> dict:
        """构建每日推荐卡片 JSON"""
        elements = []

        for i, enriched in enumerate(items, 1):
            item = enriched.item
            elements.append({
                "tag": "markdown",
                "content": (
                    f"**{i}. {item.title}**\n"
                    f"来源：{item.source} · 预计 {item.estimated_minutes} 分钟\n"
                    f"面试价值：{item.interview_relevance}"
                )
            })

            # 相关 star 提示
            if enriched.related_stars:
                stars_text = ", ".join(enriched.related_stars[:3])
                elements.append({
                    "tag": "markdown",
                    "content": f"相关：你 star 过 {stars_text}"
                })

            # 操作按钮
            elements.append({
                "tag": "action",
                "actions": [
                    _button("展开", {"action": "expand", "item_id": item.id}),
                    _button("面试卡", {"action": "interview_card", "item_id": item.id}),
                    _button("周末", {"action": "weekend", "item_id": item.id}),
                    _button("忽略", {"action": "ignore", "item_id": item.id}, danger=True),
                ]
            })

            elements.append({"tag": "hr"})

        # 相关旧文章附带提示
        # ...

        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"今日推荐 · {date.today().strftime('%m月%d日')}"}},
            "elements": elements
        }
```

### 5.3 回调分发 (`src/feishu/callbacks.py`)

```python
class ActionDispatcher:
    def __init__(self, db: Database, llm: DeepSeekClient):
        self.actions = {
            "expand": ExpandAction(db, llm),
            "interview_card": InterviewCardAction(db, llm),
            "tech_note": TechNoteAction(db, llm),
            "weekend": WeekendAction(db),
            "ignore": IgnoreAction(db),
            "mark_read": MarkReadAction(db),
        }

    async def dispatch(self, action: str, item_id: str) -> ActionResult:
        handler = self.actions.get(action)
        if not handler:
            return ActionResult.error(f"未知操作: {action}")
        return await handler.execute(item_id)
```

---

## 6. CLI 入口设计

```python
# src/main.py
import click
import asyncio

@click.group()
def cli():
    """Passive Agent Workbench"""
    pass

@cli.command()
def daily():
    """运行每日处理流水线 (launchd 调用或手动触发)"""
    config = load_config()
    db = Database(config.db_path)
    llm = DeepSeekClient(config.deepseek_api_key)
    pipeline = DailyPipeline(config, db, llm)
    result = asyncio.run(pipeline.run())
    # Phase 1: 输出到本地文件
    # Phase 2+: 通过飞书推送
    output_result(result, config)

@cli.command()
def serve():
    """启动飞书 Bot 常驻服务"""
    config = load_config()
    db = Database(config.db_path)
    llm = DeepSeekClient(config.deepseek_api_key)
    bot = FeishuBot(config.feishu_app_id, config.feishu_app_secret, db, llm)
    bot.start()

@cli.command()
@click.argument("item_id")
@click.option("--type", "action_type", type=click.Choice(["card", "note", "ignore", "read"]))
def action(item_id: str, action_type: str):
    """Phase 1: 手动执行 action (CLI 模式)"""
    config = load_config()
    db = Database(config.db_path)
    llm = DeepSeekClient(config.deepseek_api_key)
    dispatcher = ActionDispatcher(db, llm)
    result = asyncio.run(dispatcher.dispatch(action_type, item_id))
    click.echo(result.message)

@cli.command("init-stars")
def init_stars():
    """一次性导入 GitHub Stars"""
    config = load_config()
    db = Database(config.db_path)
    llm = DeepSeekClient(config.deepseek_api_key)
    initializer = GitHubStarsInitializer(db, llm)
    asyncio.run(initializer.run())

if __name__ == "__main__":
    cli()
```

---

## 7. Prompt 设计

### 7.1 摘要生成 (`prompts/summarize.md.j2`)

```
你是一个面试准备助手。用户正在准备 Agent 算法岗面试。

请分析以下内容，回答：这篇内容能帮用户回答哪个面试问题？

## 内容信息

标题：{{ item.title }}
来源：{{ item.source }}
{% if item.metadata.abstract %}摘要：{{ item.metadata.abstract }}{% endif %}
{% if item.url %}链接：{{ item.url }}{% endif %}
{% if item.metadata.tags %}标签：{{ item.metadata.tags | join(', ') }}{% endif %}

## 当前关注方向

{{ goals.priority_topics | join('\n- ') }}

## 输出要求 (严格 JSON)

{
  "one_line": "一句话定位这篇内容",
  "interview_relevance": "能帮用户回答什么面试问题（具体到问题）",
  "recommended_action": "read / make_card / make_note / ignore",
  "estimated_minutes": 20,
  "topics": ["Agent", "Tool Calling"],
  "content_type": "paper / article / note / repo / doc"
}
```

### 7.2 打分 (`prompts/score.md.j2`)

```
为以下内容的面试准备价值打分，每个维度 0-100：

## 内容

标题：{{ item.title }}
摘要：{{ item.summary }}
面试关联：{{ item.interview_relevance }}
来源类型：{{ item.source }}
内容类型：{{ item.content_type }}

## 已有面试卡标题 (用于判断新颖性)

{% for title in existing_cards[-20:] %}
- {{ title }}
{% endfor %}

## 打分维度

1. goal_relevance: 是否和 Agent 岗面试直接相关
2. novelty: 是否是上面已有卡片没有覆盖的新内容
3. actionability: 能否转化为面试回答、demo、代码
4. difficulty_fit: 是否适合 30 分钟内消化
5. source_quality: 官方文档/源码/论文 > 泛泛博客
6. timeliness: 近期发布/更新的内容优先

## 输出 (严格 JSON)

{
  "goal_relevance": 85,
  "novelty": 70,
  "actionability": 90,
  "difficulty_fit": 75,
  "source_quality": 80,
  "timeliness": 60
}
```

### 7.3 面试卡生成 (`prompts/interview_card.md.j2`)

```
基于以下内容，生成一张面试问答卡片。

## 原始内容

标题：{{ item.title }}
摘要：{{ item.summary }}
面试关联：{{ item.interview_relevance }}
{% if expanded_content %}详细内容：{{ expanded_content }}{% endif %}

## 输出格式 (Markdown)

---
type: interview-card
topic: [{{ item.topics | join(', ') }}]
source: {{ item.title }}
source_url: {{ item.url or '' }}
created: {{ today }}
---

# {一个具体的面试问题}

## 一句话答案

{30 秒内能说清的精炼回答}

## 展开回答

1. {要点一}
2. {要点二}
3. {要点三}

## 追问预判

- Q: {可能的追问 1}
  A: {回答}
- Q: {可能的追问 2}
  A: {回答}

## 关键细节

{技术细节、数据、源码要点}

## 原文要点

{从原文提取的核心论据}
```

---

## 8. 部署与运维

### 8.1 launchd 配置

**每日流水线** (`scripts/com.passive-agent.daily.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.passive-agent.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/zhuyijie/Documents/Code/PassiveAgent/.venv/bin/python</string>
        <string>-m</string>
        <string>src.main</string>
        <string>daily</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>21</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent</string>
    <key>StandardOutPath</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent/data/reports/daily_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent/data/reports/daily_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

**飞书 Bot 常驻服务** (`scripts/com.passive-agent.serve.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.passive-agent.serve</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/zhuyijie/Documents/Code/PassiveAgent/.venv/bin/python</string>
        <string>-m</string>
        <string>src.main</string>
        <string>serve</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent</string>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent/data/reports/serve_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/zhuyijie/Documents/Code/PassiveAgent/data/reports/serve_stderr.log</string>
</dict>
</plist>
```

**周六推送** (`scripts/com.passive-agent.weekend.plist`):

```xml
<!-- 每周六 10:00 触发周末队列推送 -->
<key>StartCalendarInterval</key>
<dict>
    <key>Weekday</key>
    <integer>6</integer>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

### 8.2 安装脚本 (`scripts/install_launchd.sh`)

```bash
#!/bin/bash
set -e

PLIST_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for plist in "$SCRIPT_DIR"/com.passive-agent.*.plist; do
    name=$(basename "$plist")
    cp "$plist" "$PLIST_DIR/$name"
    launchctl load "$PLIST_DIR/$name"
    echo "Loaded: $name"
done
```

### 8.3 备份策略

在每日流水线末尾附加备份逻辑：

```python
def weekly_backup(db_path: str, backup_dir: str):
    """每周日执行 SQLite 备份，保留最近 4 份"""
    if date.today().weekday() != 6:  # 仅周日
        return

    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    dest = backup_path / f"workbench_{date.today().isoformat()}.db"
    shutil.copy2(db_path, dest)

    # 清理旧备份，保留最近 4 份
    backups = sorted(backup_path.glob("workbench_*.db"), reverse=True)
    for old in backups[4:]:
        old.unlink()
```

---

## 9. 容错与重试

### 9.1 错误处理矩阵

| 组件 | 错误类型 | 处理方式 |
|------|---------|---------|
| ZoteroCollector | SQLite locked | 等待 10s 重试，3 次后跳过 |
| ZoteroCollector | 文件不存在 | 跳过该源，记录 warning |
| ObsidianCollector | inbox.md 为空/不存在 | 正常返回空列表 |
| DeepSeekClient | API timeout | 指数退避重试 (2s, 4s, 8s)，3 次后标记失败 |
| DeepSeekClient | Rate limit (429) | 按 retry-after header 等待 |
| DeepSeekClient | 全部条目处理失败 | 推送错误通知，次日补推 |
| ZoteroLocalAPI | Connection refused | 入队 zotero_write_queue，下次重试 |
| FeishuBot | WebSocket 断连 | SDK 内置重连；超过 5 分钟推送告警日志 |
| Pipeline | 部分条目打分失败 | 跳过失败条目，从成功的中选 Top N |

### 9.2 补推逻辑

```python
async def check_pending_catchup(self) -> list[Item]:
    """检查是否有昨日失败需要补推的内容"""
    yesterday = date.today() - timedelta(days=1)
    log = self.db.get_daily_log(yesterday)

    if log and log.pushed_count == 0 and log.errors:
        # 昨日推送失败，获取昨日已打分但未推送的条目
        pending = self.db.get_items_by_date_and_stage(yesterday, "summarized")
        return pending[:2]  # 最多补推 2 条，与今日 3 条合并为最多 5 条

    return []
```

---

## 10. 分阶段实施计划

### Phase 1: 本地验证 (1-2 周)

**目标**：验证 "每日 3 条推荐 + 面试卡生成" 的核心价值。

**实现范围**：

| 天数 | 任务 | 交付物 |
|------|------|--------|
| D1-D2 | 项目骨架 + SQLite schema + 配置加载 | 可运行的 CLI 框架 |
| D3 | ZoteroCollector + ObsidianCollector | 能从两个源收集数据 |
| D4 | Normalizer + Deduplicator | 统一格式 + 去重 |
| D5-D6 | DeepSeek 集成 + Summarizer + Scorer | LLM 摘要和打分 |
| D7 | Ranker + 本地输出 (daily_review.md) | 完整 daily 命令 |
| D8-D9 | InterviewCardAction + TechNoteAction | CLI 生成面试卡/笔记 |
| D10 | 端到端测试 + 修复 | 稳定可用的 Phase 1 |

**Phase 1 输出方式**：

```python
def output_local(result: PipelineResult, output_dir: str):
    """Phase 1: 输出到本地 Markdown 文件"""
    path = Path(output_dir) / f"daily_review_{date.today().isoformat()}.md"
    content = render_daily_review(result.recommended)
    path.write_text(content, encoding="utf-8")
```

**Phase 1 验证标准**：

- 连续 5 天推荐中，≥ 60% 的条目愿意进一步处理
- 生成的面试卡可直接用于复习
- 每日运行耗时 < 2 分钟
- LLM 调用成本 < 0.5 元/天

### Phase 2: 飞书接入 (1 周)

**新增**：
- 飞书自建应用配置
- 卡片模板构建 (`src/feishu/cards.py`)
- 按钮回调处理 (`src/feishu/callbacks.py`)
- Bot 常驻服务 (`src/feishu/bot.py`)
- Zotero local API 写回 (`src/integrations/zotero_api.py`)
- launchd 部署

### Phase 3: 闭环完善 (1-2 周)

**新增**：
- 负反馈引擎 (滑动窗口)
- 周末队列 + 周六推送
- 72 小时未操作提醒 (在 daily 流水线中检查)
- GitHub Stars 被动索引 (Ranker.enrich)
- Zotero 旧文章被动激活
- 文本命令处理 (本周总结等)
- 权重自然恢复 (daily 流水线中检查)

---

## 11. 关键设计决策记录

| 决策 | 选择 | 替代方案 | 理由 |
|------|------|---------|------|
| Zotero 写回方式 | Local HTTP API | 直接写 SQLite | 避免数据库损坏 |
| Inbox 行标记 | 内容匹配 | 行号 | 抗编辑竞态 |
| 新颖性判断 | 基于已有卡片标题列表 | Embedding 相似度 | Phase 1 简单有效，Phase 4 升级 |
| 去重策略 | URL精确 + 标题模糊 | LLM 语义去重 | 成本低、速度快 |
| 负反馈计数 | 滑动窗口 | 严格连续 | 更合理，避免一次操作重置历史 |
| GitHub Stars 分类 | 规则优先 + LLM 兜底 | 全 LLM | 控制初始化成本 |
| 飞书交互 | 卡片按钮 | 自然语言 | 无歧义，更快 |
| 周六推送触发 | 独立 launchd | Bot 内 asyncio 定时 | 更可靠，不依赖 Bot 进程存活时间 |

---

## 12. 依赖与环境

### 12.1 pyproject.toml

```toml
[project]
name = "passive-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.30",
    "lark-oapi>=1.3",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "click>=8.1",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
passive-agent = "src.main:cli"
```

### 12.2 环境变量

```bash
DEEPSEEK_API_KEY=sk-xxx           # DeepSeek API key
FEISHU_APP_ID=cli_xxx             # 飞书应用 ID
FEISHU_APP_SECRET=xxx             # 飞书应用 Secret
PASSIVE_AGENT_CONFIG=/path/to/config  # 配置目录 (可选，默认 ./config)
```

### 12.3 Mac mini 前置检查

- [ ] Python 3.11+ 已安装
- [ ] Zotero 桌面版已安装并运行
- [ ] Obsidian Vault 目录存在且 inbox.md 可访问
- [ ] `gh` CLI 已登录 (用于 Stars 初始化)
- [ ] 系统偏好设置 → 节能 → 永不休眠
- [ ] 飞书开放平台已创建自建应用，获取 App ID / Secret
