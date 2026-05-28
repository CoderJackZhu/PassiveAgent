# Configuration Guide

## Overview

所有配置集中在项目根目录的 `config.yaml` 一个文件中，按顶层 key 区分：

- `runtime` — 运行时路径（数据库、报告、prompts）
- `llm` — LLM 连接参数
- `goals` — 目标与优先级
- `sources` — 数据源开关和连接参数
- `recommendations` — 推荐行为控制
- `display` — 展示限制
- `feishu` — 飞书连接参数
- `scoring` — 评分权重和推送数量

首次使用需从示例复制：

```bash
cp config.yaml.example config.yaml
```

你也可以通过 `PASSIVE_AGENT_CONFIG` 环境变量指定自定义配置文件路径（指向文件或目录均可），优先级高于默认的 `config/config.yaml`。

## runtime 部分

控制运行时路径，默认值通常不需要修改。

```yaml
runtime:
  db_path: "data/workbench.db"    # SQLite 数据库路径
  reports_dir: "data/reports"     # 周报/导出输出目录
  prompts_dir: "prompts"          # LLM prompt 模板目录
```

## llm 部分

控制 LLM 连接和调用参数。

```yaml
llm:
  provider: "openai_compatible"             # deepseek | openai_compatible
  api_key_env: "XIAOMI_API_KEY"             # 从哪个环境变量读取 API Key
  base_url: "https://token-plan-cn.xiaomimimo.com/v1"  # API 地址，需与订阅页区域一致
  model: "mimo-v2.5-pro"                    # 模型名
  temperature: 0.3                          # 生成温度 (0–1)
  max_concurrency: 5                        # 最大并发请求数
  max_retries: 3                            # 失败重试次数
  retry_backoff_base_seconds: 2.0           # 重试退避基础秒数
```

**注意**：`api_key_env` 只是环境变量名，真正的密钥通过 `.env` 或系统环境变量设置，不要写在 YAML 里。当前线上配置使用小米 MiMo Token Plan；`tp-...` key 必须配 Token Plan 专用 Base URL，不能和 pay-as-you-go 的 `sk-...` key/endpoint 混用。

## goals 部分

定义当前目标和优先级主题，直接影响 LLM 打分。

```yaml
goals:
  current_focus: "Agent 算法岗面试准备"
  priority_topics:
    - Agent 架构与工程
    - Tool Calling 与 Function Calling
    - RAG 与评测
    - Workflow / Orchestration
    - Coding Agent
    - LLM Infra（推理优化、部署）
  low_priority_topics:
    - 前端开发
    - 移动开发
    - 泛泛的 AI 趋势文章
  output_preference: "interview_card"  # interview_card | tech_note
```

面试结束后可修改 `current_focus` 和 `priority_topics` 切换方向。

## sources 部分

控制数据源的开关和连接参数。

### Zotero

```yaml
zotero:
  enabled: true
  db_path: "~/Zotero/zotero.sqlite"       # Zotero 本地数据库路径
  lookback_days: 365                        # 采集最近 N 天新增的条目
  high_priority_collections:                # 高优先级分类集合（自动加权 15%）
    - Agent
    - RAG
    - LLM
  writeback_enabled: false                  # 是否回写 tag 到 Zotero
  sqlite_timeout_seconds: 30.0              # SQLite 连接超时
  db_retries: 3                             # 数据库访问重试次数
  db_retry_sleep_seconds: 5.0               # 重试间隔
  writeback_timeout_seconds: 15.0           # Zotero Web API 写入超时
  local_api_timeout_seconds: 3.0            # Zotero 本地 API 超时
```

**Zotero tag 回写**：开启后，对条目执行 action 时会将 `/unread` 替换为 `/done`。需要：
1. 在 [zotero.org/settings/keys](https://www.zotero.org/settings/keys) 创建 API Key（勾选 library read/write）
2. 设置环境变量 `ZOTERO_API_KEY`
3. 确保 Zotero 本地 HTTP API 已开启（Zotero → 设置 → 高级 → Allow other applications...）

建议先用 dry-run 测试：

```bash
passive-agent zotero-writeback          # 默认 dry-run
passive-agent zotero-writeback --execute  # 确认无误后正式执行
```

### Obsidian

```yaml
obsidian:
  enabled: true
  inbox_path: "~/ObsidianVault/00-Inbox/inbox.md"  # 采集入口文件
  vault_path: "~/ObsidianVault"                     # 输出目录（写入笔记/卡片）
  read_paths:                                        # 只读输入目录（可多个）
    - "~/Documents/MyNotes"
    - "~/Documents/InterviewPrep"
```

**目录分离设计**：
- `vault_path`：系统输出目录，生成的面试卡和技术笔记写入此处
- `read_paths`：只读搜索目录，用于"关联笔记"功能，不会被修改
- `inbox_path`：独立的采集入口，与 read_paths 无关

如果 `vault_path` 或 `inbox_path` 的父目录不存在，系统会自动创建目录；如果 `inbox_path` 文件不存在，会自动创建一个空的 `inbox.md`。

**inbox.md 格式**：

```markdown
- [标题](url) #tag1 #tag2     ← 会被采集
- 纯文本描述                    ← 会被采集
- ✓ [已处理](url)              ← 自动跳过（前置 ✓）
- [已读文章](url) ✓            ← 自动跳过（后置 ✓）
```

### GitHub Stars

```yaml
github_stars:
  enabled: true
  max_pages: 10                   # 最多获取的页数
  per_page: 100                   # 每页数量 (max 100)
  classification_batch_size: 10   # LLM 分类批处理大小
  http_timeout_seconds: 30.0      # GitHub API 请求超时
```

GitHub Stars 不参与每日 pipeline 自动采集，仅通过 `init-stars` 命令手动导入。CLI 参数 `--max-pages` 可临时覆盖配置值。

需要设置 `GITHUB_TOKEN` 环境变量（可通过 `gh auth token` 获取）。

### HuggingFace Daily Papers

```yaml
hf_daily:
  enabled: true
  max_papers: 30                # 每次最多采集论文数
  lookback_days: 30             # 回看天数
  http_timeout_seconds: 30.0    # HTTP 请求超时
```

HuggingFace Daily Papers 每日 pipeline 自动采集，不需要 API Key。

## recommendations 部分

控制推荐生命周期和关联行为。

```yaml
recommendations:
  stale_after_days: 7            # 推荐超过 N 天后标记为过期
  related_zotero_limit: 3        # 每个条目关联的 Zotero 条目数上限
  related_stars_limit: 3         # 每个条目关联的 GitHub Stars 数上限
```

## display 部分

控制 CLI dashboard、报告、飞书命令的展示数量。

```yaml
display:
  dashboard_limit: 10            # dashboard 推荐展示条数
  feedback_summary_limit: 5      # 负反馈摘要展示条数
  recent_cards_limit: 5          # 飞书「最近卡片」命令展示条数
  weekly_processed_limit: 10     # 周报中本周处理展示条数
  manual_push_limit: 5           # feishu-push 默认推送条数（CLI --limit 可覆盖）
```

## feishu 部分

```yaml
feishu:
  async_timeout_seconds: 60.0    # 飞书异步操作超时（消息处理、卡片回调）
```

## scoring 部分

控制评分权重和推送数量。

```yaml
scoring:
  weights:
    goal_relevance: 0.30    # 目标相关性
    novelty: 0.20           # 新颖性
    actionability: 0.20     # 可操作性
    difficulty_fit: 0.10    # 难度适配
    source_quality: 0.10    # 来源质量
    timeliness: 0.10        # 时效性
  daily_limit: 3            # 每日最多推送条数
  weekend_limit: 5          # 周末队列最大容量
  negative_feedback:
    topic_threshold: 3      # 同主题连续忽略 N 次后降权
    topic_penalty: 0.15     # 每次降权幅度
    topic_window: 10        # 滑动窗口大小（最近 N 条反馈）
    source_threshold: 5     # 同来源连续忽略 N 次后降权
    source_penalty: 0.20
    source_window: 15       # 滑动窗口大小（最近 N 条反馈）
    min_weight: 0.30        # 权重下限（不会降到 0）
    recovery_days: 30       # 多少天未触发负反馈后开始恢复
    recovery_rate: 0.05     # 每次恢复幅度
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `PASSIVE_AGENT_CONFIG` | 否 | 自定义配置文件路径（文件或目录），优先级高于默认位置 |
| `XIAOMI_API_KEY` | 是 | 当前默认 LLM API Key，用于摘要/打分/分类 |
| `XIAOMI_BASE_URL` | 否 | 小米 Token Plan Base URL，需与订阅页区域一致 |
| `DEEPSEEK_API_KEY` | 否 | DeepSeek 兼容别名/回退配置使用 |
| `GITHUB_TOKEN` | 否 | GitHub Stars 导入 |
| `ZOTERO_API_KEY` | 否 | Zotero tag 回写 |
| `FEISHU_APP_ID` | 否 | 飞书 Bot 推送 |
| `FEISHU_APP_SECRET` | 否 | 飞书 Bot 推送 |
| `FEISHU_CHAT_ID` | 主动推送时必需 | `daily` / `weekend-push` 的目标会话 ID |

建议在 `.env` 中配置（已被 gitignore）。如果通过 launchd 定时运行，`scripts/install_launchd.sh` 会把 `.env` 中非空的环境变量写入 plist 的 `EnvironmentVariables`。

**TCC 权限注意**：建议把项目放在 `~/Code`、`~/Developer` 等普通目录。macOS 的 Documents、Desktop、Downloads 受隐私权限保护，LaunchAgent 后台进程可能无法读取 `.venv`。`scripts/install_launchd.sh` 会阻止从这些目录安装并打印迁移命令。

获取 `FEISHU_CHAT_ID`：运行 `uv run passive-agent serve`，在飞书中给机器人发一条消息，终端日志会输出 `Auto-detected chat_id: ...`。
