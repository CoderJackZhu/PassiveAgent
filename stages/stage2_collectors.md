# Stage 2: 数据收集 + 标准化 + 去重

## 前置依赖

Stage 1 完成（项目骨架 + DB + 配置可用）

## 目标

能从 Zotero 和 Obsidian 收集真实数据，标准化后去重存入 SQLite。

## 交付物

- ZoteroCollector (只读 SQLite)
- ObsidianCollector (解析 inbox.md)
- Normalizer (RawItem → Item)
- Deduplicator (标题+URL / 模糊匹配)
- Pipeline 接入 collect → normalize → dedup → save 流程

## 验证标准

```bash
uv run passive-agent daily
# 输出: "Collected 5 items from zotero, 3 from obsidian. After dedup: 7 new items."
# data/workbench.db 中 items 表有真实数据

uv run pytest tests/test_collectors/
```

## 详细任务

### 1. Collector 协议

```python
# src/passive_agent/collectors/base.py
class Collector(Protocol):
    async def collect(self) -> list[RawItem]: ...
    def is_available(self) -> bool: ...
```

### 2. ZoteroCollector

- 以 `?mode=ro` 只读打开 zotero.sqlite
- 超时 30s，锁定时重试 3 次（间隔 10s）
- 查询最近 N 天新增（排除 attachment/note 类型）
- 提取 title, url, abstract, tags, collections, dateAdded

### 3. ObsidianCollector

- 读取 inbox.md
- 跳过空行、日期标题行 (##)、已标记行 (末尾有 ✓)
- 解析链接 `[title](url)` 和 `#tag`
- 保存 raw_text 用于后续标记

### 4. Normalizer

- RawItem → Item (生成 ID, 设置 stage="new", 填充 collected_at)
- ID 格式: item_{YYYYMMDD}_{NNN}

### 5. Deduplicator

- 有 URL: 精确匹配 existing URLs
- 无 URL: SequenceMatcher 模糊匹配标题 (threshold=0.85)
- 批内去重 + 与 DB 已有条目去重

### 6. Pipeline 集成

pipeline.run() 执行 collect → normalize → dedup → db.save_items()
此阶段 summarize/score/rank 为 pass-through（直接保存 stage="new"）
