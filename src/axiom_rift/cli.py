"""Small command line entrypoint for workspace checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collectors.mt5_fresh_export import run_terminal_export
from .paths import CAMPAIGN_DIR, CONFIG_DIR, CONTRACT_DIR, PROJECT_ROOT, REGISTRY_DIR
from .pipelines.base_frame import build_us100_m5_base_frame
from .pipelines.clean_periods import derive_clean_periods
from .pipelines.rolling_windows import build_rolling_windows
from .validation.work_units import result_json, validate_templates, validate_work_unit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="print key workspace paths as JSON")
    export_parser = subparsers.add_parser("export-mt5-max-bars", help="fresh-export max MT5 bars")
    export_parser.add_argument("--symbol", default="US100")
    export_parser.add_argument("--timeframe", default="M5")
    export_parser.add_argument("--timeout-seconds", type=int, default=240)
    subparsers.add_parser("build-us100-base-frame", help="build US100 M5 base frame from raw CSV")
    subparsers.add_parser("derive-us100-clean-periods", help="derive clean period candidates")
    subparsers.add_parser("build-us100-rolling-windows", help="build rolling-window split registry")
    subparsers.add_parser("validate-templates", help="validate campaign templates and contract alignment")
    work_unit_parser = subparsers.add_parser("validate-work-unit", help="validate a generated campaign work unit")
    work_unit_parser.add_argument("path", help="path such as campaigns/C0001_short_slug")
    return parser


def status_payload() -> dict[str, str]:
    paths: dict[str, Path] = {
        "project_root": PROJECT_ROOT,
        "configs": CONFIG_DIR,
        "contracts": CONTRACT_DIR,
        "campaigns": CAMPAIGN_DIR,
        "registries": REGISTRY_DIR,
        "claim_state": REGISTRY_DIR / "claim_state.yaml",
        "reentry": REGISTRY_DIR / "reentry.yaml",
    }
    return {key: value.as_posix() for key, value in paths.items()}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status_payload(), indent=2, sort_keys=True))
        return 0
    if args.command == "export-mt5-max-bars":
        result = run_terminal_export(args.symbol, args.timeframe, timeout_seconds=args.timeout_seconds)
        print(
            json.dumps(
                {
                    "raw_csv": result.raw_csv.as_posix(),
                    "row_count": result.row_count,
                    "first_time": result.first_time,
                    "last_time": result.last_time,
                    "sha256": result.sha256,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "build-us100-base-frame":
        coverage = build_us100_m5_base_frame()
        print(json.dumps(coverage, indent=2, sort_keys=True))
        return 0
    if args.command == "derive-us100-clean-periods":
        payload = derive_clean_periods()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "build-us100-rolling-windows":
        payload = build_rolling_windows()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-templates":
        result = validate_templates()
        print(result_json(result))
        return 0 if result.ok else 1
    if args.command == "validate-work-unit":
        result = validate_work_unit(Path(args.path))
        print(result_json(result))
        return 0 if result.ok else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
