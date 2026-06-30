"""Small command line entrypoint for workspace checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import CAMPAIGN_DIR, CONFIG_DIR, CONTRACT_DIR, PROJECT_ROOT, REGISTRY_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="print key workspace paths as JSON")
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
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
