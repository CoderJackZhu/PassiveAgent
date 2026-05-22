from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_launchd.sh"


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
