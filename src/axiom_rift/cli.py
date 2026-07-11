"""Small durable local command surface for status and recovery."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from axiom_rift.core.canonical import canonical_text
from axiom_rift.operations.writer import StateWriter
from axiom_rift.storage.state import ControlStore


def _root(value: str) -> Path:
    root = Path(value).resolve()
    if not (root / "OPERATING_DIRECTION.md").is_file():
        raise argparse.ArgumentTypeError("root has no OPERATING_DIRECTION.md")
    return root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom")
    parser.add_argument("--root", type=_root, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("recover")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = Path(arguments.root).resolve()
    try:
        if arguments.command == "status":
            control = ControlStore(root / "state" / "control.json").read()
            if control is None:
                raise RuntimeError("control state is not initialized")
            report = {
                "schema": "axiom_status",
                "revision": control["revision"],
                "initiative": control["initiative"],
                "scientific_claim": control["scientific"]["claim"],
                "active_mission": control["scientific"]["active_mission"],
                "next_action": control["next_action"],
            }
        else:
            report = {"schema": "axiom_recovery", **StateWriter(root).recover()}
        print(canonical_text(report))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"axiom: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
