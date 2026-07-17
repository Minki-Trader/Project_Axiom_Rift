"""Activate the Study-scoped scientific-change successor contract."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.operations.study_close_git import (  # noqa: E402
    require_study_close_guard_ready,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry  # noqa: E402
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.protocol import (  # noqa: E402
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


AUTHORITY_OPERATION_ID = (
    "project-goal-audit-v3-scientific-change-successor-authority-v1"
)
PROTOCOL_OPERATION_ID = AUTHORITY_OPERATION_ID + "-activate-protocol"
PREDECESSOR_AUTHORITY_DIGEST = (
    "16ed8e45375b6a9d8bdea6163778282cbc2506a7c79f5ad33ef137679091ba4d"
)
AUTHORITY_PATHS = (
    "contracts/operations.yaml",
    "contracts/science.yaml",
)
REQUIRED_MARKERS = {
    "contracts/operations.yaml": (
        "  study_scientific_change_return:\n",
        "    selected_family_returns_in_progress_to_pending_atomically: true\n",
        "    feasibility_change_uses_pre_outcome_train_only_availability_counts: true\n",
    ),
    "contracts/science.yaml": (
        "    study_scoped_scientific_change:\n",
        "      same_protocol_repair_is_forbidden: true\n",
        "      scientific_outcome_values_may_select_feasibility_parameters: false\n",
    ),
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor differs")
    return text.replace(old, new, 1)


def _operations_contract(text: str) -> str:
    marker = "  study_scientific_change_return:\n"
    if marker in text:
        return text
    return _replace_once(
        text,
        """  mixed_member_disposition:
    single_writer_event: historical_replay_obligations_disposed
    satisfactions_and_deferrals_are_disjoint_and_cover_exact_diagnosed_action: true
    valid_completed_members_are_not_discarded_by_later_engineering_failure: true
    next_action_advances_once_atomically: true
  replacement_required_terminal:
""",
        """  mixed_member_disposition:
    single_writer_event: historical_replay_obligations_disposed
    satisfactions_and_deferrals_are_disjoint_and_cover_exact_diagnosed_action: true
    valid_completed_members_are_not_discarded_by_later_engineering_failure: true
    next_action_advances_once_atomically: true
  study_scientific_change_return:
    single_writer_event: historical_replay_obligations_returned_for_scientific_change
    exact_study_scoped_requires_scientific_change_disposition_required: true
    same_protocol_repair_or_retry_allowed: false
    selected_family_returns_in_progress_to_pending_atomically: true
    every_return_head_binds_trial_study_close_diagnosis_completion_and_disposition: true
    successor_protocol_revision_binds_current_typed_return_authority: true
    successor_study_uses_distinct_executables_and_no_predecessor_evidence: true
    feasibility_change_uses_pre_outcome_train_only_availability_counts: true
    scientific_trial_claim_failure_satisfaction_candidate_holdout_and_terminal_delta: 0
    unrelated_pending_forest_and_scheduler_priority_preserved: true
  replacement_required_terminal:
""",
        label="operations scientific-change contract",
    )


def _science_contract(text: str) -> str:
    if "    study_scoped_scientific_change:\n" in text:
        return text
    text = _replace_once(
        text,
        """    - recombine
    - synthesize
batch:
""",
        """    - recombine
    - synthesize
    - revise_protocol
batch:
""",
        label="science protocol revision action",
    )
    return _replace_once(
        text,
        """    partial_family_engineering_failure_preserves_valid_member_science: true
    unresolved_selected_members_are_deferred_individually: true
    defer_requires_typed_exact_resume_condition: true
    satisfied_authority_reaudit:
""",
        """    partial_family_engineering_failure_preserves_valid_member_science: true
    unresolved_selected_members_are_deferred_individually: true
    defer_requires_typed_exact_resume_condition: true
    study_scoped_scientific_change:
      engineering_unavailability_is_not_scientific_failure: true
      exact_selected_family_returns_to_pending_without_credit: true
      same_protocol_repair_is_forbidden: true
      same_question_successor_requires_typed_continuation_lineage: true
      successor_study_and_executable_identities_are_distinct: true
      predecessor_trial_evidence_claim_kpi_and_negative_memory_inheritance: false
      feasibility_parameters_may_use_train_only_availability_counts: true
      scientific_outcome_values_may_select_feasibility_parameters: false
      corrected_protocol_is_preregistered_before_successor_outcomes: true
    satisfied_authority_reaudit:
""",
        label="science scientific-change contract",
    )


def _replacements(root: Path = ROOT) -> dict[str, bytes]:
    transforms = {
        "contracts/operations.yaml": _operations_contract,
        "contracts/science.yaml": _science_contract,
    }
    replacements: dict[str, bytes] = {}
    for relative, transform in transforms.items():
        current = (root / relative).read_bytes()
        text = transform(current.decode("ascii"))
        content = text.encode("ascii")
        if any(marker not in text for marker in REQUIRED_MARKERS[relative]):
            raise RuntimeError(f"{relative} lacks scientific-change authority")
        value = yaml.safe_load(text)
        if not isinstance(value, dict):
            raise RuntimeError(f"{relative} is not an authority mapping")
        replacements[relative] = content
    return replacements


def _audit_manifest(replacements: dict[str, bytes]) -> bytes:
    return canonical_bytes(
        {
            "authority_paths": list(AUTHORITY_PATHS),
            "diagnosis_id": (
                "diagnosis:81d551801014e8b3a3278cefb9bab929195e61c687d20b85a4a87c9d9e3f53e6"
            ),
            "engineering_completion_record_id": (
                "c5454ebb8fb2e66949d7116ca72a206c3908e336d75d18a23f5480b4574ea697"
            ),
            "replacement_sha256": {
                relative: sha256(content).hexdigest()
                for relative, content in sorted(replacements.items())
            },
            "return_event_id": (
                "44de5e2bd3e1a7b3877d6cc7edd7fe24dc3077383e2b4a7bdc7ddb1eeb1d53a7"
            ),
            "schema": "scientific_change_successor_authority_audit.v1",
            "scientific_claim_delta": 0,
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
        }
    )


def plan_activation(root: Path = ROOT) -> dict[str, object]:
    replacements = _replacements(root)
    writer = StateWriter(root)
    control = writer.read_control()
    if control is None:
        raise RuntimeError("scientific-change authority requires control")
    current_digest = control["authority"]["manifest_digest"]
    existing = None
    if current_digest != PREDECESSOR_AUTHORITY_DIGEST:
        with writer.open_stable_index() as (_control, index):
            existing = index.get("operation", AUTHORITY_OPERATION_ID)
        if existing is None:
            raise RuntimeError("scientific-change authority predecessor differs")
    return {
        "authority_operation_id": AUTHORITY_OPERATION_ID,
        "current_manifest_digest": current_digest,
        "mode": "already_applied" if existing is not None else "activate",
        "protocol_operation_id": PROTOCOL_OPERATION_ID,
        "replacement_sha256": {
            relative: sha256(content).hexdigest()
            for relative, content in sorted(replacements.items())
        },
        "schema": "scientific_change_successor_authority_plan.v1",
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    replacements = _replacements(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("scientific-change authority requires control")
    before = deepcopy(before)
    audit = writer.evidence.finalize(_audit_manifest(replacements))
    migration = writer.migrate_authority(
        replacements=replacements,
        reason=(
            "bind Study-scoped scientific-change return and distinct successor work"
        ),
        operation_id=AUTHORITY_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    migrated = writer.read_control()
    if migrated is None:
        raise RuntimeError("scientific-change migration lost control")
    activation = writer.activate_research_protocol(
        activation=ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            authority_manifest_digest=migrated["authority"]["manifest_digest"],
            audit_artifact_hash=audit.sha256,
        ),
        operation_id=PROTOCOL_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    after = writer.read_control()
    if after is None:
        raise RuntimeError("scientific-change protocol activation lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"scientific-change activation changed {field}")
    return {
        "authority_event_id": migration.event_id,
        "authority_reused": migration.reused,
        "new_manifest_digest": after["authority"]["manifest_digest"],
        "protocol_event_id": activation.event_id,
        "protocol_reused": activation.reused,
        "revision": after["revision"],
        "schema": "scientific_change_successor_authority_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    result = apply_activation(ROOT) if arguments.apply else plan_activation(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
