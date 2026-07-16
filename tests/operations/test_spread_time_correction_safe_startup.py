from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCRIPT = (
    ROOT / "scripts" / "apply_spread_time_semantics_correction.py"
)


def _fixture_repository(destination: Path) -> tuple[Path, Path]:
    root = destination / "fixture-repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / SOURCE_SCRIPT.name
    shutil.copy2(SOURCE_SCRIPT, script)
    shutil.copytree(
        ROOT / "src",
        root / "src",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.dll",
            "*.pyc",
            "*.pyd",
            "*.so",
        ),
    )
    return root, script


def _safe_help(
    root: Path,
    script: Path,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, "-I", "-S", str(script), "--help"),
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def _sentinel_source(path: Path) -> str:
    return (
        "from pathlib import Path\n"
        f"Path({str(path)!r}).write_text('executed', encoding='ascii')\n"
    )


def _repository_bytecode_inventory(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in (root / "src").rglob("*.pyc")
        )
    )


def test_matching_header_repository_bytecode_is_ignored(
    tmp_path: Path,
) -> None:
    root, script = _fixture_repository(tmp_path)
    source = root / "src" / "axiom_rift" / "core" / "canonical.py"
    sentinel = tmp_path / "malicious-bytecode-executed.txt"
    original = source.read_bytes()
    prefix = _sentinel_source(sentinel).encode("ascii")
    assert len(prefix) + 2 < len(original)
    malicious = prefix + b"#" + b"x" * (len(original) - len(prefix) - 2) + b"\n"
    assert len(malicious) == len(original)

    source.write_bytes(malicious)
    malicious_stat = source.stat()
    cache = Path(importlib.util.cache_from_source(str(source)))
    py_compile.compile(str(source), cfile=str(cache), doraise=True)
    source.write_bytes(original)
    os.utime(
        source,
        ns=(malicious_stat.st_atime_ns, malicious_stat.st_mtime_ns),
    )

    # Prove that the forged timestamp-and-size cache is executable without the
    # correction entrypoint's private cache-prefix policy.
    probe = subprocess.run(
        (
            sys.executable,
            "-I",
            "-S",
            "-c",
            (
                "import sys;"
                f"sys.path.insert(0, {str(root / 'src')!r});"
                "import axiom_rift.core.canonical"
            ),
        ),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert probe.returncode != 0
    assert "CanonicalJSONError" in probe.stderr
    assert sentinel.read_text("ascii") == "executed"
    sentinel.unlink()

    bytecode_before = _repository_bytecode_inventory(root)
    result = _safe_help(root, script)
    assert result.returncode == 0, result.stderr
    assert "--apply" in result.stdout
    assert not sentinel.exists()
    assert _repository_bytecode_inventory(root) == bytecode_before


@pytest.mark.parametrize("name", ("ignored-shadow.pyc", "ignored-shadow.pyd"))
def test_ignored_direct_or_native_repository_code_is_rejected_before_import(
    tmp_path: Path,
    name: str,
) -> None:
    root, script = _fixture_repository(tmp_path)
    (root / "src" / name).write_bytes(b"forbidden ignored executable\n")

    result = _safe_help(root, script)

    assert result.returncode != 0
    assert "sourceless or native code" in result.stderr


def test_root_and_src_yaml_shadows_and_environment_startup_hooks_are_inert(
    tmp_path: Path,
) -> None:
    root, script = _fixture_repository(tmp_path)
    sentinels = {
        name: tmp_path / f"{name}.txt"
        for name in (
            "appdata-pth",
            "appdata-sitecustomize",
            "pythonpath-sitecustomize",
            "root-yaml",
            "src-yaml",
            "userbase-pth",
            "userbase-usercustomize",
        )
    }
    (root / "yaml.py").write_text(
        _sentinel_source(sentinels["root-yaml"]), encoding="ascii"
    )
    (root / "src" / "yaml.py").write_text(
        _sentinel_source(sentinels["src-yaml"]), encoding="ascii"
    )

    version = f"Python{sys.version_info.major}{sys.version_info.minor}"
    fake_appdata_site = (
        tmp_path / "fake-appdata" / "Python" / version / "site-packages"
    )
    fake_userbase_site = (
        tmp_path / "fake-userbase" / "Lib" / "site-packages"
    )
    fake_pythonpath = tmp_path / "fake-pythonpath"
    for directory in (fake_appdata_site, fake_userbase_site, fake_pythonpath):
        directory.mkdir(parents=True)
    (fake_appdata_site / "sitecustomize.py").write_text(
        _sentinel_source(sentinels["appdata-sitecustomize"]),
        encoding="ascii",
    )
    (fake_appdata_site / "poison.pth").write_text(
        "import pathlib; "
        f"pathlib.Path({str(sentinels['appdata-pth'])!r}).write_text('executed')\n",
        encoding="ascii",
    )
    (fake_userbase_site / "usercustomize.py").write_text(
        _sentinel_source(sentinels["userbase-usercustomize"]),
        encoding="ascii",
    )
    (fake_userbase_site / "poison.pth").write_text(
        "import pathlib; "
        f"pathlib.Path({str(sentinels['userbase-pth'])!r}).write_text('executed')\n",
        encoding="ascii",
    )
    (fake_pythonpath / "sitecustomize.py").write_text(
        _sentinel_source(sentinels["pythonpath-sitecustomize"]),
        encoding="ascii",
    )
    environment = dict(os.environ)
    environment.update(
        {
            "APPDATA": str(tmp_path / "fake-appdata"),
            "PYTHONPATH": str(fake_pythonpath),
            "PYTHONUSERBASE": str(tmp_path / "fake-userbase"),
        }
    )

    bytecode_before = _repository_bytecode_inventory(root)
    result = _safe_help(root, script, environment=environment)

    assert result.returncode == 0, result.stderr
    assert "--apply" in result.stdout
    assert not [path for path in sentinels.values() if path.exists()]
    assert _repository_bytecode_inventory(root) == bytecode_before == ()
