"""Fast V2.2 quant-governance checker; never launches evidence work."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    FailureEffect,
    MetricObservation,
    MetricRule,
    Stage,
    interpret_kpis,
)
from axiom_rift.v2.research.programs import load_program_registry
from axiom_rift.v2.research.sensitivity import build_oat_plan
from axiom_rift.v2.validation.harness import validate_v21_harness
from axiom_rift.v2.validation.receipts import validation_key
from axiom_rift.v2.validation.types import ValidationIssue, ValidationResult


YAML_SCHEMAS = {
    "contracts/v2/hypothesis_contract.yaml": "axiom_rift_v2_hypothesis_contract_v1",
    "contracts/v2/kpi_policy.yaml": "axiom_rift_v2_kpi_policy_v1",
    "contracts/v2/sensitivity_policy.yaml": "axiom_rift_v2_sensitivity_policy_v1",
    "configs/v2/sensitivity.yaml": "axiom_rift_v2_sensitivity_config_v1",
}

HASHED_INPUTS = (
    "AGENTS.md",
    "contracts/v2/agents_router_candidate.md",
    ".agents/skills/axiom-v2-goal-operator/SKILL.md",
    ".agents/skills/axiom-v2-goal-operator/agents/openai.yaml",
    "contracts/v2/research_contract.yaml",
    "contracts/v2/evaluation_contract.yaml",
    "contracts/v2/architecture.yaml",
    "contracts/v2/identity_policy.yaml",
    "contracts/v2/operator_contract.yaml",
    "contracts/v2/split_policy.yaml",
    "contracts/v2/state_machine.yaml",
    "contracts/v2/validation_contract.yaml",
    "contracts/v2/hypothesis_contract.yaml",
    "contracts/v2/kpi_policy.yaml",
    "contracts/v2/sensitivity_policy.yaml",
    "configs/v2/mission.yaml",
    "configs/v2/sensitivity.yaml",
    "configs/v2/program_registry.yaml",
    "configs/v2/validation_surfaces.yaml",
    "src/axiom_rift/v2/operations.py",
    "src/axiom_rift/v2/research/evaluation.py",
    "src/axiom_rift/v2/research/sensitivity.py",
    "src/axiom_rift/v2/research/scout.py",
    "src/axiom_rift/v2/jobs/scout.py",
    "src/axiom_rift/v2/validation/governance.py",
    "src/axiom_rift/v2/cli.py",
    "tests/v2/test_v22_kpi_evaluation.py",
    "tests/v2/test_v22_sensitivity.py",
    "tests/v2/test_v22_nested_scout.py",
    "tests/v2/test_v21_state_operations.py",
    "tests/v2/test_v21_canonical_research.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def governance_validation_identity(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_hashes = {relative: _sha256_file(root / relative) for relative in HASHED_INPUTS}
    state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
    input_hashes["registries/v2/control_state.yaml"] = sha256_payload(
        {
            "schema": state.get("schema"),
            "active_truth": state.get("active_truth"),
            "root_mission": state.get("root_mission"),
            "mission_budget": state.get("mission_budget"),
            "namespace": state.get("namespace"),
            "cursor": state.get("cursor"),
            "active_job": state.get("reentry", {}).get("active_job"),
            "claim": state.get("claim"),
            "holdout": state.get("holdout"),
        }
    )
    contract_hashes = {
        relative: _sha256_file(root / relative)
        for relative in YAML_SCHEMAS
        if relative.startswith("contracts/")
    }
    config_hashes = {
        relative: _sha256_file(root / relative)
        for relative in (
            "configs/v2/mission.yaml",
            "configs/v2/sensitivity.yaml",
            "configs/v2/program_registry.yaml",
            "configs/v2/validation_surfaces.yaml",
        )
    }
    code_hash = _sha256_file(root / "src/axiom_rift/v2/validation/governance.py")
    scope = sorted(input_hashes)
    key = validation_key(
        "axiom_rift_v2_2_quant_governance_v1",
        code_hash,
        input_hashes,
        config_hashes,
        contract_hashes,
        scope,
    )
    return {
        "validator_id": "axiom_rift_v2_2_quant_governance_v1",
        "validator_code_sha256": code_hash,
        "validation_key": key,
        "input_hashes": input_hashes,
        "config_hashes": config_hashes,
        "contract_hashes": contract_hashes,
        "scope": scope,
    }


def validate_v22_quant_governance(root: Path) -> tuple[ValidationResult, dict[str, Any]]:
    started = time.perf_counter()
    root = root.resolve()
    issues: list[ValidationIssue] = []

    def issue(code: str, path: str, detail: str) -> None:
        issues.append(ValidationIssue(code, path, detail))

    base, _base_receipt = validate_v21_harness(root)
    for row in base.issues:
        issues.append(row)
    for relative, expected_schema in YAML_SCHEMAS.items():
        try:
            payload = yaml.safe_load((root / relative).read_text(encoding="ascii"))
            if not isinstance(payload, dict) or payload.get("schema") != expected_schema:
                issue("schema_mismatch", relative, f"expected {expected_schema}")
        except Exception as exc:
            issue("invalid_ascii_yaml", relative, str(exc))
    try:
        if (root / "AGENTS.md").read_text(encoding="ascii") != (
            root / "contracts/v2/agents_router_candidate.md"
        ).read_text(encoding="ascii"):
            issue("router_mismatch", "AGENTS.md", "active and candidate routers differ")
    except Exception as exc:
        issue("invalid_router", "AGENTS.md", str(exc))
    try:
        mission = yaml.safe_load((root / "configs/v2/mission.yaml").read_text(encoding="ascii"))
        bounded = mission.get("bounded_parameter_discovery", {})
        expected = {
            "unregistered_adjacent_retries_max": 0,
            "sensitivity_batches_per_hypothesis_max": 1,
            "knobs_per_hypothesis_max": 2,
            "base_and_extreme_variants_max": 5,
            "local_calibration_rounds_max": 1,
            "local_calibration_new_evaluations_per_outer_fold_max": 1,
            "local_candidate_set_including_bracket_max": 3,
            "automatic_range_extension_max": 0,
            "development_extreme_variants_max": 0,
        }
        if bounded != expected:
            issue("bounded_parameter_policy", "configs/v2/mission.yaml", "bounded limits differ")
    except Exception as exc:
        issue("invalid_mission_policy", "configs/v2/mission.yaml", str(exc))
    try:
        plan = build_oat_plan(
            hypothesis_id="V2H9999",
            stage="S",
            baseline_parameters={"model": {"alpha": 1.0}, "calibration": {"quantile": 0.5}},
            nested_policy={
                "model": {
                    "alpha": {"type": "float", "low": 0.1, "baseline": 1.0, "high": 10.0}
                }
            },
            data_role="validation_oos",
        )
        if len(plan.variants) != 3 or plan.development_variant_selection_allowed:
            issue("sensitivity_bounds", "src/axiom_rift/v2/research/sensitivity.py", "invalid OAT plan")
    except Exception as exc:
        issue("invalid_sensitivity_engine", "src/axiom_rift/v2/research/sensitivity.py", str(exc))
    try:
        profile = EvaluationProfile(
            profile_id="V2KPI_VALIDATOR",
            rules=(
                MetricRule.minimum(
                    "density",
                    "activity",
                    stages=(Stage.S,),
                    pass_at=5.0,
                    failure_effect=FailureEffect.DIAGNOSTIC,
                ),
                MetricRule.minimum(
                    "economics",
                    "economics",
                    stages=(Stage.S,),
                    pass_at=0.0,
                ),
            ),
        )
        diagnostic = interpret_kpis(Stage.S, {"density": 0.0, "economics": 1.0}, profile)
        censored = interpret_kpis(
            Stage.S,
            {"density": 5.0, "economics": MetricObservation.censored("no_loss")},
            profile,
        )
        if diagnostic.route != "route_to_R" or censored.route != "scout_rejected":
            issue("kpi_routing", "src/axiom_rift/v2/research/evaluation.py", "route semantics differ")
    except Exception as exc:
        issue("invalid_kpi_engine", "src/axiom_rift/v2/research/evaluation.py", str(exc))
    try:
        load_program_registry(root)
    except Exception as exc:
        issue("program_registry", "configs/v2/program_registry.yaml", str(exc))
    try:
        scout = (root / "src/axiom_rift/v2/research/scout.py").read_text(encoding="ascii")
        skill = (root / ".agents/skills/axiom-v2-goal-operator/SKILL.md").read_text(
            encoding="ascii"
        )
        for token in ("validation_oos", "development_cv", "trial_accounting"):
            if token not in scout:
                issue("nested_scout_boundary", "src/axiom_rift/v2/research/scout.py", token)
        for token in ("KPI and Parameter Governance", "non-compensatory", "local calibration"):
            if token not in skill:
                issue("operator_skill_boundary", ".agents/skills/axiom-v2-goal-operator/SKILL.md", token)
    except Exception as exc:
        issue("invalid_governance_source", "src/axiom_rift/v2", str(exc))
    duration = time.perf_counter() - started
    if duration > 30.0:
        issue("duration", "configs/v2/validation.yaml", f"validator took {duration:.6f}s")
    result = ValidationResult("v2-2-quant-governance", tuple(issues))
    receipt = {
        "schema": "axiom_rift_v2_2_quant_governance_validation_receipt_v1",
        **governance_validation_identity(root),
        "duration_seconds": duration,
        "outcome": "pass" if result.ok else "fail",
        "issues": [row.to_dict() for row in result.issues],
        "evidence_jobs_launched": False,
        "hard_ceiling_seconds": 30,
        "claim_ceiling": "none",
    }
    return result, receipt


__all__ = [
    "governance_validation_identity",
    "validate_v22_quant_governance",
]
