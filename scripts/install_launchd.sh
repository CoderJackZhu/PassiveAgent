#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PASSIVE_AGENT_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
PLIST_DIR="$HOME/Library/LaunchAgents"
TCC_OVERRIDE_VAR="PASSIVE_AGENT_ALLOW_TCC_PROTECTED_DIR"

canonical_dir() {
    local path="$1"
    if [[ -d "$path" ]]; then
        (cd "$path" && pwd -P)
    else
        printf "%s\n" "${path%/}"
    fi
}

path_is_inside() {
    local child="${1%/}"
    local parent="${2%/}"
    [[ "$child" == "$parent" || "$child" == "$parent"/* ]]
}

preflight_project_dir() {
    local project_dir
    local home_dir
    project_dir="$(canonical_dir "$PROJECT_DIR")"
    home_dir="$(canonical_dir "$HOME")"

    local protected_root
    for protected_root in "$home_dir/Documents" "$home_dir/Desktop" "$home_dir/Downloads"; do
        protected_root="$(canonical_dir "$protected_root")"
        if path_is_inside "$project_dir" "$protected_root"; then
            if [[ "${!TCC_OVERRIDE_VAR:-}" == "1" ]]; then
                return 0
            fi

            cat <<EOF
Error: project is in a macOS privacy-protected folder:
  $project_dir

LaunchAgents run in the background and may not be allowed to read files under
Documents, Desktop, or Downloads. This can make the service fail with errors
such as:
  PermissionError: [Errno 1] Operation not permitted: .../.venv/pyvenv.cfg

Recommended relocation and reinstall:
  mkdir -p "\$HOME/Code/Agents"
  mv "$project_dir" "\$HOME/Code/Agents/PassiveAgent"
  cd "\$HOME/Code/Agents/PassiveAgent"
  uv sync --all-extras
  scripts/install_launchd.sh

If you have intentionally granted the needed macOS privacy permission and want
to install from this location anyway, rerun with:
  $TCC_OVERRIDE_VAR=1 scripts/install_launchd.sh
EOF
            return 1
        fi
    done

    return 0
}

main() {
    echo "=== Passive Agent LaunchD Installer ==="
    echo "Project: $PROJECT_DIR"
    echo ""

    preflight_project_dir

    # Ensure reports and LaunchAgents directories exist
    mkdir -p "$PROJECT_DIR/data/reports"
    mkdir -p "$PLIST_DIR"

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
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
