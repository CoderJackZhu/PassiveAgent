# 踩坑速查

## 1. `uv run passive-agent daily` 没有飞书推送

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

## 2. 报错 `230002 - Bot/User can NOT be out of the chat`

含义：机器人不在目标会话里，或者 `FEISHU_CHAT_ID` 不是这个会话的。

处理：把机器人拉进目标群，重新用 `serve` 自动识别该群的 `chat_id`，再写回 `.env`。

## 3. 能收到卡片，但点击按钮没反应

通常是没有订阅或没有发布卡片事件。

检查飞书开放平台：

- 是否订阅 `card.action.trigger` / `card.action.trigger_v1`
- 是否发布新版本
- 租户侧是否升级/启用新版应用

## 4. 能主动推送，但发"状态 / 推送"没反应

通常是文本消息事件没通。

检查：

- 是否订阅 `im.message.receive_v1`
- 是否给了接收单聊/群聊消息权限
- `uv run passive-agent serve` 是否正在运行

## 5. launchd 后台跑不起来，但手动命令正常

常见原因是项目放在 `Documents` / `Desktop` / `Downloads` 这类 macOS 隐私保护目录下。建议放到：

```text
~/Code/Agents/PassiveAgent
```

如果已经放错位置，移动后重新执行：

```bash
uv sync
scripts/install_launchd.sh
```

## 6. launchd 里飞书长连接偶发断开

如果系统环境里有代理，例如 `HTTP_PROXY=http://127.0.0.1:7897`，飞书 WebSocket 重连可能受影响。

建议给 launchd 环境加 `NO_PROXY`：

```text
open.feishu.cn,msg-frontier.feishu.cn,.feishu.cn,.larksuite.com,127.0.0.1,localhost
```

如果你用 `scripts/install_launchd.sh`，它会把 `.env` 中的非空值写入 plist；更复杂的代理设置可直接检查 `~/Library/LaunchAgents/com.passive-agent.serve.plist`。

## 7. GitHub Stars 为空

GitHub Stars 需要手动导入，并且需要 `GITHUB_TOKEN`：

```bash
GITHUB_TOKEN=xxx uv run passive-agent init-stars
```

## 8. 不想用 Zotero / Obsidian

在 `config.yaml` 里关掉对应来源即可：

```yaml
sources:
  zotero:
    enabled: false
  obsidian:
    enabled: false
```
