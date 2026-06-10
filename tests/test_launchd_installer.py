from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_launchd.sh"
PLIST_TEMPLATES = sorted((REPO_ROOT / "scripts").glob("com.passive-agent.*.plist"))
WEEKLY_PLIST = REPO_ROOT / "scripts" / "com.passive-agent.weekly-report.plist"


def test_launchd_installer_rejects_documents_project_without_override(tmp_path):
    home = tmp_path / "home"
    project = home / "Documents" / "PassiveAgent"
    project.mkdir(parents=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PASSIVE_AGENT_PROJECT_DIR"] = str(project)
    env.pop("PASSIVE_AGENT_ALLOW_TCC_PROTECTED_DIR", None)

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "macOS privacy-protected folder" in output
    assert str(project) in output
    assert "PASSIVE_AGENT_ALLOW_TCC_PROTECTED_DIR=1" in output
    assert "scripts/install_launchd.sh" in output


def test_launchd_preflight_allows_documents_project_with_override(tmp_path):
    home = tmp_path / "home"
    project = home / "Documents" / "PassiveAgent"
    project.mkdir(parents=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PASSIVE_AGENT_PROJECT_DIR"] = str(project)
    env["PASSIVE_AGENT_ALLOW_TCC_PROTECTED_DIR"] = "1"

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"source {shlex.quote(str(INSTALLER))}; preflight_project_dir",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0


def test_launchd_plist_templates_write_logs_under_data_logs():
    assert PLIST_TEMPLATES

    for plist_path in PLIST_TEMPLATES:
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)

        assert plist["StandardOutPath"].startswith("__PROJECT_DIR__/data/logs/")
        assert plist["StandardErrorPath"].startswith("__PROJECT_DIR__/data/logs/")
        assert "/data/reports/" not in plist["StandardOutPath"]
        assert "/data/reports/" not in plist["StandardErrorPath"]


def test_launchd_installer_creates_data_logs_directory(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "PassiveAgent"
    bin_dir = tmp_path / "bin"
    project.mkdir()
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  list) exit 0 ;;\n"
        "  load|unload) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PASSIVE_AGENT_PROJECT_DIR"] = str(project)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "data" / "logs").is_dir()


def test_weekly_report_plist_runs_sunday_2130_push():
    with WEEKLY_PLIST.open("rb") as handle:
        plist = plistlib.load(handle)

    assert plist["Label"] == "com.passive-agent.weekly-report"
    assert plist["ProgramArguments"] == [
        "__PROJECT_DIR__/.venv/bin/passive-agent",
        "weekly-report",
        "--push",
    ]
    assert plist["StartCalendarInterval"] == {
        "Weekday": 0,
        "Hour": 21,
        "Minute": 30,
    }


def test_launchd_installer_summary_includes_weekly_report_service():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "com.passive-agent.weekly-report" in text
    assert "每周日 21:30 推送周报" in text


def test_scheduled_tasks_docs_include_all_launchd_services():
    text = (REPO_ROOT / "docs" / "scheduled-tasks.md").read_text(encoding="utf-8")

    assert "这个脚本会安装 4 个任务" in text
    assert "`com.passive-agent.weekly-report`" in text
    assert "每周日 21:30 推送周报" in text
