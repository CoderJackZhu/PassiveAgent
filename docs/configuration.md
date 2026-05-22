# Configuration Guide

## Overview

所有配置集中在项目根目录的 `config.yaml` 一个文件中，按顶层 key 区分三部分：

- `goals` — 目标与优先级
- `sources` — 数据源开关和连接参数
- `scoring` — 评分权重和推送数量

首次使用需从示例复制：

```bash
cp config.yaml.example config.yaml
```

## sources 部分

控制数据源的开关和连接参数。

### Zotero

```yaml
zotero:
  enabled: true
  db_path: "~/Zotero/zotero.sqlite"   # Zotero 本地数据库路径
  lookback_days: 7                      # 采集最近 N 天新增的条目
  high_priority_collections:            # 高优先级分类集合（自动加权 15%）
    - Agent
    - RAG
    - LLM
  writeback_enabled: false              # 是否回写 tag 到 Zotero
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
```

GitHub Stars 不参与每日 pipeline 自动采集，仅通过 `init-stars` 命令手动导入。

需要设置 `GITHUB_TOKEN` 环境变量（可通过 `gh auth token` 获取）。

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
  daily_limit: 5            # 每日最多推送条数
  weekend_limit: 5          # 周末队列最大容量
  negative_feedback:
    topic_threshold: 3      # 同主题连续忽略 N 次后降权
    topic_penalty: 0.15     # 每次降权幅度
    source_threshold: 5     # 同来源连续忽略 N 次后降权
    source_penalty: 0.20
    min_weight: 0.30        # 权重下限（不会降到 0）
    recovery_days: 30       # 多少天未触发负反馈后开始恢复
    recovery_rate: 0.05     # 每次恢复幅度
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API，用于摘要/打分/分类 |
| `GITHUB_TOKEN` | 否 | GitHub Stars 导入 |
| `ZOTERO_API_KEY` | 否 | Zotero tag 回写 |
| `FEISHU_APP_ID` | 否 | 飞书 Bot 推送 |
| `FEISHU_APP_SECRET` | 否 | 飞书 Bot 推送 |

建议在 `~/.zshrc` 或 `.env` 中配置（`.env` 已被 gitignore）。
