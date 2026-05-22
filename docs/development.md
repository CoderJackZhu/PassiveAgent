# Development Guide

## 环境搭建

```bash
# 克隆项目
git clone https://github.com/CoderJackZhu/PassiveAgent.git
cd PassiveAgent

# 安装依赖（使用 uv）
uv sync --all-extras

# 或使用 pip
pip install -e ".[dev]"
```

## 运行测试

```bash
pytest tests/ -v
```

## 项目约定

### 代码结构

- `collectors/` — 数据源采集器，每个实现 `Collector` 基类的 `is_available()` + `collect()` 方法
- `processors/` — 处理链：Normalizer → Deduplicator → Scorer → Summarizer → Ranker
- `actions/` — 用户操作处理器，每个实现 `BaseAction.execute(item_id)` 方法
- `integrations/` — 外部服务集成（DeepSeek LLM, Obsidian 写入, Zotero 回写）
- `feishu/` — 飞书 Bot 长连接 + 回调处理

### 数据流

```
RawItem (采集器输出)
    ↓ Normalizer
Item (标准化，入库)
    ↓ Deduplicator
Item (去重后)
    ↓ Scorer + Summarizer
Item (带评分和摘要)
    ↓ Ranker
Item (排序后 Top N)
    ↓ 推送
```

### 数据库

- SQLite WAL 模式，schema 版本通过 `PRAGMA user_version` 管理
- 迁移逻辑在 `Database.initialize()` 中，使用 `ALTER TABLE ... ADD COLUMN` 增量升级
- 当前 schema version: 3

### Prompt 模板

使用 Jinja2 模板，存放在 `prompts/` 目录：

| 模板 | 用途 |
|------|------|
| `summarize.md.j2` | 生成条目摘要 |
| `score.md.j2` | 多维度评分 |
| `interview_card.md.j2` | 生成面试卡片 |
| `tech_note.md.j2` | 生成技术笔记 |

### 配置

- 用户配置在项目根目录 `config.yaml`，通过 `.gitignore` 排除
- 提供 `config.yaml.example` 作为模板
- 配置加载逻辑在 `utils/config.py`，使用 dataclass 做类型安全

## 添加新数据源

1. 在 `collectors/` 中创建新文件，实现 `Collector` 基类
2. 在 `config.py` 中添加对应的 dataclass 配置
3. 在 `config.yaml.example` 的 `sources` 部分添加示例
4. 在 `pipeline.py` 中注册采集器

## 添加新用户操作

1. 在 `actions/` 中创建新文件，继承 `BaseAction`
2. 实现 `execute(item_id) -> ActionResult`
3. 在 `main.py` 的 `action` 命令中注册
4. 如需飞书交互，在 `feishu/commands.py` 中添加回调处理
