from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LOCAL_GIT_TIMEOUT_SECONDS = 60


if __name__ == "__main__":
    subprocess.run(
        ("git", "config", "core.hooksPath", ".githooks"),
        cwd=ROOT,
        check=True,
        timeout=LOCAL_GIT_TIMEOUT_SECONDS,
    )
    observed = subprocess.run(
        ("git", "config", "--get", "core.hooksPath"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=LOCAL_GIT_TIMEOUT_SECONDS,
    ).stdout.strip()
    if observed != ".githooks":
        raise RuntimeError("Git hooks path differs")
    print("Git Study-close hook installed: .githooks")
