"""Activate generic prospective-pair atomic scientific evidence."""

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
    "project-goal-audit-v3-prospective-pair-scientific-protocol-v1"
)
PROTOCOL_OPERATION_ID = AUTHORITY_OPERATION_ID + "-activate-protocol"
PREDECESSOR_AUTHORITY_DIGEST = (
    "ba9aec0209899be9708354c053e62ffb1e1e9a8cf81c37ff05c446f8b5ff3555"
)
AUTHORITY_PATHS = ("contracts/evidence.yaml", "contracts/science.yaml")


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor differs")
    return text.replace(old, new, 1)


def _science(text: str) -> str:
    marker = "  prospective_pair_atomic_protocol:\n"
    if marker in text:
        return text
    return _replace_once(
        text,
        """  multiplicity:
    authority: preregistered_concurrent_family_only
    global_search_history_role: context_and_duplicate_detection_only
    raw_and_adjusted_values_preserved: true
    monte_carlo_point_and_upper_preserved: true
historical_scientific_correction:
""",
        """  multiplicity:
    authority: preregistered_concurrent_family_only
    global_search_history_role: context_and_duplicate_detection_only
    raw_and_adjusted_values_preserved: true
    monte_carlo_point_and_upper_preserved: true
  prospective_pair_atomic_protocol:
    registered_closed_dispatch_required: true
    exact_two_member_family_registered_before_first_evaluation: true
    control_and_subject_executable_identities_are_immutable: true
    historical_search_count_is_context_only_never_adjustment: true
    concurrent_family_adjustment_uses_only_preregistered_members: true
    fold_windows_and_eligible_calendars_are_disjoint_and_exact: true
    trade_intent_eligible_day_and_invariance_inventories_are_complete: true
    completed_period_price_and_cost_sources_are_recomputed: true
    calculation_is_pure_from_opened_atomic_rows: true
    mechanism_specific_producer_implementation_is_preregistered: true
    summary_surface_without_atomic_trace_is_scientifically_ineligible: true
historical_scientific_correction:
""",
        label="science prospective-pair protocol",
    )


def _evidence(text: str) -> str:
    marker = "  prospective_pair_atomic_protocol:\n"
    if marker in text:
        return text
    return _replace_once(
        text,
        """  E01_multiplicity_batch_binding:
    exact_active_batch_open_required: true
    plan_registration_batch_order_set_size_and_subject_equal: true
    mission_executable_and_batch_id_bound: true
    content_addressed_derived_binding_persisted: true
    validator_registration_without_exact_batch_authority: false
historical_adjudication:
""",
        """  E01_multiplicity_batch_binding:
    exact_active_batch_open_required: true
    plan_registration_batch_order_set_size_and_subject_equal: true
    mission_executable_and_batch_id_bound: true
    content_addressed_derived_binding_persisted: true
    validator_registration_without_exact_batch_authority: false
  prospective_pair_atomic_protocol:
    protocol_definition_matches_plan_trace_and_calculation: true
    exact_family_order_control_subject_and_fold_inventory_required: true
    executed_intents_and_trade_observations_are_bijective: true
    skipped_intents_have_no_counterfactual_outcome_access: true
    decision_entry_exit_and_completed_source_clocks_are_recomputed: true
    gross_native_stress_and_net_cost_arithmetic_is_recomputed: true
    zero_invariance_mismatch_requires_equal_content_hashes: true
    selection_and_control_inference_recomputed_from_exact_daily_rows: true
    producer_callback_module_or_import_path_in_durable_payload_allowed: false
historical_adjudication:
""",
        label="evidence prospective-pair protocol",
    )


def _replacements(root: Path = ROOT) -> dict[str, bytes]:
    transforms = {
        "contracts/evidence.yaml": _evidence,
        "contracts/science.yaml": _science,
    }
    replacements: dict[str, bytes] = {}
    for relative, transform in transforms.items():
        text = transform((root / relative).read_text(encoding="ascii"))
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict) or "prospective_pair_atomic_protocol" not in text:
            raise RuntimeError(f"{relative} lacks prospective-pair authority")
        replacements[relative] = text.encode("ascii")
    return replacements


def _audit_manifest(replacements: dict[str, bytes]) -> bytes:
    return canonical_bytes(
        {
            "authority_paths": list(AUTHORITY_PATHS),
            "checkpoint_commit": "c607a23a711576417932247a4285783d0f527361",
            "new_protocol_id": "prospective_policy.concurrent_pair.v1",
            "replacement_sha256": {
                relative: sha256(content).hexdigest()
                for relative, content in sorted(replacements.items())
            },
            "schema": "prospective_pair_scientific_protocol_audit.v1",
            "scientific_claim_delta": 0,
            "scientific_trial_delta": 0,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }
    )


def plan_activation(root: Path = ROOT) -> dict[str, object]:
    replacements = _replacements(root)
    writer = StateWriter(root)
    control = writer.read_control()
    if control is None:
        raise RuntimeError("prospective-pair activation requires control")
    existing = None
    if control["authority"]["manifest_digest"] != PREDECESSOR_AUTHORITY_DIGEST:
        with writer.open_stable_index() as (_control, index):
            existing = index.get("operation", AUTHORITY_OPERATION_ID)
        if existing is None:
            raise RuntimeError("prospective-pair authority predecessor differs")
    return {
        "authority_operation_id": AUTHORITY_OPERATION_ID,
        "current_manifest_digest": control["authority"]["manifest_digest"],
        "mode": "already_applied" if existing is not None else "activate",
        "protocol_operation_id": PROTOCOL_OPERATION_ID,
        "replacement_sha256": {
            relative: sha256(content).hexdigest()
            for relative, content in sorted(replacements.items())
        },
        "schema": "prospective_pair_scientific_protocol_plan.v1",
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    replacements = _replacements(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("prospective-pair activation requires control")
    before = deepcopy(before)
    audit = writer.evidence.finalize(_audit_manifest(replacements))
    migration = writer.migrate_authority(
        replacements=replacements,
        reason=(
            "bind generic prospective-pair atomic evidence and pure v2 recalculation"
        ),
        operation_id=AUTHORITY_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    migrated = writer.read_control()
    if migrated is None:
        raise RuntimeError("prospective-pair migration lost control")
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
        raise RuntimeError("prospective-pair activation lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"prospective-pair activation changed {field}")
    return {
        "authority_event_id": migration.event_id,
        "authority_reused": migration.reused,
        "new_manifest_digest": after["authority"]["manifest_digest"],
        "protocol_event_id": activation.event_id,
        "protocol_reused": activation.reused,
        "revision": after["revision"],
        "schema": "prospective_pair_scientific_protocol_result.v1",
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    result = apply_activation(ROOT) if arguments.apply else plan_activation(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
