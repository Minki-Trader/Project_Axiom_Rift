"""Bounded V2.1 CLI; one invocation performs at most one declared action."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.git_closeout import verify_metadata_checkpoint
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.state.transitions import make_next_action, validate_next_action


GOAL_ACTION_SCHEMA = "axiom_rift_v21_goal_action_v1"
GOAL_ACTION_KINDS = (
    "validate_surface",
    "reconcile_state",
    "git_closeout",
    "execute_declared_job",
    "terminal",
)
DECLARED_JOB_KINDS = (
    "data_identity",
    "reference_fixture",
    "scout",
    "nested_scout",
    "confirmation",
    "promotion",
    "materialization",
)
TERMINAL_OUTCOMES = (
    "completed_pre_live_handoff",
    "closed_no_candidate",
    "blocked_external",
    "stopped_by_user",
)
FORBIDDEN_ACTION_KEYS = {
    "callable",
    "command",
    "import",
    "import_path",
    "module",
    "python",
    "shell",
}


class GoalActionError(ValueError):
    """Raised when a goal action is not explicit, bounded, and whitelisted."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="show compact V2 state without evidence payloads")
    goal_run = subparsers.add_parser("goal-run", help="return one preregistered deterministic action")
    goal_run.add_argument("--action-file", default=None)
    resume = subparsers.add_parser("resume", help="resume exactly one preregistered action")
    resume.add_argument("--action-file", default=None)
    resume.add_argument("--resume-token", default=None)
    validate = subparsers.add_parser("validate-surface", help="check one receipt-keyed activation surface")
    validate.add_argument(
        "--surface",
        required=True,
    )
    validate.add_argument("--slice-id", required=True)
    validate.add_argument("--recheck", action="store_true")
    validate.add_argument("--record-id", default=None)
    validate.add_argument("--hard-ceiling-seconds", type=float, default=30.0)
    reconcile = subparsers.add_parser("reconcile-state", help="report or apply a pending safe control recovery")
    reconcile.add_argument("--apply", action="store_true")
    subparsers.add_parser(
        "diagnostic-validate-bootstrap",
        help="legacy bootstrap diagnostic; it does not run evidence jobs",
    )
    return parser


def _json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="ascii"))
    else:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise GoalActionError("goal action root must be a mapping")
    return payload


def _contains_forbidden_action_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in FORBIDDEN_ACTION_KEYS or _contains_forbidden_action_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_action_key(item) for item in value)
    return False


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoalActionError(f"goal action requires {key}")
    return value


def load_goal_action(path: Path) -> dict[str, Any]:
    """Load one explicit action; no hypothesis, module, or command is inferred."""

    payload = _load_mapping(path)
    allowed_top_level = {"schema", "goal_id", "action_id", "action_kind", "parameters"}
    extra_top_level = sorted(set(payload) - allowed_top_level)
    if extra_top_level:
        raise GoalActionError(f"goal action has unsupported fields: {extra_top_level}")
    if payload.get("schema") != GOAL_ACTION_SCHEMA:
        raise GoalActionError("goal action schema mismatch")
    goal_id = _require_string(payload, "goal_id")
    action_id = _require_string(payload, "action_id")
    action_kind = _require_string(payload, "action_kind")
    if action_kind not in GOAL_ACTION_KINDS:
        raise GoalActionError(f"goal action kind is not whitelisted: {action_kind}")
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        raise GoalActionError("goal action parameters must be a mapping")
    if _contains_forbidden_action_key(parameters):
        raise GoalActionError("goal action may not contain module, import, callable, shell, or command keys")

    normalized: dict[str, Any]
    if action_kind == "validate_surface":
        _reject_extra_parameters(parameters, {"surface", "slice_id"})
        surface = _require_string(parameters, "surface")
        if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in surface):
            raise GoalActionError("validation surface name is not a safe declarative identifier")
        normalized = {"surface": surface, "slice_id": _require_string(parameters, "slice_id")}
    elif action_kind == "reconcile_state":
        _reject_extra_parameters(parameters, {"expected_revision"})
        expected_revision = parameters.get("expected_revision")
        if not isinstance(expected_revision, int) or expected_revision < 1:
            raise GoalActionError("reconcile_state requires a positive expected_revision")
        normalized = {"expected_revision": expected_revision}
    elif action_kind == "git_closeout":
        _reject_extra_parameters(parameters, {"declared_paths", "commit_message"})
        paths = parameters.get("declared_paths")
        message = parameters.get("commit_message")
        if not isinstance(paths, list) or not paths or not all(isinstance(item, str) and item for item in paths):
            raise GoalActionError("git_closeout requires declared_paths")
        if not isinstance(message, str) or not message or "\n" in message or "\r" in message:
            raise GoalActionError("git_closeout requires one commit-message line")
        normalized = {"declared_paths": list(dict.fromkeys(paths)), "commit_message": message}
    elif action_kind == "execute_declared_job":
        _reject_extra_parameters(
            parameters,
            {"job_id", "job_kind", "spec_object_id", "hypothesis_id"},
        )
        job_kind = _require_string(parameters, "job_kind")
        if job_kind not in DECLARED_JOB_KINDS:
            raise GoalActionError(f"job kind is not whitelisted: {job_kind}")
        spec_object_id = _require_string(parameters, "spec_object_id")
        if len(spec_object_id) != 64 or any(char not in "0123456789abcdef" for char in spec_object_id):
            raise GoalActionError("declared job requires a lowercase SHA-256 spec_object_id")
        normalized = {
            "job_id": _require_string(parameters, "job_id"),
            "job_kind": job_kind,
            "spec_object_id": spec_object_id,
        }
        if job_kind in {
            "scout",
            "nested_scout",
            "confirmation",
            "promotion",
            "materialization",
        }:
            normalized["hypothesis_id"] = _require_string(parameters, "hypothesis_id")
    else:
        _reject_extra_parameters(parameters, {"outcome", "basis_receipt_ids"})
        outcome = _require_string(parameters, "outcome")
        receipt_ids = parameters.get("basis_receipt_ids")
        if outcome not in TERMINAL_OUTCOMES:
            raise GoalActionError("terminal outcome is not allowed")
        if not isinstance(receipt_ids, list) or not receipt_ids or not all(
            isinstance(item, str) and item for item in receipt_ids
        ):
            raise GoalActionError("terminal action requires basis_receipt_ids")
        normalized = {"outcome": outcome, "basis_receipt_ids": list(dict.fromkeys(receipt_ids))}
    return {
        "schema": GOAL_ACTION_SCHEMA,
        "goal_id": goal_id,
        "action_id": action_id,
        "action_kind": action_kind,
        "parameters": normalized,
    }


def _reject_extra_parameters(parameters: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(parameters) - allowed)
    if extra:
        raise GoalActionError(f"goal action parameters are unsupported: {extra}")


def structured_goal_action(
    action: dict[str, Any],
    *,
    mode: str,
    resume_token: str | None = None,
) -> dict[str, Any]:
    if mode not in {"goal-run", "resume"}:
        raise GoalActionError("goal action mode must be goal-run or resume")
    if "kind" in action:
        validate_next_action(action)
        action_hash = sha256_payload(action)
        action_id = action_hash[:16]
        goal_id = action.get("goal_id")
    else:
        action_hash = sha256_payload(action)
        action_id = action["action_id"]
        goal_id = action["goal_id"]
    if mode == "resume" and resume_token is not None and resume_token != action_id:
        raise GoalActionError("resume token must equal the structured action identity")
    return {
        "schema": "axiom_rift_v21_goal_step_v1",
        "mode": mode,
        "goal_id": goal_id,
        "action_id": action_id,
        "action_sha256": action_hash,
        "action": action,
        "bounded_steps": 1,
        "daemon": False,
        "hypothesis_invented": False,
        "side_effects_executed": False,
        "status": "declared_action_ready",
    }


def load_control_action(root: Path, *, resume: bool = False) -> dict[str, Any]:
    from axiom_rift.v2.state.store import ControlStore

    state = ControlStore(root / "registries/v2/control_state.yaml").load()
    if resume:
        job = state.get("reentry", {}).get("active_job")
        if not isinstance(job, dict):
            raise GoalActionError("resume requires a declared active_job")
        action = make_next_action(
            "resume_job",
            goal_id=job.get("goal_id"),
            stage=state.get("cursor", {}).get("stage"),
            subject_id=job.get("stage_id"),
            job_kind=job.get("kind"),
            summary=job.get("resume_action"),
        )
    else:
        root_mission = state.get("root_mission", {})
        if root_mission.get("status") == "terminal_pending_push":
            checkpoint = verify_metadata_checkpoint(
                root,
                state.get("reentry", {}).get("git_sync"),
            )
            if checkpoint.ok:
                action = make_next_action(
                    "none",
                    summary=f"verified root terminal: {root_mission.get('terminal_outcome')}",
                )
            else:
                action = state.get("cursor", {}).get("next_action")
        else:
            action = state.get("cursor", {}).get("next_action")
        validate_next_action(action)
    return action


def compact_status(root: Path) -> dict[str, Any]:
    from axiom_rift.v2.state.store import ControlStore

    state = ControlStore(root / "registries/v2/control_state.yaml").load()
    cursor = state.get("cursor", {})
    claim = state.get("claim", {})
    reentry = state.get("reentry", {})
    root_mission = dict(state.get("root_mission", {}))
    checkpoint = verify_metadata_checkpoint(root, reentry.get("git_sync"))
    if root_mission.get("status") == "terminal_pending_push" and checkpoint.ok:
        effective_root_status = "terminal"
        effective_terminal_outcome = root_mission.get("terminal_outcome")
    else:
        effective_root_status = root_mission.get("status")
        effective_terminal_outcome = (
            root_mission.get("terminal_outcome")
            if root_mission.get("status") == "terminal"
            else None
        )
    return {
        "schema": "axiom_rift_v21_compact_status_v1",
        "revision": state.get("revision"),
        "status": state.get("status"),
        "active_truth": state.get("active_truth"),
        "root_mission": root_mission,
        "effective_root_status": effective_root_status,
        "effective_terminal_outcome": effective_terminal_outcome,
        "mission_budget": state.get("mission_budget"),
        "slice_budget": state.get("slice_budget"),
        "cursor": {
            key: cursor.get(key)
            for key in (
                "active_goal_id",
                "active_hypothesis_id",
                "stage",
                "stage_id",
                "stage_status",
                "stage_outcome",
                "terminal_outcome",
                "next_action",
            )
        },
        "claim": {
            "subject_id": claim.get("subject_id"),
            "current_level": claim.get("current_level"),
            "claim_ceiling": claim.get("claim_ceiling"),
            "blocked_by": claim.get("blocked_by", []),
        },
        "reentry": {
            "active_slice_id": reentry.get("active_slice_id"),
            "active_job": reentry.get("active_job"),
            "blocker": reentry.get("blocker"),
            "git_sync": reentry.get("git_sync", reentry.get("git_closeout")),
            "git_sync_effective": checkpoint.to_payload(),
        },
        "daemon": False,
    }


def reconcile_state(root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Report ledger drift and optionally finish one verified pending control replace."""

    from axiom_rift.v2.operations import V2OperationWriter

    registry = root / "registries/v2"
    writer = V2OperationWriter(
        object_dir=registry / "objects",
        control_state=registry / "control_state.yaml",
        hypothesis_ledger=registry / "hypothesis_ledger.jsonl",
        evidence_ledger=registry / "evidence_ledger.jsonl",
        material_ledger=registry / "material_ledger.jsonl",
        validation_receipt_ledger=registry / "validation_receipts.jsonl",
    )
    before = writer.reconciliation_report()
    mutation_performed = False
    if apply and before.get("pending_control_recovery"):
        writer.recover_pending_control()
        mutation_performed = True
    after = writer.reconciliation_report()
    actions = [
        {"ledger": name, **detail}
        for name, detail in after["ledgers"].items()
        if detail["status"] != "in_sync"
    ]
    return {
        "schema": "axiom_rift_v21_reconcile_state_v1",
        "status": "aligned" if after["ok"] else "reconciliation_required",
        "revision": writer.control.load()["revision"],
        "actions": actions,
        "pending_control_recovery": after.get("pending_control_recovery", False),
        "mutation_performed": mutation_performed,
        "bounded_steps": 1,
        "daemon": False,
    }


def _receipt_store(root: Path):
    from axiom_rift.v2.identity import ObjectStore
    from axiom_rift.v2.ledger import HashChainLedger
    from axiom_rift.v2.validation.receipts import ValidationReceiptStore

    return ValidationReceiptStore(
        ObjectStore(root / "registries/v2/objects"),
        HashChainLedger(root / "registries/v2/validation_receipts.jsonl", "validation_receipt"),
    )


def load_validation_surface(root: Path, surface: str) -> dict[str, Any]:
    """Return focused and forbidden checks from the optional surface registry."""

    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in surface):
        raise ValueError("validation surface name is not a safe declarative identifier")
    path = root / "configs/v2/validation_surfaces.yaml"
    if not path.exists():
        if surface in {"activation-candidate", "activation-active"}:
            return {
                "surface": surface,
                "focused_checks": ["activation_receipt_chain"],
                "forbidden_checks": ["data_build", "model_training", "mt5_test", "onnx_export", "download"],
                "source": "built_in_activation_fallback",
            }
        raise ValueError(f"validation surface registry is missing: {path}")
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="ascii"))
    surfaces = payload.get("surfaces") if isinstance(payload, dict) else None
    if isinstance(surfaces, dict) and surface not in surfaces and surface in {
        "activation-candidate",
        "activation-active",
    }:
        return {
            "surface": surface,
            "focused_checks": ["activation_receipt_chain"],
            "forbidden_checks": ["data_build", "model_training", "mt5_test", "onnx_export", "download"],
            "source": "built_in_activation_fallback",
        }
    if not isinstance(surfaces, dict) or surface not in surfaces:
        raise ValueError(f"validation surface is not declared: {surface}")
    entry = surfaces[surface]
    if not isinstance(entry, dict):
        raise ValueError(f"validation surface entry must be a mapping: {surface}")
    focused = entry.get("focused_checks", entry.get("checks", []))
    forbidden = entry.get("forbidden_checks", entry.get("forbidden", []))
    if not isinstance(focused, list) or not all(isinstance(item, str) and item for item in focused):
        raise ValueError("focused_checks must be a list of identifiers")
    if not isinstance(forbidden, list) or not all(isinstance(item, str) and item for item in forbidden):
        raise ValueError("forbidden_checks must be a list of identifiers")
    forbidden_actions = {"data_build", "model_training", "mt5_test", "onnx_export", "download"}
    if forbidden_actions.intersection(focused):
        raise ValueError("focused validation checks may not launch evidence jobs")
    return {
        "surface": surface,
        "focused_checks": list(focused),
        "forbidden_checks": list(forbidden),
        "source": path.relative_to(root).as_posix(),
    }


def _validate_surface(args: argparse.Namespace, root: Path) -> int:
    from datetime import datetime, timezone

    from axiom_rift.v2.validation.activation import validate_v2_activation
    from axiom_rift.v2.validation.budget import (
        IdenticalFailedValidationError,
        SliceValidationBudget,
        ValidationBudgetError,
    )
    from axiom_rift.v2.validation.cache import activation_validation_identity
    from axiom_rift.v2.validation.harness import (
        harness_validation_identity,
        validate_v21_harness,
    )
    from axiom_rift.v2.validation.governance import (
        governance_validation_identity,
        validate_v22_quant_governance,
    )

    if args.hard_ceiling_seconds <= 0 or args.hard_ceiling_seconds > 30:
        _json({"status": "blocked", "code": "invalid_hard_ceiling", "maximum_seconds": 30})
        return 2
    declaration = load_validation_surface(root, args.surface)
    executable_surfaces = {
        "activation-candidate",
        "activation-active",
        "v2_1_harness",
        "v2_2_quant_governance",
    }
    if args.surface not in executable_surfaces:
        _json(
            {
                "schema": "axiom_rift_v21_validate_surface_v1",
                "status": "declared_focused_checks",
                "surface": declaration,
                "execution": "declaration_only",
                "evidence_jobs_launched": False,
                "daemon": False,
            }
        )
        return 0
    if args.surface == "v2_2_quant_governance":
        phase = None
        identity = governance_validation_identity(root)
    elif args.surface == "v2_1_harness":
        phase = None
        identity = harness_validation_identity(root)
    else:
        phase = args.surface.removeprefix("activation-")
        identity = activation_validation_identity(root, phase)
    store = _receipt_store(root)
    budget = SliceValidationBudget(
        args.slice_id,
        store,
        hard_ceiling_seconds=args.hard_ceiling_seconds,
    )
    try:
        authorization = budget.authorize_validation(identity["validation_key"], recheck=args.recheck)
    except (IdenticalFailedValidationError, ValidationBudgetError) as exc:
        _json(
            {
                "schema": "axiom_rift_v21_validate_surface_v1",
                "status": "blocked",
                "code": type(exc).__name__,
                "detail": str(exc),
                "budget": budget.to_payload(),
            }
        )
        return 2
    if authorization.cache_hit:
        _json(
            {
                "schema": "axiom_rift_v21_validate_surface_v1",
                "status": "cache_hit",
                "surface": declaration,
                "authorization": authorization.to_payload(),
                "budget": budget.to_payload(),
            }
        )
        return 0
    if root.resolve() == PROJECT_ROOT.resolve():
        import yaml

        state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
        slice_budget = state.get("slice_budget") if isinstance(state, dict) else None
        if isinstance(slice_budget, dict):
            from axiom_rift.v2.operations import V2OperationWriter

            V2OperationWriter().consume_slice_budget(
                phase="recheck" if args.recheck else "validation",
                validation_key=identity["validation_key"],
                expected_slice_id=args.slice_id,
                idempotency_key=(
                    f"authorize_{args.slice_id}_{'recheck' if args.recheck else 'validation'}_"
                    f"{identity['validation_key']}"
                ),
            )
    if args.surface == "v2_2_quant_governance":
        result, receipt = validate_v22_quant_governance(root)
    elif args.surface == "v2_1_harness":
        result, receipt = validate_v21_harness(root)
    else:
        result, receipt = validate_v2_activation(root, str(phase))
    try:
        budget.check_duration(float(receipt["duration_seconds"]))
    except ValidationBudgetError as exc:
        receipt = dict(receipt)
        receipt["outcome"] = "fail"
        receipt["issues"] = [
            *list(receipt.get("issues", [])),
            {"code": "validation_budget_exceeded", "path": args.slice_id, "detail": str(exc)},
        ]
        result_code = 2
    else:
        result_code = 0 if result.ok else 1
    receipt = {**receipt, "slice_id": args.slice_id}
    record = None
    if args.record_id is not None:
        if root.resolve() == PROJECT_ROOT.resolve():
            from axiom_rift.v2.operations import V2OperationWriter

            current_cursor = compact_status(root)["cursor"]
            next_action = current_cursor.get("next_action")
            if next_action is None:
                next_action = "continue_from_activation_validation_receipt"
            state = V2OperationWriter().record_validation_receipt(
                receipt_id=args.record_id,
                receipt=receipt,
                idempotency_key=f"record_{args.record_id}",
                exact_next_action=next_action,
            )
            record = {"state_revision": state["revision"]}
        else:
            occurred = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            object_id, row = store.record(args.record_id, occurred, receipt)
            record = {"receipt_object_id": object_id, "ledger_seq": row["ledger_seq"]}
    _json(
        {
            "schema": "axiom_rift_v21_validate_surface_v1",
            "status": "pass" if result_code == 0 else "fail",
            "surface": declaration,
            "authorization": authorization.to_payload(),
            "budget": budget.to_payload(),
            "result": result.to_dict(),
            "receipt": receipt,
            "record": record,
        }
    )
    return result_code


def main(argv: list[str] | None = None, *, root: Path = PROJECT_ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "status":
            _json(compact_status(root))
            return 0
        if args.command in {"goal-run", "resume"}:
            action = (
                load_goal_action(Path(args.action_file))
                if args.action_file is not None
                else load_control_action(root, resume=args.command == "resume")
            )
            _json(
                structured_goal_action(
                    action,
                    mode=args.command,
                    resume_token=getattr(args, "resume_token", None),
                )
            )
            return 0
        if args.command == "validate-surface":
            return _validate_surface(args, root)
        if args.command == "reconcile-state":
            payload = reconcile_state(root, apply=args.apply)
            _json(payload)
            return 0 if payload["status"] == "aligned" else 1
        if args.command == "diagnostic-validate-bootstrap":
            from axiom_rift.v2.validation import validate_v2_bootstrap

            result = validate_v2_bootstrap(root)
            _json(result.to_dict())
            return 0 if result.ok else 1
    except (GoalActionError, OSError, RuntimeError, ValueError) as exc:
        _json(
            {
                "schema": "axiom_rift_v21_cli_error_v1",
                "status": "blocked",
                "code": type(exc).__name__,
                "detail": str(exc),
                "daemon": False,
            }
        )
        return 2
    raise RuntimeError(f"unsupported V2 command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
