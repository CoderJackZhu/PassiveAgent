# 自动定时运行

本地和飞书都验证通过后，可以设置定时任务自动运行。根据你的操作系统选择对应方案。

---

## macOS（LaunchAgent）

运行安装脚本：

```bash
scripts/install_launchd.sh
```

这个脚本会安装 3 个任务：

| 服务 | 做什么 |
|---|---|
| `com.passive-agent.daily` | 每天 21:00 跑一次 `daily` |
| `com.passive-agent.weekend` | 每周六 10:00 推送周末阅读队列 |
| `com.passive-agent.serve` | 常驻飞书长连接服务 |

### 查看服务

```bash
launchctl list | grep passive-agent
```

日志通常在：

```text
data/reports/*stdout.log
data/reports/*stderr.log
```

### TCC 权限注意

建议把项目放在 `~/Code`、`~/Developer` 等普通目录。macOS 的 Documents、Desktop、Downloads 受隐私权限保护，LaunchAgent 后台进程可能无法读取 `.venv`。

`scripts/install_launchd.sh` 会阻止从这些目录安装并打印迁移命令。如果已经放错位置，移动后重新执行：

```bash
uv sync
scripts/install_launchd.sh
```

---

## Linux（systemd）

### 1. 创建 service 文件

将以下内容写入 `~/.config/systemd/user/passive-agent-daily.service`：

```ini
[Unit]
Description=Passive Agent Daily Recommendation
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/PassiveAgent
ExecStart=/path/to/PassiveAgent/.venv/bin/passive-agent daily
EnvironmentFile=/path/to/PassiveAgent/.env

[Install]
WantedBy=default.target
```

### 2. 创建 timer 文件

写入 `~/.config/systemd/user/passive-agent-daily.timer`：

```ini
[Unit]
Description=Run Passive Agent daily at 21:00

[Timer]
OnCalendar=*-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 3. 周末推送 timer

写入 `~/.config/systemd/user/passive-agent-weekend.timer`：

```ini
[Unit]
Description=Run Passive Agent weekend push on Saturday 10:00

[Timer]
OnCalendar=Sat *-*-* 10:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

对应的 service 文件类似 daily，把 `ExecStart` 改为：

```ini
ExecStart=/path/to/PassiveAgent/.venv/bin/passive-agent weekend-push
```

### 4. 飞书长连接服务

写入 `~/.config/systemd/user/passive-agent-serve.service`：

```ini
[Unit]
Description=Passive Agent Feishu WebSocket Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/PassiveAgent
ExecStart=/path/to/PassiveAgent/.venv/bin/passive-agent serve
EnvironmentFile=/path/to/PassiveAgent/.env
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### 5. 启用并启动

```bash
systemctl --user daemon-reload
systemctl --user enable --now passive-agent-daily.timer
systemctl --user enable --now passive-agent-weekend.timer
systemctl --user enable --now passive-agent-serve.service
```

### 查看状态

```bash
systemctl --user list-timers | grep passive-agent
systemctl --user status passive-agent-serve
journalctl --user -u passive-agent-daily --since today
```

### 注意事项

- 用户级 systemd 需要启用 lingering 才能在未登录时运行：`loginctl enable-linger $USER`
- `Persistent=true` 确保错过的任务在开机后补执行
- 路径中的 `/path/to/PassiveAgent` 需要替换为实际项目路径

---

## Windows（任务计划程序）

### 方式一：PowerShell 脚本创建

```powershell
# 每日推荐 — 每天 21:00
$action = New-ScheduledTaskAction `
    -Execute "C:\path\to\PassiveAgent\.venv\Scripts\passive-agent.exe" `
    -Argument "daily" `
    -WorkingDirectory "C:\path\to\PassiveAgent"

$trigger = New-ScheduledTaskTrigger -Daily -At 9:00PM

Register-ScheduledTask `
    -TaskName "PassiveAgent-Daily" `
    -Action $action `
    -Trigger $trigger `
    -Description "Passive Agent Daily Recommendation"
```

```powershell
# 周末推送 — 每周六 10:00
$action = New-ScheduledTaskAction `
    -Execute "C:\path\to\PassiveAgent\.venv\Scripts\passive-agent.exe" `
    -Argument "weekend-push" `
    -WorkingDirectory "C:\path\to\PassiveAgent"

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 10:00AM

Register-ScheduledTask `
    -TaskName "PassiveAgent-Weekend" `
    -Action $action `
    -Trigger $trigger `
    -Description "Passive Agent Weekend Push"
```

```powershell
# 飞书长连接服务 — 开机自动启动
$action = New-ScheduledTaskAction `
    -Execute "C:\path\to\PassiveAgent\.venv\Scripts\passive-agent.exe" `
    -Argument "serve" `
    -WorkingDirectory "C:\path\to\PassiveAgent"

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName "PassiveAgent-Serve" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Passive Agent Feishu WebSocket Service"
```

### 方式二：GUI 操作

1. 打开"任务计划程序"（`taskschd.msc`）
2. 点击"创建基本任务"
3. 名称填 `PassiveAgent-Daily`
4. 触发器选"每天"，时间设 21:00
5. 操作选"启动程序"：
   - 程序：`C:\path\to\PassiveAgent\.venv\Scripts\passive-agent.exe`
   - 参数：`daily`
   - 起始位置：`C:\path\to\PassiveAgent`
6. 重复以上步骤创建 Weekend 和 Serve 任务

### 查看和管理

```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -like "PassiveAgent*"}
Start-ScheduledTask -TaskName "PassiveAgent-Daily"   # 手动触发一次
```

### 环境变量

Windows 任务计划程序会继承系统环境变量。如果你的 `.env` 中有密钥，需要在系统或用户环境变量里设置，或者在启动脚本中加载：

```powershell
# 创建一个包装脚本 run-daily.ps1
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
passive-agent daily
```

---

## Docker / cron（服务器部署）

如果在服务器上运行，可以用 crontab：

```bash
crontab -e
```

添加：

```cron
# 每天 21:00 运行每日推荐
0 21 * * * cd /path/to/PassiveAgent && .venv/bin/passive-agent daily >> data/reports/cron.log 2>&1

# 每周六 10:00 推送周末队列
0 10 * * 6 cd /path/to/PassiveAgent && .venv/bin/passive-agent weekend-push >> data/reports/cron.log 2>&1
```

飞书长连接服务建议用 supervisor 或 systemd 管理（参考上面 Linux 部分），不适合用 cron。

---

## 代理环境

如果系统环境里有代理（如 `HTTP_PROXY=http://127.0.0.1:7897`），飞书 WebSocket 重连可能受影响。

建议在环境中设置 `NO_PROXY`：

```text
open.feishu.cn,msg-frontier.feishu.cn,.feishu.cn,.larksuite.com,127.0.0.1,localhost
```

- macOS：`scripts/install_launchd.sh` 会把 `.env` 中的非空值写入 plist
- Linux：写入 service 的 `Environment=` 或 `EnvironmentFile=`
- Windows：在系统环境变量或包装脚本中设置
