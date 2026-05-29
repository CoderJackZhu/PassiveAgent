# Passive Agent Workbench

> 每天从 Zotero、Obsidian、HuggingFace Daily、GitHub Stars 里挑出少量真正值得看的内容，并推送到飞书或在终端里查看。

信息过载时，问题通常不是"没有资料"，而是"不知道今天先看哪几个"。Passive Agent 会帮你完成：采集 → 去重 → 摘要 → 打分 → 推荐 → 反馈降权。

```text
资料来源 → 去重 → LLM 摘要/打分 → Top N 推荐 → 你选择：看 / 忽略 / 周末读 / 生成卡片
```

## 适合谁

- 你有一堆论文、文章、GitHub 项目，但每天只想看最重要的 3 个。
- 你在准备 Agent / LLM / 算法工程相关面试，需要持续积累高价值材料。
- 你希望"少推类似"这种反馈能影响后续推荐，而不是每天重复刷到不想看的东西。

## 5 分钟跑起来

### 1. 安装依赖

```bash
git clone https://github.com/CoderJackZhu/PassiveAgent.git
cd PassiveAgent
uv sync
```

后续命令都用 `uv run passive-agent ...`。如果你已经 `source .venv/bin/activate`，也可以直接用 `passive-agent ...`。

### 2. 创建配置文件

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

打开 `.env` 填一个 LLM API Key（任何 OpenAI 兼容的 API 均可）：

```bash
XIAOMI_API_KEY=你的_key
XIAOMI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
```

默认使用小米 MiMo 模型。如需切换其他 OpenAI 兼容服务，修改 `config.yaml` 的 `llm` 部分即可（详见 [docs/configuration.md](docs/configuration.md#llm-部分)）。

### 3. 初始化数据库

```bash
uv run passive-agent init-db
```

### 4. 跑一次每日推荐

```bash
uv run passive-agent daily
```

### 5. 查看结果

```bash
uv run passive-agent status
uv run passive-agent dashboard
uv run passive-agent list --stage recommended
```

如果这些命令能看到推荐条目，说明本地流程已经跑通。

## 日常命令

| 你想做什么 | 命令 |
|---|---|
| 跑一次完整推荐流程 | `uv run passive-agent daily` |
| 看系统状态 | `uv run passive-agent status` |
| 看终端看板 | `uv run passive-agent dashboard` |
| 看推荐列表 | `uv run passive-agent list --stage recommended` |
| 把某条变成面试卡 | `uv run passive-agent action <item_id> --type card` |
| 忽略某条并记录负反馈 | `uv run passive-agent action <item_id> --type ignore` |
| 加入周末深读 | `uv run passive-agent action <item_id> --type weekend` |
| 生成本周周报 | `uv run passive-agent weekly-report` |

`<item_id>` 可以从 `list --stage recommended` 或 `dashboard` 里看到。

## 数据来源

| 来源 | 默认状态 | 说明 |
|---|---:|---|
| Zotero | 开启 | 读取本地 `~/Zotero/zotero.sqlite`，适合论文和长期资料库。 |
| HuggingFace Daily Papers | 开启 | 拉取近期 HF Daily Papers。 |
| Obsidian Inbox | 关闭 | 适合临时丢 URL，格式见 [docs/configuration.md](docs/configuration.md#obsidian)。 |
| GitHub Stars | 关闭 | 需要 `GITHUB_TOKEN` 手动导入：`uv run passive-agent init-stars`。 |

## 配置怎么改

大部分用户只需要改 3 个地方。完整配置参考：[docs/configuration.md](docs/configuration.md)。

### 1. 当前目标

```yaml
goals:
  current_focus: "Agent 算法岗面试准备"
  priority_topics:
    - Agent 架构与工程
    - Tool Calling
    - RAG 与评测
```

### 2. 数据源开关

```yaml
sources:
  zotero:
    enabled: false
  obsidian:
    enabled: true
    inbox_path: "~/ObsidianVault/00-Inbox/inbox.md"
```

### 3. 每天推几条

```yaml
scoring:
  daily_limit: 3
  weekend_limit: 5
```

## 进阶

| 文档 | 内容 |
|---|---|
| [飞书接入](docs/feishu.md) | 主动推送、长连接服务、权限配置 |
| [定时任务](docs/scheduled-tasks.md) | macOS LaunchAgent 安装和管理 |
| [完整配置参考](docs/configuration.md) | 所有 YAML 字段和环境变量说明 |
| [踩坑速查](docs/troubleshooting.md) | 常见问题和解决方法 |
| [开发指南](docs/development.md) | 代码结构、数据流、如何添加新功能 |

## 项目结构

```text
PassiveAgent/
├── config.yaml.example      # 配置模板
├── .env.example             # 环境变量模板，不提交真实密钥
├── prompts/                 # LLM prompt 模板
├── docs/                    # 详细文档
├── scripts/                 # launchd 安装脚本和 plist 模板
├── src/passive_agent/
│   ├── main.py              # CLI 入口
│   ├── pipeline.py          # 每日处理流水线
│   ├── collectors/          # 数据采集器
│   ├── processors/          # 去重 / 摘要 / 打分 / 排序
│   ├── actions/             # 用户操作处理
│   ├── feishu/              # 飞书 Bot
│   └── storage/             # SQLite 数据库和模型
└── tests/
```

## 开发

```bash
uv sync --all-extras
uv run pytest tests/ -v
```

技术栈：Python 3.11+、SQLite、Click、Jinja2、OpenAI-compatible LLM API、飞书开放平台。

## License

MIT
