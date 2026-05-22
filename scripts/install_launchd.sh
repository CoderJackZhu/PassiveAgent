#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$HOME/Library/LaunchAgents"

echo "=== Passive Agent LaunchD Installer ==="
echo "Project: $PROJECT_DIR"
echo ""

# Ensure reports directory exists
mkdir -p "$PROJECT_DIR/data/reports"

# Install each plist (substitute __PROJECT_DIR__ placeholder)
for plist in "$SCRIPT_DIR"/com.passive-agent.*.plist; do
    name=$(basename "$plist")
    dest="$PLIST_DIR/$name"

    # Unload if already loaded
    if launchctl list 2>/dev/null | grep -q "${name%.plist}"; then
        echo "Unloading existing: $name"
        launchctl unload "$dest" 2>/dev/null || true
    fi

    # Substitute placeholder and install
    sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$plist" > "$dest"
    launchctl load "$dest"
    echo "Loaded: $name"
done

echo ""
echo "Done! Services installed:"
echo "  - com.passive-agent.daily    (每天 21:00 运行 pipeline)"
echo "  - com.passive-agent.serve    (飞书 Bot 常驻, KeepAlive)"
echo "  - com.passive-agent.weekend  (每周六 10:00 推送周末队列)"
echo ""
echo "Tip: set environment variables in ~/.zshenv or use 'launchctl setenv' for:"
echo "  DEEPSEEK_API_KEY, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID"
echo ""
echo "管理命令:"
echo "  launchctl list | grep passive-agent"
echo "  launchctl unload ~/Library/LaunchAgents/com.passive-agent.serve.plist"
