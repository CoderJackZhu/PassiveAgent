# Stage 1: 项目骨架 + 配置 + DB + 数据模型

## 目标

建立可运行的项目框架，`passive-agent daily` 命令可以空跑通过。

## 交付物

- uv 管理的 Python 项目
- 配置文件加载 (goals.yaml / sources.yaml / scoring.yaml)
- SQLite 数据库初始化与迁移
- 数据模型 (dataclass)
- CLI 入口 (click)
- 基础日志

## 验证标准

```bash
uv run passive-agent daily   # 输出 "No collectors configured" 或类似空跑提示
uv run passive-agent --help  # 展示所有子命令
uv run pytest                # 配置/DB 相关测试通过
```

## 详细任务

### 1. 项目初始化

```
PassiveAgent/
├── pyproject.toml          # uv 项目配置
├── config/
│   ├── goals.yaml
│   ├── sources.yaml
│   └── scoring.yaml
├── src/
│   └── passive_agent/
│       ├── __init__.py
│       ├── main.py         # CLI 入口
│       ├── pipeline.py     # 流水线骨架 (空实现)
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── database.py
│       │   └── models.py
│       └── utils/
│           ├── __init__.py
│           ├── config.py
│           └── logger.py
├── prompts/                # 空目录，后续阶段填充
├── data/                   # 运行时数据目录
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   └── test_database.py
└── stages/                 # 实施文档
```

### 2. pyproject.toml

```toml
[project]
name = "passive-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.30",
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
passive-agent = "passive_agent.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3. 配置文件

三个 YAML 文件按 design.md 第 9 节定义，config.py 负责加载和校验。

### 4. SQLite Schema

按 technical_plan.md 第 3.1 节的完整 schema 建表。使用 `PRAGMA user_version` 管理版本。

### 5. 数据模型

- Item, Score, RawItem, EnrichedItem (dataclass)
- 序列化/反序列化方法 (to_dict / from_row)

### 6. CLI

- `passive-agent daily` — 调用 pipeline.run()（此阶段为空跑）
- `passive-agent init-db` — 初始化数据库
- `passive-agent --help`
