"""Small command line entrypoint for workspace checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collectors.mt5_fresh_export import run_terminal_export
from .paths import CAMPAIGN_DIR, CONFIG_DIR, CONTRACT_DIR, PROJECT_ROOT, REGISTRY_DIR
from .pipelines.base_frame import build_us100_m5_base_frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="print key workspace paths as JSON")
    export_parser = subparsers.add_parser("export-mt5-max-bars", help="fresh-export max MT5 bars")
    export_parser.add_argument("--symbol", default="US100")
    export_parser.add_argument("--timeframe", default="M5")
    export_parser.add_argument("--timeout-seconds", type=int, default=240)
    subparsers.add_parser("build-us100-base-frame", help="build US100 M5 base frame from raw CSV")
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
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
