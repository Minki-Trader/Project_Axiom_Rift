"""MT5 terminal state cleanup for headless CLI runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


HEADLESS_PROFILE_NAME = "AxiomRiftHeadless"


@dataclass(frozen=True)
class TerminalHygieneResult:
    data_dir: Path
    profile_dir: Path
    changed_files: tuple[Path, ...]
    removed_chart_files: tuple[Path, ...]


def prepare_headless_terminal(data_dir: Path, profile_name: str = HEADLESS_PROFILE_NAME) -> TerminalHygieneResult:
    return enforce_headless_terminal_state(data_dir, profile_name=profile_name)


def cleanup_headless_terminal(data_dir: Path, profile_name: str = HEADLESS_PROFILE_NAME) -> TerminalHygieneResult:
    return enforce_headless_terminal_state(data_dir, profile_name=profile_name)


def enforce_headless_terminal_state(data_dir: Path, profile_name: str = HEADLESS_PROFILE_NAME) -> TerminalHygieneResult:
    data_dir = data_dir.resolve()
    profile_dir = data_dir / "MQL5" / "Profiles" / "Charts" / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    removed_chart_files = []
    for chart_file in sorted(profile_dir.glob("*.chr")):
        chart_file.unlink()
        removed_chart_files.append(chart_file)

    changed_files = []
    common_ini = data_dir / "config" / "common.ini"
    if _rewrite_ini(
        common_ini,
        {
            "Charts": {
                "ProfileLast": profile_name,
                "SaveDeleted": "0",
                "PreloadCharts": "0",
            },
            "Experts": {
                "Chart": "0",
            },
        },
    ):
        changed_files.append(common_ini)

    terminal_ini = data_dir / "config" / "terminal.ini"
    if _rewrite_ini(
        terminal_ini,
        {
            "CodeBasesList": {
                "MQL5AddChart": "0",
            },
            "Tester": {
                "Visualization": "0",
            },
        },
    ):
        changed_files.append(terminal_ini)

    return TerminalHygieneResult(
        data_dir=data_dir,
        profile_dir=profile_dir,
        changed_files=tuple(changed_files),
        removed_chart_files=tuple(removed_chart_files),
    )


def _rewrite_ini(path: Path, updates: dict[str, dict[str, str]]) -> bool:
    original = path.read_bytes() if path.exists() else b""
    original_text = _decode_mt5_ini(original)
    original_lines = original_text.splitlines()
    updated_lines = _apply_ini_updates(original_lines, updates)
    updated_text = "\r\n".join(updated_lines)
    if updated_lines:
        updated_text += "\r\n"
    updated = updated_text.encode("utf-16")
    if updated == original:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(updated)
    return True


def _decode_mt5_ini(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-16", errors="ignore")


def _apply_ini_updates(lines: list[str], updates: dict[str, dict[str, str]]) -> list[str]:
    remaining = {section: values.copy() for section, values in updates.items()}
    output: list[str] = []
    section: str | None = None

    def flush_missing(target_section: str | None) -> None:
        if target_section is None:
            return
        missing = remaining.get(target_section)
        if not missing:
            return
        for key, value in list(missing.items()):
            output.append(f"{key}={value}")
            del missing[key]

    for line in lines:
        parsed_section = _parse_section(line)
        if parsed_section is not None:
            flush_missing(section)
            section = parsed_section
            output.append(line)
            continue

        replacement = _replacement_line(section, line, remaining)
        output.append(replacement if replacement is not None else line)

    flush_missing(section)
    for target_section, missing in remaining.items():
        if not missing:
            continue
        if output and output[-1] != "":
            output.append("")
        output.append(f"[{target_section}]")
        for key, value in missing.items():
            output.append(f"{key}={value}")
    return output


def _parse_section(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    return stripped[1:-1]


def _replacement_line(section: str | None, line: str, remaining: dict[str, dict[str, str]]) -> str | None:
    if section is None or section not in remaining or "=" not in line:
        return None
    key, _value = line.split("=", 1)
    missing = remaining[section]
    if key not in missing:
        return None
    value = missing.pop(key)
    return f"{key}={value}"
