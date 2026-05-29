# 飞书接入

本地能跑通以后，再接飞书。飞书分两种能力：

| 能力 | 用途 | 需要什么 |
|---|---|---|
| 主动推送 | `daily` / `weekend-push` 把推荐卡片发到聊天里 | `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CHAT_ID` |
| 长连接服务 | 接收"暂停 / 恢复 / 推送"等文本命令，处理卡片按钮 | `uv run passive-agent serve` 常驻运行 |

## 1. 在 `.env` 里填飞书信息

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_CHAT_ID=oc_xxx
```

## 2. 不知道 `FEISHU_CHAT_ID` 怎么拿？

先只填 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，启动长连接：

```bash
uv run passive-agent serve
```

然后在飞书里给机器人发一条消息。日志里会出现：

```text
Auto-detected chat_id: oc_xxx
```

把这个值写回 `.env` 的 `FEISHU_CHAT_ID`。

## 3. 验证能否主动推送

```bash
uv run passive-agent feishu-push --stage recommended --limit 5
```

能收到卡片，说明主动推送已通。

## 4. 验证按钮和文本命令

保持下面命令运行：

```bash
uv run passive-agent serve
```

然后在飞书里：

- 点卡片按钮，日志应出现 `Card action: ...`
- 发送 `状态` / `推送` / `暂停` / `恢复`，日志应出现收到消息

## 5. 飞书开放平台需要打开什么

在飞书开放平台的企业自建应用里：

1. 启用机器人能力。
2. 权限管理里开通消息发送权限：`im:message:send_as_bot` 或 `im:message`。
3. 如果要接收文本命令，订阅事件：`im.message.receive_v1`。
4. 如果要处理卡片按钮，订阅事件：`card.action.trigger`（旧控制台可能叫 `card.action.trigger_v1`）。
5. 每次改权限或事件后，都要发布新版本，并在租户侧升级/启用。
