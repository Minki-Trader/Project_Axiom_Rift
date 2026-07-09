"""Small stable V2 CLI; command count does not grow with hypotheses or runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_rift.paths import PROJECT_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="show compact V2 control state")
    subparsers.add_parser("validate-bootstrap", help="validate the V2 bootstrap control plane")
    activation = subparsers.add_parser("validate-activation", help="check activation receipts without running evidence jobs")
    activation.add_argument("--phase", choices=("candidate", "active"), default="active")
    activation.add_argument("--force", action="store_true", help="ignore an identical successful receipt")
    activation.add_argument("--record-id", default=None)
    transition = subparsers.add_parser("advance-stage", help="perform an evidence-gated H/S/R/P/M transition")
    transition.add_argument("--to", required=True, choices=("H", "S", "R", "P", "M"))
    transition.add_argument("--stage-id", required=True)
    transition.add_argument("--basis-evidence-id", required=True)
    transition.add_argument("--next-action", required=True)
    transition.add_argument("--idempotency-key", required=True)
    data = subparsers.add_parser("run-data-identity", help="run the explicit corrected data identity job")
    data.add_argument("--output", default="campaigns/v2/V2G0001_v2_activation/evidence/V2DATA0002")
    fixture = subparsers.add_parser("run-reference-fixture", help="run the bounded non-economic Python/ONNX/MQL/MT5 fixture")
    fixture.add_argument("--output", default="campaigns/v2/V2G0001_v2_activation/evidence/V2FIX0001")
    smoke = subparsers.add_parser("run-reference-online-smoke", help="run the bounded native real-tick reference EA smoke")
    smoke.add_argument("--output", default="campaigns/v2/V2G0001_v2_activation/evidence/V2MT50001")
    scout = subparsers.add_parser("run-scout", help="run one preregistered declarative S job")
    scout.add_argument("--output", required=True)
    return parser


def _json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _validate_activation(args: argparse.Namespace) -> int:
    from axiom_rift.v2.identity import ObjectStore
    from axiom_rift.v2.ledger import HashChainLedger
    from axiom_rift.v2.operations import V2OperationWriter
    from axiom_rift.v2.validation.activation import validate_v2_activation
    from axiom_rift.v2.validation.cache import activation_validation_identity
    from axiom_rift.v2.validation.receipts import ValidationReceiptStore

    identity = activation_validation_identity(PROJECT_ROOT, args.phase)
    store = ValidationReceiptStore(
        ObjectStore(PROJECT_ROOT / "registries/v2/objects"),
        HashChainLedger(PROJECT_ROOT / "registries/v2/validation_receipts.jsonl", "validation_receipt"),
    )
    if not args.force:
        cached = store.cached_success(identity["validation_key"])
        if cached is not None:
            _json({"cache_hit": True, "receipt": cached["payload"]})
            return 0
    result, receipt = validate_v2_activation(PROJECT_ROOT, args.phase)
    payload: dict[str, object] = {"cache_hit": False, "result": result.to_dict(), "receipt": receipt}
    if args.record_id is not None:
        state = V2OperationWriter().record_validation_receipt(
            receipt_id=args.record_id,
            receipt=receipt,
            idempotency_key=f"record_{args.record_id}",
            exact_next_action="continue_from_activation_validation_receipt",
        )
        payload["state_revision"] = state["revision"]
    _json(payload)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "status":
        import yaml

        _json(yaml.safe_load((PROJECT_ROOT / "registries/v2/control_state.yaml").read_text(encoding="ascii")))
        return 0
    if args.command == "validate-bootstrap":
        from axiom_rift.v2.validation import validate_v2_bootstrap

        result = validate_v2_bootstrap()
        _json(result.to_dict())
        return 0 if result.ok else 1
    if args.command == "validate-activation":
        return _validate_activation(args)
    if args.command == "advance-stage":
        from axiom_rift.v2.operations import V2OperationWriter

        state = V2OperationWriter().advance_stage(
            new_stage=args.to,
            stage_id=args.stage_id,
            basis_evidence_id=args.basis_evidence_id,
            idempotency_key=args.idempotency_key,
            exact_next_action=args.next_action,
        )
        _json(state)
        return 0
    if args.command == "run-data-identity":
        from axiom_rift.v2.jobs.data_identity import run_corrected_data_identity_job

        records, receipt = run_corrected_data_identity_job(PROJECT_ROOT / args.output)
        _json({"material_ids": [record.material_id for record in records], "receipt": receipt})
        return 0
    if args.command == "run-reference-fixture":
        from axiom_rift.v2.mt5.runner import run_reference_fixture_job

        _json(run_reference_fixture_job(PROJECT_ROOT / args.output))
        return 0
    if args.command == "run-reference-online-smoke":
        from axiom_rift.v2.mt5.runner import run_reference_online_smoke_job

        _json(run_reference_online_smoke_job(PROJECT_ROOT / args.output, real_ticks=True))
        return 0
    if args.command == "run-scout":
        from axiom_rift.v2.jobs.scout import run_v2s0001_job

        _json(run_v2s0001_job(PROJECT_ROOT / args.output))
        return 0
    raise RuntimeError(f"unsupported V2 command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
