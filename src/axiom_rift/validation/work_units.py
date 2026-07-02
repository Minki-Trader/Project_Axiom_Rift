"""Validate Axiom campaign and synthesis work-unit files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axiom_rift.paths import PROJECT_ROOT

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in missing optional dependency environments
    yaml = None


CAMPAIGN_FOLDER_RE = re.compile(r"^(C\d{4})_([a-z0-9][a-z0-9_]*[a-z0-9])$")
SYNTHESIS_FOLDER_RE = re.compile(r"^(SC\d{4})_([a-z0-9][a-z0-9_]*[a-z0-9])$")
RUN_FOLDER_RE = re.compile(r"^R\d{4}$")
SYNTHESIS_RUN_FOLDER_RE = re.compile(r"^SR\d{4}$")

TEMPLATE_SENTINELS = {
    "C0000",
    "SC0000",
    "R0000",
    "SR0000",
    "PX0000",
    "MT50000",
    "P0000",
    "G0000",
    "L0000",
    "A0000",
    "placeholder",
}

FALSE_CLAIM_KEYS = {
    "claim_authority",
    "selected",
    "label_selected",
    "feature_set_selected",
    "model_selected",
    "trade_logic_selected",
    "runtime_probe_completed",
    "economics_pass",
    "materialization_ready",
    "runtime_authority",
    "onnx_ready",
    "promotion_ready",
    "live_ready",
}

CAMPAIGN_REQUIRED_FILES = ("campaign.yaml", "inputs.yaml", "selected.yaml")
SYNTHESIS_REQUIRED_FILES = ("synthesis.yaml", "ingredient_refs.yaml", "synthesis_queue.yaml", "selected.yaml")
RUN_REQUIRED_FILES = (
    "run_manifest.json",
    "gate_report.json",
    "artifact_lineage.json",
    "kpi/proxy.json",
    "kpi/mt5_logic_parity.json",
    "kpi/mt5_tick.json",
    "kpi/proxy_vs_mt5_logic_parity.json",
    "kpi/execution_divergence.json",
)
OPTIONAL_RUN_KPI_FILES = (
    "kpi/mt5_tick_by_fold.json",
    "kpi/execution_divergence_by_fold.json",
)
ROLLING_WINDOW_CLOSEOUT_REQUIRED_FILES = (
    "kpi/mt5_tick_by_fold.json",
    "kpi/execution_divergence_by_fold.json",
)
CLOSEOUT_DECISIONS = {"close_no_candidate", "close_with_candidate_evidence", "close_non_portable"}
CLOSED_RUN_STATUSES = {"closed_no_candidate", "closed_with_candidate_evidence", "closed_non_portable"}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ValidationResult:
    target: str
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "target": self.target,
            "error_count": sum(1 for issue in self.issues if issue.severity == "error"),
            "warning_count": sum(1 for issue in self.issues if issue.severity == "warning"),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class IssueCollector:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.issues: list[ValidationIssue] = []

    def add(self, code: str, path: Path | str, detail: str, severity: str = "error") -> None:
        self.issues.append(ValidationIssue(severity, code, self.display_path(path), detail))

    def display_path(self, path: Path | str) -> str:
        if isinstance(path, str):
            return path
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def result_json(result: ValidationResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def validate_templates(root: Path = PROJECT_ROOT) -> ValidationResult:
    root = root.resolve()
    issues = IssueCollector(root)
    template_root = root / "campaigns" / "_templates"
    template_files = all_template_files(root, issues)
    check_required_files(issues, template_files)
    check_structured_files(issues, [root / item for item in template_files])
    check_templates_have_template_marker(issues, template_root)
    check_template_contract_alignment(issues, root)
    check_template_claim_boundaries(issues, template_root)
    check_mandatory_mt5_policy(issues, root)
    return ValidationResult("templates", tuple(issues.issues))


def validate_work_unit(path: Path, root: Path = PROJECT_ROOT) -> ValidationResult:
    root = root.resolve()
    target = path if path.is_absolute() else root / path
    target = target.resolve()
    issues = IssueCollector(root)
    if not target.exists():
        issues.add("missing_work_unit", target, "work-unit path does not exist")
        return ValidationResult(issues.display_path(target), tuple(issues.issues))
    if not target.is_dir():
        issues.add("invalid_work_unit_path", target, "work-unit path must be a directory")
        return ValidationResult(issues.display_path(target), tuple(issues.issues))

    kind, work_unit_id, slug = detect_work_unit(target)
    if kind is None or work_unit_id is None:
        issues.add(
            "invalid_work_unit_folder",
            target,
            "folder name must match C0001_short_slug or SC0001_short_slug",
        )
        return ValidationResult(issues.display_path(target), tuple(issues.issues))

    ensure_under_campaigns(issues, root, target)
    check_no_forbidden_data_dirs(issues, target)
    if kind == "campaign":
        validate_campaign_root(issues, target, work_unit_id, slug or "")
        run_id_pattern = RUN_FOLDER_RE
        parent_type = "campaign"
    else:
        validate_synthesis_root(issues, target, work_unit_id, slug or "")
        run_id_pattern = SYNTHESIS_RUN_FOLDER_RE
        parent_type = "synthesis"
    validate_runs(issues, target, work_unit_id, parent_type, run_id_pattern)
    check_no_template_sentinels(issues, target)
    return ValidationResult(issues.display_path(target), tuple(issues.issues))


def all_template_files(root: Path, issues: IssueCollector) -> tuple[str, ...]:
    registry = safe_load_structured(issues, root / "registries" / "template_registry.yaml")
    if not isinstance(registry, dict):
        return ()
    paths: list[str] = []
    for template_set in registry.get("template_sets", {}).values():
        for entry in template_set.get("required_templates", []):
            template_path = entry.get("path")
            if isinstance(template_path, str):
                paths.append(template_path)
    return tuple(dict.fromkeys(paths))


def check_required_files(issues: IssueCollector, rel_paths: tuple[str, ...]) -> None:
    for rel_path in rel_paths:
        path = issues.root / rel_path
        if not path.exists():
            issues.add("missing_required_file", path, "required template file is missing")
            continue
        if not path.is_file():
            issues.add("invalid_required_file", path, "required template path is not a file")


def check_structured_files(issues: IssueCollector, paths: list[Path]) -> None:
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        if not is_ascii(path):
            issues.add("non_ascii_file", path, "active template file must be ASCII-only")
        try:
            load_structured(path, issues.root)
        except Exception as exc:  # noqa: BLE001 - report parser errors without crashing validation
            issues.add("parse_error", path, str(exc))


def check_templates_have_template_marker(issues: IssueCollector, template_root: Path) -> None:
    for path in sorted(template_root.rglob("*")):
        if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        data = safe_load_structured(issues, path)
        if isinstance(data, dict) and data.get("template") is not True:
            issues.add("template_marker_missing", path, "template file must declare template: true")


def check_template_contract_alignment(issues: IssueCollector, root: Path) -> None:
    lifecycle = safe_load_structured(issues, root / "contracts" / "campaign_lifecycle.yaml")
    if not isinstance(lifecycle, dict):
        return
    required_fields = lifecycle.get("required_fields", {})
    mapping = {
        "campaign": root / "campaigns" / "_templates" / "campaign.yaml",
        "synthesis": root / "campaigns" / "_templates" / "synthesis.yaml",
        "run": root / "campaigns" / "_templates" / "run_manifest.json",
        "synthesis_run": root / "campaigns" / "_templates" / "run_manifest.json",
        "gate_report": root / "campaigns" / "_templates" / "gate_report.json",
    }
    for section, template_path in mapping.items():
        data = safe_load_structured(issues, template_path)
        if not isinstance(data, dict):
            continue
        for field in required_fields.get(section, []):
            if not has_path(data, field):
                issues.add(
                    "required_field_missing_from_template",
                    template_path,
                    f"{section} requires {field}",
                )

    artifact_contract = safe_load_structured(issues, root / "contracts" / "artifact_lineage.yaml")
    artifact_template = safe_load_structured(issues, root / "campaigns" / "_templates" / "artifact_lineage.json")
    if isinstance(artifact_contract, dict) and isinstance(artifact_template, dict):
        required = artifact_contract.get("required_fields", {})
        for field in required.get("lineage", []):
            if not has_path(artifact_template, field):
                issues.add("required_field_missing_from_template", "artifact_lineage", f"lineage requires {field}")
        for field in required.get("artifact_records_item", []):
            if not has_path(artifact_template, f"artifact_records[].{field}"):
                issues.add(
                    "required_field_missing_from_template",
                    "artifact_lineage",
                    f"artifact_records item requires {field}",
                )


def check_template_claim_boundaries(issues: IssueCollector, template_root: Path) -> None:
    for path in sorted(template_root.rglob("*")):
        if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        data = safe_load_structured(issues, path)
        if isinstance(data, dict):
            check_claim_false_values(issues, path, data)


def check_mandatory_mt5_policy(issues: IssueCollector, root: Path) -> None:
    lifecycle = safe_load_structured(issues, root / "contracts" / "campaign_lifecycle.yaml")
    if not isinstance(lifecycle, dict):
        return
    run_policy = lifecycle.get("run_policy", {})
    expected = {
        "full_period_mt5_kpi_is_diagnostic_only_for_closeout": True,
        "opened_run_commits_to_mt5_validation": True,
        "proxy_kpi_is_not_screening_gate_for_mt5": True,
        "proxy_result_may_stop_mt5_validation": False,
        "proxy_only_scout_allowed": False,
        "proxy_requires_matching_mt5_probe": True,
        "run_closeout_requires_rolling_window_fold_isolated_mt5_tick": True,
        "run_completion_requires_explicit_mt5_evidence": True,
        "run_may_close_without_mt5_pair": False,
        "weak_proxy_result_may_skip_mt5_probe": False,
    }
    for key, value in expected.items():
        if run_policy.get(key) is not value:
            issues.add("mandatory_mt5_policy_mismatch", "contracts/campaign_lifecycle.yaml", f"{key} must be {value}")
    for rel_path in RUN_REQUIRED_FILES:
        path = root / "campaigns" / "_templates" / rel_path
        if not path.exists():
            issues.add("run_template_missing_explicit_kpi_file", path, "run template must include explicit KPI files")


def validate_campaign_root(issues: IssueCollector, target: Path, campaign_id: str, slug: str) -> None:
    require_child_files(issues, target, CAMPAIGN_REQUIRED_FILES)
    campaign = safe_load_structured(issues, target / "campaign.yaml")
    inputs = safe_load_structured(issues, target / "inputs.yaml")
    selected = safe_load_structured(issues, target / "selected.yaml")
    if isinstance(campaign, dict):
        require_actual_file(issues, target / "campaign.yaml", campaign)
        require_equal(issues, target / "campaign.yaml", campaign.get("campaign_id"), campaign_id, "campaign_id")
        require_equal(issues, target / "campaign.yaml", campaign.get("campaign_slug"), slug, "campaign_slug")
        require_non_empty_path(issues, target / "campaign.yaml", campaign, "opened_at_utc")
        require_non_empty_path(issues, target / "campaign.yaml", campaign, "hypothesis.summary")
        require_non_empty_path(issues, target / "campaign.yaml", campaign, "hypothesis.boundary")
        check_claim_false_values(issues, target / "campaign.yaml", campaign)
    if isinstance(inputs, dict):
        require_actual_file(issues, target / "inputs.yaml", inputs)
        require_equal(issues, target / "inputs.yaml", inputs.get("work_unit_id"), campaign_id, "work_unit_id")
        check_claim_false_values(issues, target / "inputs.yaml", inputs)
    if isinstance(selected, dict):
        require_actual_file(issues, target / "selected.yaml", selected)
        check_claim_false_values(issues, target / "selected.yaml", selected)


def validate_synthesis_root(issues: IssueCollector, target: Path, synthesis_id: str, slug: str) -> None:
    require_child_files(issues, target, SYNTHESIS_REQUIRED_FILES)
    synthesis = safe_load_structured(issues, target / "synthesis.yaml")
    ingredient_refs = safe_load_structured(issues, target / "ingredient_refs.yaml")
    synthesis_queue = safe_load_structured(issues, target / "synthesis_queue.yaml")
    selected = safe_load_structured(issues, target / "selected.yaml")
    if isinstance(synthesis, dict):
        require_actual_file(issues, target / "synthesis.yaml", synthesis)
        require_equal(issues, target / "synthesis.yaml", synthesis.get("synthesis_id"), synthesis_id, "synthesis_id")
        require_equal(issues, target / "synthesis.yaml", synthesis.get("synthesis_slug"), slug, "synthesis_slug")
        require_non_empty_path(issues, target / "synthesis.yaml", synthesis, "opened_at_utc")
        require_non_empty_path(issues, target / "synthesis.yaml", synthesis, "synthesis_question.summary")
        require_non_empty_path(issues, target / "synthesis.yaml", synthesis, "synthesis_question.boundary")
        check_claim_false_values(issues, target / "synthesis.yaml", synthesis)
    for rel_path, data in (
        ("ingredient_refs.yaml", ingredient_refs),
        ("synthesis_queue.yaml", synthesis_queue),
        ("selected.yaml", selected),
    ):
        if isinstance(data, dict):
            require_actual_file(issues, target / rel_path, data)
            check_claim_false_values(issues, target / rel_path, data)


def validate_runs(
    issues: IssueCollector,
    work_unit: Path,
    work_unit_id: str,
    parent_type: str,
    run_pattern: re.Pattern[str],
) -> None:
    runs_root = work_unit / "runs"
    if not runs_root.exists():
        return
    if not runs_root.is_dir():
        issues.add("invalid_runs_path", runs_root, "runs path must be a directory")
        return
    for run_dir in sorted(item for item in runs_root.iterdir() if item.is_dir()):
        if not run_pattern.match(run_dir.name):
            issues.add("invalid_run_folder", run_dir, f"run folder does not match {run_pattern.pattern}")
            continue
        validate_run_folder(issues, run_dir, work_unit_id, parent_type, run_dir.name)


def validate_run_folder(
    issues: IssueCollector,
    run_dir: Path,
    work_unit_id: str,
    parent_type: str,
    run_id: str,
) -> None:
    require_child_files(issues, run_dir, RUN_REQUIRED_FILES)
    run_manifest = safe_load_structured(issues, run_dir / "run_manifest.json")
    gate_report = safe_load_structured(issues, run_dir / "gate_report.json")
    if isinstance(run_manifest, dict):
        require_actual_file(issues, run_dir / "run_manifest.json", run_manifest)
        require_equal(issues, run_dir / "run_manifest.json", run_manifest.get("work_unit_id"), work_unit_id, "work_unit_id")
        require_equal(issues, run_dir / "run_manifest.json", run_manifest.get("parent_type"), parent_type, "parent_type")
        require_equal(issues, run_dir / "run_manifest.json", run_manifest.get("run_id"), run_id, "run_id")
        require_non_empty_path(issues, run_dir / "run_manifest.json", run_manifest, "hypothesis_variant.summary")
        require_non_empty_path(issues, run_dir / "run_manifest.json", run_manifest, "hypothesis_variant.variant_boundary")
        for surface in ("model", "feature", "trade_logic", "label"):
            require_non_empty_path(issues, run_dir / "run_manifest.json", run_manifest, f"surfaces.{surface}.summary")
        check_claim_false_values(issues, run_dir / "run_manifest.json", run_manifest)

    for rel_path in RUN_REQUIRED_FILES:
        path = run_dir / rel_path
        if rel_path == "run_manifest.json":
            data = run_manifest
        elif rel_path == "gate_report.json":
            data = gate_report
        else:
            data = safe_load_structured(issues, path)
        if isinstance(data, dict):
            require_actual_file(issues, path, data)
            check_claim_false_values(issues, path, data)
            if "work_unit_id" in data:
                require_equal(issues, path, data.get("work_unit_id"), work_unit_id, "work_unit_id")
            if "run_id" in data:
                require_equal(issues, path, data.get("run_id"), run_id, "run_id")
    for rel_path in OPTIONAL_RUN_KPI_FILES:
        path = run_dir / rel_path
        if not path.exists():
            continue
        data = safe_load_structured(issues, path)
        if isinstance(data, dict):
            require_actual_file(issues, path, data)
            check_claim_false_values(issues, path, data)
            if "work_unit_id" in data:
                require_equal(issues, path, data.get("work_unit_id"), work_unit_id, "work_unit_id")
            if "run_id" in data:
                require_equal(issues, path, data.get("run_id"), run_id, "run_id")
    if isinstance(run_manifest, dict) and isinstance(gate_report, dict):
        check_rolling_window_closeout_evidence(issues, run_dir, run_manifest, gate_report)


def check_rolling_window_closeout_evidence(
    issues: IssueCollector,
    run_dir: Path,
    run_manifest: dict[str, Any],
    gate_report: dict[str, Any],
) -> None:
    decision = gate_report.get("decision")
    status = run_manifest.get("status")
    if decision not in CLOSEOUT_DECISIONS and status not in CLOSED_RUN_STATUSES:
        return

    exception = get_path(gate_report, "rolling_window_closeout_gate.fold_isolated_exception", default={})
    if isinstance(exception, dict) and exception.get("applies") is True:
        missing_exception_fields = [
            field
            for field in ("reason", "blocking_condition", "revisit_when")
            if exception.get(field) in (None, "", [], {})
        ]
        if missing_exception_fields:
            issues.add(
                "rolling_window_closeout_exception_incomplete",
                run_dir / "gate_report.json",
                "fold-isolated closeout exception is missing: " + ", ".join(missing_exception_fields),
            )
        return

    missing_files = [rel_path for rel_path in ROLLING_WINDOW_CLOSEOUT_REQUIRED_FILES if not (run_dir / rel_path).exists()]
    if missing_files:
        issues.add(
            "rolling_window_closeout_evidence_missing",
            run_dir / "gate_report.json",
            "closeout requires fold-isolated MT5 tick evidence or a complete exception; missing "
            + ", ".join(missing_files),
        )
        return

    evidence_paths = collect_evidence_paths(run_manifest, gate_report)
    missing_records = [rel_path for rel_path in ROLLING_WINDOW_CLOSEOUT_REQUIRED_FILES if rel_path not in evidence_paths]
    if missing_records:
        issues.add(
            "rolling_window_closeout_path_not_recorded",
            run_dir / "gate_report.json",
            "fold-isolated closeout evidence exists but is not recorded in evidence paths: "
            + ", ".join(missing_records),
        )


def collect_evidence_paths(*payloads: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for payload in payloads:
        evidence = payload.get("evidence_paths")
        if isinstance(evidence, dict):
            paths.update(str(value) for value in evidence.values() if isinstance(value, str))
        elif isinstance(evidence, list):
            paths.update(str(value) for value in evidence if isinstance(value, str))
    return paths


def require_child_files(issues: IssueCollector, base: Path, rel_paths: tuple[str, ...]) -> None:
    for rel_path in rel_paths:
        path = base / rel_path
        if not path.exists():
            issues.add("missing_required_file", path, f"required file {rel_path} is missing")
        elif not path.is_file():
            issues.add("invalid_required_file", path, f"required file {rel_path} is not a file")
        elif not is_ascii(path):
            issues.add("non_ascii_file", path, "active work-unit file must be ASCII-only")
        elif path.suffix.lower() in {".json", ".yaml", ".yml"}:
            try:
                load_structured(path, issues.root)
            except Exception as exc:  # noqa: BLE001
                issues.add("parse_error", path, str(exc))


def detect_work_unit(path: Path) -> tuple[str | None, str | None, str | None]:
    campaign_match = CAMPAIGN_FOLDER_RE.match(path.name)
    if campaign_match:
        return "campaign", campaign_match.group(1), campaign_match.group(2)
    synthesis_match = SYNTHESIS_FOLDER_RE.match(path.name)
    if synthesis_match:
        return "synthesis", synthesis_match.group(1), synthesis_match.group(2)
    return None, None, None


def ensure_under_campaigns(issues: IssueCollector, root: Path, target: Path) -> None:
    try:
        rel = target.relative_to(root / "campaigns")
    except ValueError:
        issues.add("work_unit_outside_campaigns", target, "work unit must live under campaigns/")
        return
    if len(rel.parts) != 1:
        issues.add("nested_work_unit", target, "C and SC work units must be direct children of campaigns/")


def check_no_forbidden_data_dirs(issues: IssueCollector, target: Path) -> None:
    for item in target.rglob("*"):
        lowered = {part.lower() for part in item.relative_to(target).parts}
        if {"data", "raw"} <= lowered or {"data", "processed"} <= lowered:
            issues.add("forbidden_data_path", item, "raw or processed data must not be placed in campaign folders")
        if "raw" in lowered and item.is_dir():
            issues.add("forbidden_raw_dir", item, "raw data directories are not allowed inside work units")
        if "processed" in lowered and item.is_dir():
            issues.add("forbidden_processed_dir", item, "processed data directories are not allowed inside work units")


def check_no_template_sentinels(issues: IssueCollector, target: Path) -> None:
    for path in sorted(item for item in target.rglob("*") if item.is_file()):
        if path.suffix.lower() not in {".json", ".yaml", ".yml", ".csv", ".txt", ".md"}:
            continue
        try:
            text = path.read_text(encoding="ascii")
        except UnicodeDecodeError:
            issues.add("non_ascii_file", path, "active work-unit file must be ASCII-only")
            continue
        for sentinel in TEMPLATE_SENTINELS:
            if sentinel in text:
                issues.add("template_sentinel_left", path, f"template sentinel remains: {sentinel}")


def check_claim_false_values(issues: IssueCollector, path: Path | str, data: Any, prefix: str = "") -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            if key in FALSE_CLAIM_KEYS and value is not False:
                issues.add("claim_boundary_not_false", path, f"{dotted} must be false")
            if key.endswith("_selected") and value is True:
                issues.add("selection_claim_true", path, f"{dotted} must not be true")
            check_claim_false_values(issues, path, value, dotted)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            check_claim_false_values(issues, path, item, f"{prefix}[{index}]")


def require_actual_file(issues: IssueCollector, path: Path, data: dict[str, Any]) -> None:
    if data.get("template") is True:
        issues.add("template_marker_left", path, "actual work-unit files must not keep template: true")


def require_equal(issues: IssueCollector, path: Path, observed: Any, expected: Any, field: str) -> None:
    if observed != expected:
        issues.add("field_value_mismatch", path, f"{field} must be {expected!r}, observed {observed!r}")


def require_non_empty_path(issues: IssueCollector, path: Path, data: dict[str, Any], dotted_path: str) -> None:
    value = get_path(data, dotted_path)
    if value in (None, "", [], {}):
        issues.add("required_field_unfilled", path, f"{dotted_path} must be filled")


def safe_load_structured(issues: IssueCollector, path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return load_structured(path, issues.root)
    except Exception as exc:  # noqa: BLE001
        issues.add("parse_error", path, str(exc))
        return None


def load_structured(path: Path, root: Path) -> Any:
    if not is_ascii(path):
        raise ValueError("file is not ASCII-only")
    suffix = path.suffix.lower()
    text = path.read_text(encoding="ascii")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to parse YAML files")
        return yaml.safe_load(text)
    raise ValueError(f"unsupported structured file extension under {root}: {path.suffix}")


def is_ascii(path: Path) -> bool:
    try:
        path.read_bytes().decode("ascii")
        return True
    except UnicodeDecodeError:
        return False


def has_path(data: Any, dotted_path: str) -> bool:
    sentinel = object()
    return get_path(data, dotted_path, default=sentinel) is not sentinel


def get_path(data: Any, dotted_path: str, default: Any = None) -> Any:
    current = data
    for part in dotted_path.split("."):
        if part.endswith("[]"):
            key = part[:-2]
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
            if not isinstance(current, list) or not current:
                return default
            current = current[0]
            continue
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
