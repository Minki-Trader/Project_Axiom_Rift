"""Decision-intelligence helpers for next-work scope and run pre-open checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ADJACENT_TUNING_RISK_ALLOWED = {"low", "medium"}
EXPECTED_INFORMATION_GAIN_ALLOWED = {"medium", "high"}
DECISION_PAYOFF_ALLOWED = {"medium", "high"}
MT5_PORTABILITY_ALLOWED = {"clear", "risky"}
SURFACE_DISTANCE_FIELDS = (
    "label_changed",
    "feature_changed",
    "model_changed",
    "trade_logic_changed",
)


def pre_open_required(run_manifest: dict[str, Any]) -> bool:
    """Require pre-open checks only for future/v2 manifests or explicit blocks."""
    schema = str(run_manifest.get("schema", ""))
    if schema.endswith("_v2"):
        return True
    return "pre_open_decision" in run_manifest


def validate_pre_open_decision(issues: Any, path: Path, run_manifest: dict[str, Any]) -> None:
    if not pre_open_required(run_manifest):
        return

    decision = run_manifest.get("pre_open_decision")
    if not isinstance(decision, dict):
        issues.add("pre_open_decision_missing", path, "future run requires pre_open_decision")
        return

    required = (
        "novelty_score",
        "adjacent_tuning_risk",
        "expected_information_gain",
        "failure_memory_used",
        "surface_distance",
        "mt5_portability",
        "decision_payoff",
        "reject_if_failure_only_repeats_known_negative_memory",
        "true_variant_summary",
        "adjacent_tuning_rejection_reason",
    )
    for field in required:
        if decision.get(field) in (None, "", [], {}):
            issues.add("pre_open_decision_field_missing", path, f"pre_open_decision.{field} is required")

    novelty = decision.get("novelty_score")
    if not isinstance(novelty, int) or novelty < 3 or novelty > 5:
        issues.add("pre_open_novelty_score_invalid", path, "novelty_score must be an integer from 3 to 5")

    adjacent_risk = decision.get("adjacent_tuning_risk")
    if adjacent_risk not in ADJACENT_TUNING_RISK_ALLOWED:
        issues.add("pre_open_adjacent_tuning_risk_invalid", path, "adjacent_tuning_risk must be low or medium")

    info_gain = decision.get("expected_information_gain")
    if info_gain not in EXPECTED_INFORMATION_GAIN_ALLOWED:
        issues.add("pre_open_information_gain_invalid", path, "expected_information_gain must be medium or high")

    payoff = decision.get("decision_payoff")
    if payoff not in DECISION_PAYOFF_ALLOWED:
        issues.add("pre_open_decision_payoff_invalid", path, "decision_payoff must be medium or high")

    portability = decision.get("mt5_portability")
    if portability not in MT5_PORTABILITY_ALLOWED:
        issues.add("pre_open_mt5_portability_invalid", path, "mt5_portability must be clear or risky")

    repeat_guard = decision.get("reject_if_failure_only_repeats_known_negative_memory")
    if repeat_guard is not True:
        issues.add(
            "pre_open_repeat_negative_memory_guard_missing",
            path,
            "reject_if_failure_only_repeats_known_negative_memory must be true",
        )

    surface_distance = decision.get("surface_distance")
    if not isinstance(surface_distance, dict):
        issues.add("pre_open_surface_distance_invalid", path, "surface_distance must be an object")
        return

    changed = []
    for field in SURFACE_DISTANCE_FIELDS:
        value = surface_distance.get(field)
        if not isinstance(value, bool):
            issues.add("pre_open_surface_distance_field_invalid", path, f"surface_distance.{field} must be boolean")
        changed.append(value is True)

    if not any(changed):
        issues.add(
            "pre_open_surface_distance_missing",
            path,
            "at least one label, feature, model, or trade_logic surface must change",
        )


def classify_issue_scope(issue: Any, active_run_path: str | None = None) -> dict[str, Any]:
    code = getattr(issue, "code", "")
    path = getattr(issue, "path", "")
    detail = getattr(issue, "detail", "")

    if code in {"artifact_lineage_hash_mismatch", "artifact_lineage_hash_missing"}:
        debt_class = "known_nonblocking_for_next_run_decision"
        if active_run_path and path.startswith(active_run_path):
            debt_class = "closeout_blocker"
        return {
            "class": debt_class,
            "code": code,
            "path": path,
            "detail": detail,
            "may_continue_discovery": debt_class == "known_nonblocking_for_next_run_decision",
            "blocks_selected_claim": True,
            "blocks_promotion": True,
            "blocks_handoff": True,
            "blocks_reproducibility_claim": True,
        }

    if code in {
        "active_campaign_missing",
        "active_campaign_path_missing",
        "active_synthesis_path_missing",
        "active_run_path_missing",
        "latest_operation_source_missing",
        "parse_error",
        "forbidden_claim_true",
        "claim_boundary_not_false",
        "selection_claim_true",
    }:
        return {
            "class": "active_path_blocker",
            "code": code,
            "path": path,
            "detail": detail,
            "may_continue_discovery": False,
        }

    if code in {
        "rolling_window_closeout_evidence_missing",
        "rolling_window_closeout_path_not_recorded",
        "evidence_path_missing",
    }:
        return {
            "class": "closeout_blocker",
            "code": code,
            "path": path,
            "detail": detail,
            "may_continue_current_evidence_loop": True,
            "blocks_run_or_campaign_closeout": True,
        }

    return {
        "class": "unclassified_blocker",
        "code": code,
        "path": path,
        "detail": detail,
        "may_continue_discovery": False,
    }


def debt_scope_summary(issues: tuple[Any, ...], active_run_path: str | None = None) -> dict[str, Any]:
    errors = [issue for issue in issues if getattr(issue, "severity", "") == "error"]
    classified = [classify_issue_scope(issue, active_run_path=active_run_path) for issue in errors]
    blocking_classes = {"active_path_blocker", "closeout_blocker", "unclassified_blocker"}
    blockers = [item for item in classified if item["class"] in blocking_classes]
    return {
        "global_repo_state_ok": not errors,
        "next_work_decision_may_continue": not blockers,
        "debt_classes": classified,
    }
