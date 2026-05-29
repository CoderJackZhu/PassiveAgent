# Passive Agent Workbench

> 每天从 Zotero、Obsidian、HuggingFace Daily、GitHub Stars 里挑出少量真正值得看的内容，并推送到飞书或在终端里查看。

信息过载时，问题通常不是“没有资料”，而是“不知道今天先看哪几个”。Passive Agent 会帮你完成：采集 → 去重 → 摘要 → 打分 → 推荐 → 反馈降权。

```text
资料来源 → 去重 → LLM 摘要/打分 → Top N 推荐 → 你选择：看 / 忽略 / 周末读 / 生成卡片
```

## 适合谁

- 你有一堆论文、文章、GitHub 项目，但每天只想看最重要的 3 个。
- 你在准备 Agent / LLM / 算法工程相关面试，需要持续积累高价值材料。
- 你希望“少推类似”这种反馈能影响后续推荐，而不是每天重复刷到不想看的东西。

## 5 分钟跑起来

下面是最短路径：先本地跑通，再决定要不要接飞书和定时任务。

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

先不用理解 `config.yaml` 的全部内容。默认配置已经能工作；你只需要打开 `.env` 填一个 LLM API Key：

```bash
XIAOMI_API_KEY=你的_key
XIAOMI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
```

没有 LLM Key 也能采集部分数据，但不会有高质量摘要和打分。

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

## 你每天真正会用的命令

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

## 数据从哪里来

默认配置里已经打开了常用来源。你可以先不改，跑通后再按需调整。

| 来源 | 默认状态 | 说明 |
|---|---:|---|
| Zotero | 开启 | 读取本地 `~/Zotero/zotero.sqlite`，适合论文和长期资料库。 |
| HuggingFace Daily Papers | 开启 | 拉取近期 HF Daily Papers。 |
| Obsidian Inbox | 关闭 | 适合临时丢 URL，格式见下方。 |
| GitHub Stars | 关闭 | 需要手动导入，适合整理已 star 的项目。 |

### Obsidian Inbox 格式

如果你启用了 Obsidian，在 inbox 文件里写：

```markdown
- [文章标题](https://example.com/article) #Agent #unread
- 纯文本描述也可以
- ✓ [已处理的条目](https://example.com/old)  # 会被跳过
```

### GitHub Stars

GitHub Stars 不会每次 `daily` 自动全量拉取。需要时手动导入：

```bash
GITHUB_TOKEN=xxx uv run passive-agent init-stars
uv run passive-agent list-stars --sort stars
uv run passive-agent export-stars
```

## 配置怎么改：只看这 3 个地方

大部分用户不用读完整 YAML。常改的只有这几个：

### 1. 当前目标

在 `config.yaml` 里改：

```yaml
goals:
  current_focus: "Agent 算法岗面试准备"
  priority_topics:
    - Agent 架构与工程
    - Tool Calling
    - RAG 与评测
```

它会直接影响推荐排序。

### 2. 数据源开关

不用某个来源就关掉：

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

完整配置参考：[docs/configuration.md](docs/configuration.md)。

## 接入飞书（可选）

本地能跑通以后，再接飞书。飞书分两种能力：

| 能力 | 用途 | 需要什么 |
|---|---|---|
| 主动推送 | `daily` / `weekend-push` 把推荐卡片发到聊天里 | `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CHAT_ID` |
| 长连接服务 | 接收“暂停 / 恢复 / 推送”等文本命令，处理卡片按钮 | `uv run passive-agent serve` 常驻运行 |

### 1. 在 `.env` 里填飞书信息

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_CHAT_ID=oc_xxx
```

### 2. 不知道 `FEISHU_CHAT_ID` 怎么拿？

先只填 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，启动长连接：

```bash
uv run passive-agent serve
```

然后在飞书里给机器人发一条消息。日志里会出现：

```text
Auto-detected chat_id: oc_xxx
```

把这个值写回 `.env` 的 `FEISHU_CHAT_ID`。

### 3. 验证能否主动推送

```bash
uv run passive-agent feishu-push --stage recommended --limit 5
```

能收到卡片，说明主动推送已通。

### 4. 验证按钮和文本命令

保持下面命令运行：

```bash
uv run passive-agent serve
```

然后在飞书里：

- 点卡片按钮，日志应出现 `Card action: ...`
- 发送 `状态` / `推送` / `暂停` / `恢复`，日志应出现收到消息

### 5. 飞书开放平台需要打开什么

在飞书开放平台的企业自建应用里：

1. 启用机器人能力。
2. 权限管理里开通消息发送权限：`im:message:send_as_bot` 或 `im:message`。
3. 如果要接收文本命令，订阅事件：`im.message.receive_v1`。
4. 如果要处理卡片按钮，订阅事件：`card.action.trigger`（旧控制台可能叫 `card.action.trigger_v1`）。
5. 每次改权限或事件后，都要发布新版本，并在租户侧升级/启用。

## 自动定时运行（可选）

本地和飞书都验证通过后，再安装 macOS LaunchAgent：

```bash
scripts/install_launchd.sh
```

这个脚本会安装 3 个任务：

| 服务 | 做什么 |
|---|---|
| `com.passive-agent.daily` | 每天 21:00 跑一次 `daily` |
| `com.passive-agent.weekend` | 每周六 10:00 推送周末阅读队列 |
| `com.passive-agent.serve` | 常驻飞书长连接服务 |

查看服务：

```bash
launchctl list | grep passive-agent
```

日志通常在：

```text
data/reports/*stdout.log
data/reports/*stderr.log
```

## 踩坑速查

### 1. `uv run passive-agent daily` 没有飞书推送

先确认 `.env` 里有：

```bash
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_CHAT_ID=...
```

然后手动验证：

```bash
uv run passive-agent feishu-push --stage recommended --limit 5
```

如果手动推送也失败，优先排查飞书权限和 `FEISHU_CHAT_ID`。

### 2. 报错 `230002 - Bot/User can NOT be out of the chat`

含义：机器人不在目标会话里，或者 `FEISHU_CHAT_ID` 不是这个会话的。

处理：把机器人拉进目标群，重新用 `serve` 自动识别该群的 `chat_id`，再写回 `.env`。

### 3. 能收到卡片，但点击按钮没反应

通常是没有订阅或没有发布卡片事件。

检查飞书开放平台：

- 是否订阅 `card.action.trigger` / `card.action.trigger_v1`
- 是否发布新版本
- 租户侧是否升级/启用新版应用

### 4. 能主动推送，但发“状态 / 推送”没反应

通常是文本消息事件没通。

检查：

- 是否订阅 `im.message.receive_v1`
- 是否给了接收单聊/群聊消息权限
- `uv run passive-agent serve` 是否正在运行

### 5. launchd 后台跑不起来，但手动命令正常

常见原因是项目放在 `Documents` / `Desktop` / `Downloads` 这类 macOS 隐私保护目录下。建议放到：

```text
~/Code/Agents/PassiveAgent
```

如果已经放错位置，移动后重新执行：

```bash
uv sync
scripts/install_launchd.sh
```

### 6. launchd 里飞书长连接偶发断开

如果系统环境里有代理，例如 `HTTP_PROXY=http://127.0.0.1:7897`，飞书 WebSocket 重连可能受影响。

建议给 launchd 环境加 `NO_PROXY`：

```text
open.feishu.cn,msg-frontier.feishu.cn,.feishu.cn,.larksuite.com,127.0.0.1,localhost
```

如果你用 `scripts/install_launchd.sh`，它会把 `.env` 中的非空值写入 plist；更复杂的代理设置可直接检查 `~/Library/LaunchAgents/com.passive-agent.serve.plist`。

### 7. GitHub Stars 为空

GitHub Stars 需要手动导入，并且需要 `GITHUB_TOKEN`：

```bash
GITHUB_TOKEN=xxx uv run passive-agent init-stars
```

### 8. 不想用 Zotero / Obsidian

在 `config.yaml` 里关掉对应来源即可：

```yaml
sources:
  zotero:
    enabled: false
  obsidian:
    enabled: false
```

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
