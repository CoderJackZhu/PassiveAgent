# Passive Agent Workbench

个人注意力调度系统 — 从信息池中筛选高价值内容，碎片时间 review，确认后沉淀为可复用知识。

## 解决什么问题

信息过载不是缺资料，而是不知道先看什么。本系统每天从 Zotero、Obsidian、GitHub Stars 中自动筛选少量高价值条目推送给你，你只需碎片时间做一个决策（生成卡片 / 忽略 / 加入周末），系统负责执行和归档。

## 核心流程

```
Zotero / Obsidian / GitHub Stars
        ↓
   采集 + 去重
        ↓
  LLM 摘要 + 打分
        ↓
   Top N 推送（飞书）
        ↓
  你回复：卡片 / 忽略 / 周末
        ↓
   系统执行 + 归档
```

## 快速开始

### 1. 安装

```bash
git clone https://github.com/CoderJackZhu/PassiveAgent.git
cd PassiveAgent
uv sync
```

### 2. 配置

复制示例配置并按需修改：

```bash
cp config.yaml.example config.yaml
```

### 3. 环境变量

```bash
export DEEPSEEK_API_KEY="your-key"          # LLM 摘要/打分（必需）
export GITHUB_TOKEN="your-token"            # GitHub Stars 导入（可选）
export ZOTERO_API_KEY="your-key"            # Zotero tag 回写（可选）
export FEISHU_APP_ID="your-app-id"          # 飞书推送（可选）
export FEISHU_APP_SECRET="your-secret"      # 飞书推送（可选）
```

### 4. 初始化

```bash
passive-agent init-db
```

### 5. 运行每日 pipeline

```bash
passive-agent daily
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `daily` | 运行每日采集-处理-推送流水线 |
| `status` | 查看系统状态（各阶段条目数） |
| `list --stage recommended` | 列出指定阶段的条目 |
| `action <id> --type card` | 对条目执行操作 |
| `init-stars [--refresh]` | 导入/刷新 GitHub Stars |
| `list-stars [--topic X] [--language Y] [--sort stars]` | 查看已导入的 Stars |
| `export-stars [--output path]` | 导出 Stars 为 Markdown |
| `weekly-report` | 生成本周周报 |
| `weekend-push` | 推送周末阅读队列 |
| `zotero-writeback [--execute]` | Zotero tag 回写（默认 dry-run） |
| `serve` | 启动飞书 Bot 长连接服务 |
| `init-db` | 初始化数据库 |

## 用户操作

对推荐条目可执行 8 种操作：

| 操作 | CLI type | 说明 |
|------|----------|------|
| 生成面试卡 | `card` | 生成 Q&A 结构的面试准备卡片 |
| 生成技术笔记 | `note` | 生成结构化技术笔记 |
| 标记已读 | `read` | 标记为已处理 |
| 忽略 | `ignore` | 移除 + 记录负反馈 |
| 少推类似 | `mute` | 降低该主题/来源权重 |
| 加入周末 | `weekend` | 放入周末深度阅读队列 |
| 关联笔记 | `link` | 搜索 Obsidian 中相关笔记 |

示例：

```bash
passive-agent action item_20260522_001 --type card
passive-agent action item_20260522_002 --type weekend
```

## 数据源配置

所有配置集中在项目根目录的 `config.yaml` 中，按 `goals` / `sources` / `scoring` 三个顶层 key 区分。详见 [docs/configuration.md](docs/configuration.md)。

```yaml
# config.yaml 结构概览
goals:
  current_focus: "Agent 算法岗面试准备"
  priority_topics: [...]
  output_preference: "interview_card"

sources:
  zotero:
    enabled: true
    db_path: "~/Zotero/zotero.sqlite"
    ...
  obsidian:
    enabled: true
    inbox_path: "~/ObsidianVault/00-Inbox/inbox.md"
    ...
  github_stars:
    enabled: true

scoring:
  weights: { goal_relevance: 0.30, ... }
  daily_limit: 5
  negative_feedback: { ... }
```

GitHub Stars 用法：

```bash
GITHUB_TOKEN=xxx passive-agent init-stars        # 首次导入
GITHUB_TOKEN=xxx passive-agent init-stars --refresh  # 刷新元数据
passive-agent list-stars --topic Agent --sort stars  # 查看
passive-agent export-stars                           # 导出 Markdown
```

## 评分机制

系统通过 6 个维度对条目打分，只有高分条目才会被推荐：

| 维度 | 权重 | 说明 |
|------|------|------|
| 目标相关性 | 30% | 是否与当前 focus 强相关 |
| 新颖性 | 20% | 是否为已有知识中没有的 |
| 可操作性 | 20% | 能否转化为代码/卡片/回答 |
| 难度适配 | 10% | 是否适合碎片时间消化 |
| 来源质量 | 10% | 官方文档/源码 > 泛泛文章 |
| 时效性 | 10% | 近期技术更新优先 |

负反馈机制：连续忽略同一主题/来源会自动降权，长期不触发则逐步恢复。

## 项目结构

```
passive-agent-workbench/
├── config.yaml              # 统一配置文件（gitignored，提供 .example）
├── prompts/                 # LLM prompt 模板 (Jinja2)
├── docs/                    # 文档
├── src/passive_agent/
│   ├── main.py              # CLI 入口
│   ├── pipeline.py          # 每日处理流水线
│   ├── collectors/          # 数据采集器
│   ├── processors/          # 去重/评分/摘要/排序
│   ├── actions/             # 用户操作处理
│   ├── integrations/        # 外部集成 (DeepSeek, Zotero API, Obsidian)
│   ├── feishu/              # 飞书 Bot
│   ├── storage/             # 数据库 + 数据模型
│   └── utils/               # 配置/日志
├── data/                    # 运行时数据（gitignored）
│   ├── workbench.db         # SQLite 数据库
│   └── reports/             # 周报/导出
└── tests/
```

## 自动化部署 (macOS launchd)

创建 `~/Library/LaunchAgents/com.passive-agent.daily.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.passive-agent.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/PassiveAgent/.venv/bin/python</string>
        <string>-m</string>
        <string>passive_agent.main</string>
        <string>daily</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/PassiveAgent</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>22</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DEEPSEEK_API_KEY</key>
        <string>your-key</string>
    </dict>
</dict>
</plist>
```

加载：

```bash
launchctl load ~/Library/LaunchAgents/com.passive-agent.daily.plist
```

## 技术栈

- Python 3.11+
- SQLite (WAL mode)
- DeepSeek API (摘要/评分/分类)
- Zotero Web API (tag 回写)
- 飞书开放平台 (推送/交互)
- Click (CLI)
- Jinja2 (prompt 模板)

## License

MIT
