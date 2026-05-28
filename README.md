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

`uv sync` 会把 CLI 安装到项目虚拟环境中。后续命令建议使用 `uv run passive-agent ...`；如果想直接运行 `passive-agent ...`，需要先执行 `source .venv/bin/activate`。

### 2. 配置

复制示例配置并按需修改：

```bash
cp config.yaml.example config.yaml
```

### 3. 环境变量

```bash
export XIAOMI_API_KEY="your-token-plan-key" # LLM 摘要/打分（必需；当前默认使用小米 MiMo）
export XIAOMI_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"  # 可选，需与订阅页区域一致
export GITHUB_TOKEN="your-token"            # GitHub Stars 导入（可选）
export ZOTERO_API_KEY="your-key"            # Zotero tag 回写（可选）
export FEISHU_APP_ID="your-app-id"          # 飞书推送（可选）
export FEISHU_APP_SECRET="your-secret"      # 飞书推送（可选）
export FEISHU_CHAT_ID="your-chat-id"        # 主动推送目标会话（daily/weekend 必需）
```

### 4. 初始化

```bash
uv run passive-agent init-db
```

### 5. 运行每日 pipeline

```bash
uv run passive-agent daily
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
| `feishu-push [--stage recommended]` | 手动推送当前条目到飞书，用于验证配置 |
| `zotero-writeback [--execute]` | Zotero tag 回写（默认 dry-run） |
| `serve` | 启动飞书 Bot 长连接服务 |
| `init-db` | 初始化数据库 |

## 飞书配置与权限

`daily` 和 `weekend-push` 是一次性主动推送，必须设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CHAT_ID`。`serve` 是飞书长连接服务，用于接收消息和处理卡片按钮，需要单独常驻运行。

### 飞书开放平台设置

1. 在飞书开放平台创建企业自建应用，并启用机器人能力。
2. 在「凭证与基础信息」中复制 `App ID` / `App Secret`，分别写入 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`。
3. 在「权限管理」中至少开通以下权限，并发布新版本：
   - 发送消息：`im:message:send_as_bot`（以应用的身份发消息）或 `im:message`（获取与发送单聊、群组消息）。
   - 接收单聊消息：`im:message.p2p_msg` 或 `im:message.p2p_msg:readonly`。
   - 如需在群聊里使用：`im:message.group_at_msg` 或 `im:message.group_at_msg:readonly`（接收群聊中 @ 机器人的消息）。
4. 在「事件与回调」中使用长连接 / WebSocket 模式，并订阅：
   - `im.message.receive_v1`（接收消息）：用于处理「推送」「暂停」「恢复」「详情 <id>」等文本命令。
   - `card.action.trigger`（卡片回传交互）：用于处理卡片按钮。部分旧版控制台里名称可能显示为 `card.action.trigger_v1` /「消息卡片回传交互（旧）」。
5. 修改权限或事件后，必须发布新版本，并在租户侧重新启用/升级应用；只在开发后台勾选但不发布，线上 Bot 不会生效。

### 获取和验证 `FEISHU_CHAT_ID`

先设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`XIAOMI_API_KEY`，运行：

```bash
uv run passive-agent serve
```

然后在飞书里给机器人发一条消息。日志会输出：

```text
Auto-detected chat_id: ...
```

把这个值写入 `FEISHU_CHAT_ID`。如果推送到群聊，必须把机器人加入同一个群，并确认机器人在群里有发言权限；否则主动发送会失败，典型报错是：

```text
230002 - Bot/User can NOT be out of the chat
```

可先用以下命令验证飞书配置是否能发消息：

```bash
uv run passive-agent feishu-push --stage recommended --limit 5
```

再点击卡片按钮，日志应出现 `Card action: ...`。如果能收到卡片但点击按钮没反应，优先检查是否已订阅并发布 `card.action.trigger` / `card.action.trigger_v1`。

### 常见踩坑

- **只配了 App ID/Secret 不够**：发消息、收消息、卡片按钮分别依赖不同权限/事件订阅。
- **改完权限/事件必须发布版本**：否则本地 `serve` 重启也不会收到新事件。
- **`FEISHU_CHAT_ID` 必须来自目标会话**：从 A 会话自动识别出的 chat_id，不能拿去给 Bot 不在其中的 B 群主动推送。
- **系统代理可能影响长连接重连**：如果 macOS/launchd 环境里有 `HTTP_PROXY` / `HTTPS_PROXY` 指向本机代理（如 `127.0.0.1:7897`），而代理短暂不可用，飞书 WebSocket 可能断线后重连失败。建议在 launchd plist 或启动环境里加：

```bash
NO_PROXY="open.feishu.cn,msg-frontier.feishu.cn,.feishu.cn,.larksuite.com,127.0.0.1,localhost"
no_proxy="$NO_PROXY"
```

验证长连接是否正常：`serve` 日志里应出现连接成功；飞书发「状态」或「推送」后，日志应出现 `Received message ...`。

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
uv run passive-agent action item_20260522_001 --type card
uv run passive-agent action item_20260522_002 --type weekend
```

## 数据源配置

所有配置集中在项目根目录的 `config.yaml` 中，按 `runtime` / `llm` / `goals` / `sources` / `recommendations` / `display` / `feishu` / `scoring` 八个顶层 key 区分。详见 [docs/configuration.md](docs/configuration.md)。

```yaml
# config.yaml 结构概览
runtime:
  db_path: "data/workbench.db"
  reports_dir: "data/reports"
  prompts_dir: "prompts"

llm:
  provider: "openai_compatible"
  api_key_env: "XIAOMI_API_KEY"
  base_url: "https://token-plan-cn.xiaomimimo.com/v1"
  model: "mimo-v2.5-pro"
  temperature: 0.3
  max_concurrency: 5
  max_retries: 3

goals:
  current_focus: "Agent 算法岗面试准备"
  priority_topics: [...]
  output_preference: "interview_card"

sources:
  zotero:
    enabled: true
    db_path: "~/Zotero/zotero.sqlite"
    sqlite_timeout_seconds: 30.0
    ...
  obsidian:
    enabled: true
    inbox_path: "~/ObsidianVault/00-Inbox/inbox.md"
    ...
  github_stars:
    enabled: true
    max_pages: 10
    per_page: 100
    ...
  hf_daily:
    enabled: true
    max_papers: 30
    lookback_days: 30
    ...

recommendations:
  stale_after_days: 7
  related_zotero_limit: 3
  related_stars_limit: 3

display:
  dashboard_limit: 10
  manual_push_limit: 5

feishu:
  async_timeout_seconds: 60.0

scoring:
  weights: { goal_relevance: 0.30, ... }
  daily_limit: 3
  negative_feedback: { topic_threshold: 3, topic_window: 10, ... }
```

GitHub Stars 用法：

```bash
GITHUB_TOKEN=xxx uv run passive-agent init-stars            # 首次导入
GITHUB_TOKEN=xxx uv run passive-agent init-stars --refresh  # 刷新元数据
uv run passive-agent list-stars --topic Agent --sort stars  # 查看
uv run passive-agent export-stars                           # 导出 Markdown
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

建议把项目放在 `~/Code`、`~/Developer` 等普通目录下再安装 launchd 服务。macOS 的
Documents、Desktop、Downloads 受隐私权限保护，LaunchAgent 后台进程可能无法读取
项目内的 `.venv`，表现为 `PermissionError: [Errno 1] Operation not permitted:
.../.venv/pyvenv.cfg`。`scripts/install_launchd.sh` 会拦截这些路径并给出迁移命令；
如已明确授予所需权限，可用 `PASSIVE_AGENT_ALLOW_TCC_PROTECTED_DIR=1
scripts/install_launchd.sh` 覆盖。

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
        <key>XIAOMI_API_KEY</key>
        <string>your-token-plan-key</string>
        <key>XIAOMI_BASE_URL</key>
        <string>https://token-plan-cn.xiaomimimo.com/v1</string>
        <key>FEISHU_APP_ID</key>
        <string>your-app-id</string>
        <key>FEISHU_APP_SECRET</key>
        <string>your-secret</string>
        <key>FEISHU_CHAT_ID</key>
        <string>your-chat-id</string>
    </dict>
</dict>
</plist>
```

加载：

```bash
launchctl load ~/Library/LaunchAgents/com.passive-agent.daily.plist
```

如果使用 `scripts/install_launchd.sh` 安装 plist，注意 launchd 不会自动继承当前终端里的 `export`。可用 `launchctl setenv FEISHU_CHAT_ID "..."` 等命令写入用户级环境，或在安装后的 plist 中配置 `EnvironmentVariables`。

## 技术栈

- Python 3.11+
- SQLite (WAL mode)
- OpenAI-compatible LLM API（当前默认小米 MiMo，用于摘要/评分/分类）
- Zotero Web API (tag 回写)
- 飞书开放平台 (推送/交互)
- Click (CLI)
- Jinja2 (prompt 模板)

## License

MIT
