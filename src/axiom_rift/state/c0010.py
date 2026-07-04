"""C0010 draft validators for multi-file state updates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from axiom_rift.state.transactions import StateTransaction, TransactionError


FALSE_ONLY_FLAGS = {
    "claim_authority",
    "economics_pass",
    "feature_set_selected",
    "label_selected",
    "live_ready",
    "materialization_ready",
    "model_selected",
    "onnx_ready",
    "promotion_ready",
    "runtime_authority",
    "runtime_probe_completed",
    "selected",
}


def validate_c0010_transaction(
    tx: StateTransaction,
    *,
    run_dir: Path,
    campaign_path: Path,
    reentry_path: Path,
    claim_state_path: Path,
    expected_next_action: str | None = None,
    run_id: str | None = None,
) -> None:
    """Validate the state files that C0010 MT5 recorders update together."""

    run_manifest_path = run_dir / "run_manifest.json"
    gate_report_path = run_dir / "gate_report.json"
    run_manifest = _read_json_if_present(tx, run_manifest_path)
    gate_report = _read_json_if_present(tx, gate_report_path)
    campaign = _read_yaml_if_present(tx, campaign_path)
    reentry = _read_yaml_if_present(tx, reentry_path)
    claim_state = _read_yaml_if_present(tx, claim_state_path)

    _assert_false_claim_flags(
        [
            ("run_manifest", run_manifest),
            ("gate_report", gate_report),
            ("campaign", campaign),
            ("reentry", reentry),
            ("claim_state", claim_state),
        ]
    )
    if (
        run_manifest is not None
        and gate_report is not None
        and (expected_next_action is not None or (tx.has_draft(run_manifest_path) and tx.has_draft(gate_report_path)))
    ):
        _assert_run_gate_alignment(run_manifest, gate_report)
        _assert_evidence_paths_exist(tx, run_dir, run_manifest, gate_report)
    if expected_next_action is not None:
        _assert_next_action_alignment(
            expected_next_action,
            campaign=campaign,
            reentry=reentry,
            claim_state=claim_state,
            gate_report=gate_report,
        )
        if run_id is not None and run_id.lower() not in expected_next_action.lower():
            raise TransactionError(
                f"Expected next action {expected_next_action!r} does not reference {run_id}"
            )


def _read_json_if_present(tx: StateTransaction, path: Path) -> Any | None:
    if tx.has_draft(path) or path.exists():
        return tx.read_json(path)
    return None


def _read_yaml_if_present(tx: StateTransaction, path: Path) -> Any | None:
    if tx.has_draft(path) or path.exists():
        return tx.read_yaml(path)
    return None


def _assert_run_gate_alignment(run_manifest: dict[str, Any], gate_report: dict[str, Any]) -> None:
    run_gate_status = run_manifest.get("gate_status")
    if not run_gate_status:
        return
    accepted = {
        gate_report.get("decision"),
        gate_report.get("evidence_gate", {}).get("status"),
        gate_report.get("rolling_window_closeout_gate", {}).get("status"),
    }
    if (
        run_gate_status not in accepted
        and not (
            run_gate_status == "fold_isolated_evidence_recorded_pending_closeout_review"
            and gate_report.get("evidence_gate", {}).get("status") == "fold_isolated_evidence_recorded"
        )
    ):
        raise TransactionError(
            "C0010 run_manifest.gate_status does not align with gate_report status: "
            f"{run_gate_status!r}"
        )


def _assert_evidence_paths_exist(
    tx: StateTransaction,
    run_dir: Path,
    run_manifest: dict[str, Any],
    gate_report: dict[str, Any],
) -> None:
    paths: set[str] = set()
    run_paths = run_manifest.get("evidence_paths", {})
    if isinstance(run_paths, dict):
        paths.update(str(value) for value in run_paths.values() if isinstance(value, str))
    elif isinstance(run_paths, list):
        paths.update(str(value) for value in run_paths if isinstance(value, str))
    gate_paths = gate_report.get("evidence_paths", [])
    if isinstance(gate_paths, list):
        paths.update(str(value) for value in gate_paths if isinstance(value, str))
    for rel_path in sorted(paths):
        if not _should_check_evidence_path(rel_path):
            continue
        target = (run_dir / rel_path).resolve()
        if not tx.has_draft(target) and not target.exists():
            raise TransactionError(f"C0010 evidence path is missing: {run_dir / rel_path}")


def _should_check_evidence_path(rel_path: str) -> bool:
    if rel_path.startswith("../"):
        return False
    return rel_path.startswith("kpi/") or rel_path.startswith("artifacts/") or rel_path == "artifact_lineage.json"


def _assert_next_action_alignment(
    expected_next_action: str,
    *,
    campaign: dict[str, Any] | None,
    reentry: dict[str, Any] | None,
    claim_state: dict[str, Any] | None,
    gate_report: dict[str, Any] | None,
) -> None:
    observed: list[tuple[str, Any]] = []
    if gate_report is not None:
        observed.append(("gate_report.next_action", gate_report.get("next_action")))
    if campaign is not None:
        observed.append(("campaign.closeout.remaining_question", campaign.get("closeout", {}).get("remaining_question")))
    if claim_state is not None:
        observed.append(
            (
                "claim_state.latest_operation.next_required_action",
                claim_state.get("latest_operation", {}).get("next_required_action"),
            )
        )
    if reentry is not None:
        tasks = reentry.get("next_work", {}).get("tasks") or []
        observed.append(("reentry.next_work.tasks[0]", tasks[0] if tasks else None))
    mismatches = [f"{name}={value!r}" for name, value in observed if value != expected_next_action]
    if mismatches:
        raise TransactionError(
            f"C0010 next action mismatch, expected {expected_next_action!r}: " + "; ".join(mismatches)
        )


def _assert_false_claim_flags(named_payloads: Iterable[tuple[str, Any]]) -> None:
    for name, payload in named_payloads:
        for path, key, value in _walk_flags(payload):
            if key in FALSE_ONLY_FLAGS and value is True:
                joined = ".".join(str(part) for part in path + (key,))
                raise TransactionError(f"{name} sets forbidden claim flag true: {joined}")


def _walk_flags(payload: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                yield path, key, value
            yield from _walk_flags(value, path + (key,))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk_flags(value, path + (index,))
