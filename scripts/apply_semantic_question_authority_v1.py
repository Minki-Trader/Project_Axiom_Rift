#!/usr/bin/env python3
"""Activate semantic-question authority without publishing a drifted graph."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Callable

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
    "project-goal-audit-v2-semantic-question-authority-v1"
)
PROTOCOL_OPERATION_ID = (
    "project-goal-audit-v2-semantic-question-authority-v1-activate-protocol"
)
AUTHORITY_REASON = (
    "bind exact semantic question identity and typed Study reentry lineage"
)
AUDIT_REPORT = Path(
    "records/audits/2026-07-16_semantic_question_lineage_audit.md"
)
EXPECTED_REPORT_SHA256 = (
    "fb7146f4897a985406381ee96ef7f1966246b7fab7e8c20379d522a86ec03101"
)
EXPECTED_REPORT_SIZE = 5334
EXPECTED_REPORT_MARKERS = (
    "status: repaired_pending_activation",
    "- Study declarations: 112",
    "- Exact semantic question cores: 108",
    "- Typed historical lineage edges: 13",
    "## Quant-Team Review",
    "scientific_trial_delta: 0",
    "scientific_claim_delta: 0",
)
EXPECTED_PREDECESSOR_SHA256 = {
    "OPERATING_DIRECTION.md": (
        "630794dda943c570fbc3bca6d80815a6eb24beb316d9838108726a738cf3b63d"
    ),
    "contracts/operations.yaml": (
        "68ae8fc5e40d8cc9c1d60afda5e1d2aaffdf99a34c2fd46d510e8d11ad1f6114"
    ),
    "contracts/science.yaml": (
        "9b15f3fc4c67a49aa2a5603a487fa3c39703414b19b12f41a8735c10c5e384df"
    ),
}
EXPECTED_SUCCESSOR_SHA256 = {
    "OPERATING_DIRECTION.md": (
        "63b9929a77274ec807ed5849a3173fcf3cadc126816913e3c3856fe31a85f787"
    ),
    "contracts/operations.yaml": (
        "9e2e96f6df50f1f20aa01532bb8e96e15a0080e1a42a8dbe6cf952861d1e6497"
    ),
    "contracts/science.yaml": (
        "dd168f00df3c7c1b27b8fca7ffe9683bcd0e893a1bbdbecd3ac614bc27f0b818"
    ),
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor block differs")
    return text.replace(old, new, 1)


def _operating_direction(text: str) -> str:
    return _replace_once(
        text,
        """- [MUST] OD-TAX-009 Trials, claims, and negative memory bind to immutable
  Executables. A Lineage never merges distinct Executable evidence.
""",
        """- [MUST] OD-TAX-009 Trials, claims, and negative memory bind to immutable
  Executables. A Lineage never merges distinct Executable evidence.
- [MUST] OD-TAX-010 An exact semantic question core consists only of the declared
  causal question and its changed and controlled variables. It groups research
  intent but never merges Studies, Batches, Executables, trials, evidence,
  claims, KPI, or negative memory.
- [MUST] OD-TAX-011 Every Study binds exactly one semantic question core. Reuse of
  an existing exact core requires a typed predecessor relation. A relation
  between distinct cores requires explicit expert-reviewed equivalence unless
  it is a semantic revision to a distinct non-equivalent estimand.
- [MUST] OD-TAX-012 A successor result never rewrites or inherits predecessor
  evidence. Engineering reentry may resolve only an exact predecessor
  non-scientific gap through successor-only evidence; semantic revision retains
  a distinct estimand and no retrospective resolution authority.
""",
        label="operating direction semantic question taxonomy",
    )


def _operations_contract(text: str) -> str:
    return _replace_once(
        text,
        """    later_batch_open_requires_current_continue_record_and_exact_batch_id: true
    commitment_bound_excess_allowed: false
    judge_study_bypass_allowed: false
active_state:
""",
        """    later_batch_open_requires_current_continue_record_and_exact_batch_id: true
    commitment_bound_excess_allowed: false
    judge_study_bypass_allowed: false
semantic_question_registry:
  state_writer_is_only_writer: true
  activation_event: semantic_question_registry_backfilled
  activation_is_atomic_with_complete_historical_projection: true
  activation_requires_stable_scientific_boundary: true
  historical_source_scan:
    allowed_only_at_explicit_backfill: true
    source_kind: study-open
    routine_repeat_lookup_is_fingerprint_indexed: true
  one_study_binds_exactly_one_core: true
  prospective_study_open_atomically_records_core_binding_and_typed_lineage: true
  repeated_exact_core_without_typed_lineage_allowed: false
  distinct_core_nonrevision_lineage_requires_accepted_exact_equivalence: true
  semantic_revision_conflicting_with_accepted_equivalence_allowed: false
  historical_correction:
    event: semantic_question_corrections_recorded
    additive_only: true
    exact_current_protocol_audit_artifact_required: true
    plural_quant_team_review_required: true
    rewrites_old_records: false
    trial_holdout_claim_and_failure_deltas: zero
  successor_close_resolution_is_additive_and_successor_only: true
  equivalence_or_lineage_is_executable_trial_claim_kpi_or_memory_authority: false
active_state:
""",
        label="operations semantic question registry",
    )


def _science_contract(text: str) -> str:
    text = _replace_once(
        text,
        """      - negative_memory
      - portfolio_decisions
      - study_kpi
""",
        """      - negative_memory
      - portfolio_decisions
      - semantic_question_lineage
      - study_kpi
""",
        label="science semantic question intake surface",
    )
    return _replace_once(
        text,
        """  exhaustion_requires:
    - mechanism_family_diversity
    - primary_research_layer_diversity
    - system_architecture_family_diversity
    - validator_demonstrated_negative_depth
portfolio:
""",
        """  exhaustion_requires:
    - mechanism_family_diversity
    - primary_research_layer_diversity
    - system_architecture_family_diversity
    - validator_demonstrated_negative_depth
semantic_question_registry:
  core_fields:
    - causal_question
    - changed_variables
    - controlled_variables
  protocol_fields_are_not_core_identity: true
  natural_language_similarity_or_fuzzy_stripping_is_authority: false
  one_study_one_core: true
  repeated_exact_core_requires_typed_lineage: true
  relations:
    - engineering_reentry
    - continuation
    - independent_replication
    - confirmation
    - semantic_revision
  distinct_core_nonrevision_relation_requires_explicit_equivalence: true
  semantic_revision_requires_distinct_non_equivalent_core: true
  equivalence_scope: declared_question_core_only
  equivalence_is_transitive_authority: false
  executable_trial_evidence_claim_kpi_and_negative_memory_transfer: false
  engineering_reentry_requires_exact_non_scientific_gap_and_successor_evidence: true
  not_identifiable_label_alone_is_reentry_authority: false
  semantic_revision_resolves_predecessor_estimand: false
  historical_correction_requires_current_protocol_review_artifact: true
  historical_review_uses_plural_quant_team_lenses: true
  historical_corrections_are_additive_zero_credit: true
portfolio:
""",
        label="science semantic question registry",
    )


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "OPERATING_DIRECTION.md": _operating_direction,
    "contracts/operations.yaml": _operations_contract,
    "contracts/science.yaml": _science_contract,
}
SUCCESSOR_MARKERS = {
    "OPERATING_DIRECTION.md": (
        "OD-TAX-010",
        "OD-TAX-011",
        "OD-TAX-012",
    ),
    "contracts/operations.yaml": (
        "semantic_question_registry:",
        "activation_event: semantic_question_registry_backfilled",
        "repeated_exact_core_without_typed_lineage_allowed: false",
    ),
    "contracts/science.yaml": (
        "semantic_question_registry:",
        "one_study_one_core: true",
        "semantic_revision_resolves_predecessor_estimand: false",
    ),
}


def _read_audit_report(root: Path = ROOT) -> bytes:
    content = (root / AUDIT_REPORT).read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("semantic question audit report is not ASCII") from exc
    if (
        len(content) != EXPECTED_REPORT_SIZE
        or sha256(content).hexdigest() != EXPECTED_REPORT_SHA256
        or any(text.count(marker) != 1 for marker in EXPECTED_REPORT_MARKERS)
    ):
        raise RuntimeError("semantic question audit report bytes differ")
    return content


def desired_replacements(root: Path = ROOT) -> tuple[dict[str, bytes], str]:
    current = {relative: (root / relative).read_bytes() for relative in TRANSFORMS}
    observed = {
        relative: sha256(content).hexdigest()
        for relative, content in current.items()
    }
    materialized = all(
        all(marker.encode("ascii") in current[relative] for marker in markers)
        for relative, markers in SUCCESSOR_MARKERS.items()
    )
    if materialized:
        return current, "already_materialized"
    if observed == EXPECTED_SUCCESSOR_SHA256:
        return current, "already_materialized"
    if observed != EXPECTED_PREDECESSOR_SHA256:
        raise RuntimeError("semantic question authority predecessor is mixed or unknown")
    desired: dict[str, bytes] = {}
    for relative, transform in TRANSFORMS.items():
        content = transform(current[relative].decode("ascii")).encode("ascii")
        if not content.endswith(b"\n"):
            raise RuntimeError(f"{relative} replacement lost its final newline")
        if relative.endswith(".yaml"):
            parsed = yaml.safe_load(content.decode("ascii"))
            if not isinstance(parsed, dict):
                raise RuntimeError(f"{relative} replacement is not a YAML mapping")
        desired[relative] = content
    transformed = {
        relative: sha256(content).hexdigest()
        for relative, content in desired.items()
    }
    if transformed != EXPECTED_SUCCESSOR_SHA256:
        raise RuntimeError("semantic question authority successor hashes differ")
    return desired, "activate"


def plan_activation(root: Path = ROOT) -> dict[str, object]:
    report = _read_audit_report(root)
    replacements, mode = desired_replacements(root)
    return {
        "authority_operation_id": AUTHORITY_OPERATION_ID,
        "mode": mode,
        "protocol_operation_id": PROTOCOL_OPERATION_ID,
        "report_sha256": sha256(report).hexdigest(),
        "replacement_sha256": {
            relative: sha256(content).hexdigest()
            for relative, content in sorted(replacements.items())
        },
        "schema": "semantic_question_authority_activation_plan.v1",
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    report = _read_audit_report(root)
    replacements, mode = desired_replacements(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("semantic question activation requires control")
    before = deepcopy(before)
    report_artifact = writer.evidence.finalize(report)
    migration = writer.migrate_authority(
        replacements=replacements,
        reason=AUTHORITY_REASON,
        operation_id=AUTHORITY_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    migrated = writer.read_control()
    if migrated is None:
        raise RuntimeError("semantic question authority migration lost control")
    activation = writer.activate_research_protocol(
        activation=ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            authority_manifest_digest=migrated["authority"]["manifest_digest"],
            audit_artifact_hash=report_artifact.sha256,
        ),
        operation_id=PROTOCOL_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    after = writer.read_control()
    if after is None:
        raise RuntimeError("semantic question protocol activation lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"semantic question activation changed {field}")
    event_delta = int(not migration.reused) + int(not activation.reused)
    if after["revision"] != before["revision"] + event_delta:
        raise RuntimeError("semantic question activation revision differs")
    if after["authority"]["manifest_digest"] == before["authority"]["manifest_digest"]:
        if not migration.reused:
            raise RuntimeError("semantic question migration changed no authority")
    elif migration.reused:
        raise RuntimeError("semantic question authority changed on reused migration")
    return {
        "authority_event_id": migration.event_id,
        "authority_reused": migration.reused,
        "mode": mode,
        "new_manifest_digest": after["authority"]["manifest_digest"],
        "protocol_event_id": activation.event_id,
        "protocol_reused": activation.reused,
        "revision": after["revision"],
        "schema": "semantic_question_authority_activation_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit exactly the authority migration and protocol activation",
    )
    args = parser.parse_args()
    result = apply_activation(ROOT) if args.apply else plan_activation(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
