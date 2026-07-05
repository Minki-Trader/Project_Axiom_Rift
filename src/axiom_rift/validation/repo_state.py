"""Validate whole-repository operating state without mutating files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.validation.decision_intelligence import debt_scope_summary
from axiom_rift.validation.price_quality import BASE_FRAME_RELATIVE_PATH, PRICE_QUALITY_AUDIT_RELATIVE_PATH
from axiom_rift.validation.work_units import (
    CLOSEOUT_DECISIONS,
    CLOSED_RUN_STATUSES,
    IssueCollector,
    ValidationResult,
    check_rolling_window_closeout_evidence,
    get_path,
    safe_load_structured,
)


FORBIDDEN_ACTIVE_CLAIMS = {
    "runtime_authority",
    "live_ready",
    "selected",
    "promotion_ready",
    "onnx_ready",
    "model_selected",
    "feature_set_selected",
    "label_selected",
}


@dataclass(frozen=True)
class RepoStateValidationResult(ValidationResult):
    active_run_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload["blocking_issues"] = [
            issue.to_dict() for issue in self.issues if issue.severity == "error"
        ]
        payload["warnings"] = [
            issue.to_dict() for issue in self.issues if issue.severity == "warning"
        ]
        payload["decision_scope"] = debt_scope_summary(
            self.issues,
            active_run_path=self.active_run_path,
        )
        return payload


def validate_repo_state(root: Path = PROJECT_ROOT) -> RepoStateValidationResult:
    root = root.resolve()
    issues = IssueCollector(root)

    claim_state_path = root / "registries" / "claim_state.yaml"
    reentry_path = root / "registries" / "reentry.yaml"
    runtime_config_path = root / "configs" / "runtime.yaml"
    claim_state = safe_load_structured(issues, claim_state_path)
    reentry = safe_load_structured(issues, reentry_path)
    runtime_config = safe_load_structured(issues, runtime_config_path)

    check_runtime_config(issues, runtime_config_path, runtime_config)
    check_price_quality_audit(issues, root)
    check_forbidden_claims(issues, claim_state_path, claim_state)
    check_forbidden_claims(issues, reentry_path, reentry)

    active_campaign_rel = active_campaign_from_state(claim_state, reentry)
    allow_no_active_campaign = no_active_campaign_after_closeout_allowed(claim_state, reentry)
    campaign_root = resolve_repo_path(root, active_campaign_rel) if active_campaign_rel else None
    campaign = None
    if campaign_root is None:
        if not allow_no_active_campaign:
            issues.add("active_campaign_missing", claim_state_path, "active campaign is not recorded")
    elif not campaign_root.exists():
        issues.add("active_campaign_path_missing", campaign_root, "active campaign path does not exist")
    else:
        campaign = safe_load_structured(issues, campaign_root / "campaign.yaml")
        check_forbidden_claims(issues, campaign_root / "campaign.yaml", campaign)

    check_active_campaign_alignment(issues, claim_state, reentry)
    latest_run = latest_run_from_state(root, issues, claim_state)
    check_active_run_alignment(issues, claim_state, campaign, campaign_root, latest_run)
    check_latest_operation_alignment(
        issues,
        root,
        claim_state,
        reentry,
        campaign,
        latest_run,
        allow_no_active_campaign=allow_no_active_campaign,
    )
    if latest_run is not None:
        check_latest_run_evidence(issues, latest_run)

    check_closed_runs(root, issues)
    check_artifact_lineage_hashes(root, issues)
    active_run_display = display_rel(root, latest_run) if latest_run is not None else None
    return RepoStateValidationResult("repo-state", tuple(issues.issues), active_run_display)


def check_runtime_config(issues: IssueCollector, path: Path, data: Any) -> None:
    if not path.exists():
        issues.add("runtime_config_missing", path, "configs/runtime.yaml is missing")
        return
    if not isinstance(data, dict):
        return
    complete = data.get("active_runtime_config_complete")
    if complete is None:
        complete = get_path(data, "claim_boundary.active_runtime_config_complete")
    if complete is not True:
        issues.add(
            "runtime_config_incomplete",
            path,
            "active_runtime_config_complete is not true",
            severity="warning",
        )
    check_forbidden_claims(issues, path, data)


def check_price_quality_audit(issues: IssueCollector, root: Path) -> None:
    audit_path = root / PRICE_QUALITY_AUDIT_RELATIVE_PATH
    base_frame_path = root / BASE_FRAME_RELATIVE_PATH
    if not base_frame_path.exists():
        issues.add("base_frame_missing", base_frame_path, "US100 M5 base-frame CSV is missing")
        return
    if not audit_path.exists():
        issues.add("price_quality_audit_missing", audit_path, "US100 M5 price quality audit is missing")
        return
    audit = safe_load_structured(issues, audit_path)
    if not isinstance(audit, dict):
        return
    recorded_base = audit.get("base_frame_csv")
    if recorded_base != BASE_FRAME_RELATIVE_PATH:
        issues.add(
            "price_quality_base_frame_path_mismatch",
            audit_path,
            f"base_frame_csv must be {BASE_FRAME_RELATIVE_PATH!r}, observed {recorded_base!r}",
        )
    recorded_hash = audit.get("base_frame_sha256")
    if not isinstance(recorded_hash, str) or not recorded_hash:
        issues.add("price_quality_base_frame_hash_missing", audit_path, "base_frame_sha256 is missing")
    else:
        actual_hash = sha256_file(base_frame_path)
        if actual_hash != recorded_hash:
            issues.add(
                "price_quality_base_frame_hash_mismatch",
                audit_path,
                f"expected {recorded_hash}, actual {actual_hash}",
            )
    blocker_count = audit.get("blocker_count")
    if not isinstance(blocker_count, int):
        issues.add("price_quality_blocker_count_missing", audit_path, "blocker_count is missing or invalid")
    elif blocker_count > 0:
        issues.add(
            "price_quality_blockers_recorded",
            audit_path,
            f"price quality audit has {blocker_count} blocking issue(s)",
        )
    warning_count = audit.get("warning_count")
    if isinstance(warning_count, int) and warning_count > 0:
        issues.add(
            "price_quality_warnings_recorded",
            audit_path,
            f"price quality audit has {warning_count} warning observation(s)",
            severity="warning",
        )


def active_campaign_from_state(claim_state: Any, reentry: Any) -> str | None:
    for value in (
        get_path(claim_state, "active_campaign"),
        get_path(reentry, "next_work.campaign"),
        get_path(reentry, "project.active_campaign"),
    ):
        if isinstance(value, str) and value:
            return value
    return None


def active_synthesis_from_state(claim_state: Any, reentry: Any) -> str | None:
    for value in (
        get_path(claim_state, "active_synthesis"),
        get_path(reentry, "next_work.synthesis"),
        get_path(reentry, "project.active_synthesis"),
    ):
        if isinstance(value, str) and value:
            return value
    return None


def no_active_campaign_after_closeout_allowed(claim_state: Any, reentry: Any) -> bool:
    active_campaign = active_campaign_from_state(claim_state, reentry)
    active_run = get_path(claim_state, "active_run")
    if active_campaign or active_run:
        return False
    evidence_status = get_path(claim_state, "latest_operation.evidence_status")
    if evidence_status not in {"closed_no_candidate", "closed_with_candidate_evidence", "closed_non_portable"}:
        return False
    next_action = get_path(claim_state, "latest_operation.next_required_action")
    if not isinstance(next_action, str) or not next_action:
        next_action = first_task(reentry)
    if not isinstance(next_action, str):
        return False
    return (
        next_action.startswith("choose_c")
        or next_action.startswith("open_c")
        or next_action == "choose_or_open_next_major_campaign"
    )


def check_active_campaign_alignment(issues: IssueCollector, claim_state: Any, reentry: Any) -> None:
    observed = {
        "claim_state.active_campaign": get_path(claim_state, "active_campaign"),
        "reentry.next_work.campaign": get_path(reentry, "next_work.campaign"),
        "reentry.project.active_campaign": get_path(reentry, "project.active_campaign"),
    }
    filled = {name: value for name, value in observed.items() if isinstance(value, str) and value}
    if len(set(filled.values())) > 1:
        detail = "; ".join(f"{name}={value!r}" for name, value in sorted(filled.items()))
        issues.add("active_campaign_mismatch", "registries", detail)


def latest_run_from_state(root: Path, issues: IssueCollector, claim_state: Any) -> Path | None:
    active_run = get_path(claim_state, "active_run")
    recorded = get_path(claim_state, "latest_operation.recorded_at_source")
    inferred = run_dir_from_artifact_path(root, recorded) if isinstance(recorded, str) else None
    explicit = resolve_repo_path(root, active_run) if isinstance(active_run, str) and active_run else None
    if explicit is not None and inferred is not None and explicit.resolve() != inferred.resolve():
        issues.add(
            "active_run_latest_operation_mismatch",
            "registries/claim_state.yaml",
            f"active_run={display_rel(root, explicit)!r}; latest_operation source={display_rel(root, inferred)!r}",
        )
    latest = explicit or inferred
    if latest is not None and not latest.exists():
        issues.add("active_run_path_missing", latest, "latest active_run path does not exist")
    return latest


def check_active_run_alignment(
    issues: IssueCollector,
    claim_state: Any,
    campaign: Any,
    campaign_root: Path | None,
    latest_run: Path | None,
) -> None:
    if campaign_root is None or latest_run is None or not isinstance(campaign, dict):
        return
    campaign_active = get_path(campaign, "run_index.active_run")
    if campaign_active in (None, "", "null"):
        return
    campaign_run = resolve_run_pointer(campaign_root, campaign_active)
    if campaign_run.resolve() != latest_run.resolve():
        issues.add(
            "campaign_active_run_mismatch",
            campaign_root / "campaign.yaml",
            f"run_index.active_run={campaign_active!r}; latest operation run={display_rel(campaign_root.parent.parent, latest_run)!r}",
        )
    active_run = get_path(claim_state, "active_run")
    if isinstance(active_run, str) and active_run:
        active_run_path = resolve_repo_path(campaign_root.parent.parent, active_run)
        if active_run_path.resolve() != latest_run.resolve():
            issues.add("claim_state_active_run_mismatch", "registries/claim_state.yaml", active_run)


def check_latest_operation_alignment(
    issues: IssueCollector,
    root: Path,
    claim_state: Any,
    reentry: Any,
    campaign: Any,
    latest_run: Path | None,
    *,
    allow_no_active_campaign: bool = False,
) -> None:
    gate_report = None
    if latest_run is not None and (latest_run / "gate_report.json").exists():
        gate_report = safe_load_structured(issues, latest_run / "gate_report.json")
    recorded = get_path(claim_state, "latest_operation.recorded_at_source")
    recorded_path = resolve_repo_path(root, recorded) if isinstance(recorded, str) else None
    active_synthesis = active_synthesis_from_state(claim_state, reentry)
    active_synthesis_root = resolve_repo_path(root, active_synthesis) if active_synthesis else None
    latest_operation_is_active_synthesis = (
        recorded_path is not None
        and active_synthesis_root is not None
        and path_is_relative_to(recorded_path, active_synthesis_root)
    )
    expected_values = {
        "claim_state.latest_operation.next_required_action": get_path(
            claim_state, "latest_operation.next_required_action"
        ),
        "reentry.next_work.tasks[0]": first_task(reentry),
    }
    if latest_operation_is_active_synthesis and active_synthesis_root is not None:
        synthesis_queue = safe_load_structured(issues, active_synthesis_root / "synthesis_queue.yaml")
        expected_values["synthesis_queue.queue[0].next_action"] = first_synthesis_queue_next_action(
            synthesis_queue
        )
    elif not allow_no_active_campaign:
        expected_values["campaign.closeout.remaining_question"] = get_path(campaign, "closeout.remaining_question")
    if latest_run is not None and not latest_operation_is_active_synthesis:
        expected_values["gate_report.next_action"] = get_path(gate_report, "next_action")
    filled = {name: value for name, value in expected_values.items() if isinstance(value, str) and value}
    if len(set(filled.values())) > 1:
        detail = "; ".join(f"{name}={value!r}" for name, value in sorted(filled.items()))
        issues.add("next_action_mismatch", "repo-state", detail)
    missing = [name for name, value in expected_values.items() if value in (None, "", [])]
    if missing:
        issues.add(
            "next_action_missing",
            "repo-state",
            "missing next action fields: " + ", ".join(missing),
            severity="warning",
        )
    if isinstance(recorded, str) and recorded_path is not None and not recorded_path.exists():
        issues.add("latest_operation_source_missing", recorded, "latest operation source file is missing")


def check_latest_run_evidence(issues: IssueCollector, run_dir: Path) -> None:
    manifest_path = run_dir / "run_manifest.json"
    gate_path = run_dir / "gate_report.json"
    manifest = safe_load_structured(issues, manifest_path)
    gate_report = safe_load_structured(issues, gate_path)
    if not isinstance(manifest, dict) or not isinstance(gate_report, dict):
        return
    for rel_path in sorted(collect_evidence_paths(manifest, gate_report)):
        if not should_check_evidence_path(rel_path):
            continue
        target = resolve_run_evidence_path(run_dir, rel_path)
        if not target.exists():
            issues.add("evidence_path_missing", target, f"recorded evidence path is missing: {rel_path}")


def check_closed_runs(root: Path, issues: IssueCollector) -> None:
    for run_dir in iter_run_dirs(root):
        manifest = safe_load_structured(issues, run_dir / "run_manifest.json")
        gate_report = safe_load_structured(issues, run_dir / "gate_report.json")
        if not isinstance(manifest, dict) or not isinstance(gate_report, dict):
            continue
        if is_closed_run(manifest, gate_report):
            check_rolling_window_closeout_evidence(issues, run_dir, manifest, gate_report)


def check_artifact_lineage_hashes(root: Path, issues: IssueCollector) -> None:
    for lineage_path in sorted((root / "campaigns").glob("**/runs/*/artifact_lineage.json")):
        lineage = safe_load_structured(issues, lineage_path)
        if not isinstance(lineage, dict):
            continue
        records = lineage.get("artifact_records")
        if not isinstance(records, list):
            continue
        run_dir = lineage_path.parent
        for record in records:
            if not isinstance(record, dict):
                continue
            rel_path = record.get("repo_relative_path")
            expected_hash = record.get("sha256")
            artifact_id = str(record.get("artifact_id", "unknown_artifact"))
            if not isinstance(rel_path, str) or not rel_path:
                issues.add("artifact_lineage_path_missing", lineage_path, f"{artifact_id} has no repo_relative_path")
                continue
            if not isinstance(expected_hash, str) or not expected_hash:
                issues.add("artifact_lineage_hash_missing", lineage_path, f"{artifact_id} has no sha256")
                continue
            target = resolve_artifact_path(root, run_dir, rel_path)
            if not target.exists():
                issues.add("artifact_lineage_target_missing", target, f"{artifact_id} target is missing")
                continue
            actual_hash = sha256_file(target)
            if actual_hash != expected_hash:
                issues.add(
                    "artifact_lineage_hash_mismatch",
                    lineage_path,
                    f"{artifact_id} hash mismatch for {rel_path}: expected {expected_hash}, actual {actual_hash}",
                )


def check_forbidden_claims(issues: IssueCollector, path: Path | str, payload: Any, prefix: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_ACTIVE_CLAIMS and value is True:
                issues.add("forbidden_claim_true", path, f"{dotted} must remain false")
            check_forbidden_claims(issues, path, value, dotted)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            check_forbidden_claims(issues, path, item, f"{prefix}[{index}]")


def is_closed_run(manifest: dict[str, Any], gate_report: dict[str, Any]) -> bool:
    statuses = {
        manifest.get("status"),
        get_path(manifest, "closeout_review.status"),
        gate_report.get("status"),
        get_path(gate_report, "closeout_review.status"),
    }
    return bool(statuses & CLOSED_RUN_STATUSES) or gate_report.get("decision") in CLOSEOUT_DECISIONS


def iter_run_dirs(root: Path) -> list[Path]:
    campaigns = root / "campaigns"
    if not campaigns.exists():
        return []
    return sorted(path for path in campaigns.glob("*/runs/*") if path.is_dir())


def collect_evidence_paths(*payloads: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for payload in payloads:
        evidence = payload.get("evidence_paths")
        if isinstance(evidence, dict):
            paths.update(str(value) for value in evidence.values() if isinstance(value, str))
        elif isinstance(evidence, list):
            paths.update(str(value) for value in evidence if isinstance(value, str))
    return paths


def should_check_evidence_path(rel_path: str) -> bool:
    if rel_path.startswith("../"):
        return False
    return (
        rel_path == "artifact_lineage.json"
        or rel_path.startswith("kpi/")
        or rel_path.startswith("artifacts/")
    )


def resolve_run_evidence_path(run_dir: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute():
        return path
    return (run_dir / path).resolve()


def resolve_artifact_path(root: Path, run_dir: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute():
        return path
    root_candidate = (root / path).resolve()
    if root_candidate.exists() or rel_path.startswith(("campaigns/", "data/", "configs/", "registries/", "contracts/")):
        return root_candidate
    return (run_dir / path).resolve()


def resolve_repo_path(root: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def resolve_run_pointer(campaign_root: Path, pointer: str) -> Path:
    path = Path(pointer)
    if path.is_absolute():
        return path
    if pointer.startswith("campaigns/"):
        return (campaign_root.parent.parent / path).resolve()
    return (campaign_root / path).resolve()


def run_dir_from_artifact_path(root: Path, rel_path: str) -> Path | None:
    parts = Path(rel_path).parts
    if "runs" not in parts:
        return None
    index = parts.index("runs")
    if len(parts) <= index + 1:
        return None
    return (root / Path(*parts[: index + 2])).resolve()


def first_task(reentry: Any) -> str | None:
    tasks = get_path(reentry, "next_work.tasks")
    if isinstance(tasks, list) and tasks:
        return tasks[0] if isinstance(tasks[0], str) else None
    return None


def first_synthesis_queue_next_action(synthesis_queue: Any) -> str | None:
    queue = get_path(synthesis_queue, "queue")
    if isinstance(queue, list) and queue:
        first = queue[0]
        if isinstance(first, dict):
            value = first.get("next_action")
            if isinstance(value, str):
                return value
    return None


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def display_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
