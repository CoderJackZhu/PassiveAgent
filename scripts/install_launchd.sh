#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$HOME/Library/LaunchAgents"
ENV_FILE="$PROJECT_DIR/.env"

echo "=== Passive Agent LaunchD Installer ==="
echo "Project: $PROJECT_DIR"
echo ""

# Check .env file exists for environment variables
if [ ! -f "$ENV_FILE" ]; then
    echo "Warning: $ENV_FILE not found."
    echo "Create it with DEEPSEEK_API_KEY, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID"
    echo ""
fi

# Ensure reports directory exists
mkdir -p "$PROJECT_DIR/data/reports"

# Install each plist
for plist in "$SCRIPT_DIR"/com.passive-agent.*.plist; do
    name=$(basename "$plist")

    # Unload if already loaded
    if launchctl list | grep -q "${name%.plist}"; then
        echo "Unloading existing: $name"
        launchctl unload "$PLIST_DIR/$name" 2>/dev/null || true
    fi

    # Copy and load
    cp "$plist" "$PLIST_DIR/$name"
    launchctl load "$PLIST_DIR/$name"
    echo "Loaded: $name"
done

echo ""
echo "Done! Services installed:"
echo "  - com.passive-agent.daily    (每天 21:00 运行 pipeline)"
echo "  - com.passive-agent.serve    (飞书 Bot 常驻, KeepAlive)"
echo "  - com.passive-agent.weekend  (每周六 10:00 推送周末队列)"
echo ""
echo "管理命令:"
echo "  launchctl list | grep passive-agent    # 查看状态"
echo "  launchctl unload ~/Library/LaunchAgents/com.passive-agent.serve.plist  # 停止服务"
