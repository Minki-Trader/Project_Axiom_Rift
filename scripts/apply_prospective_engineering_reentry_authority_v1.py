"""Activate typed non-replay engineering-gap successor authority."""

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
    "project-goal-audit-v3-prospective-engineering-reentry-authority-v1"
)
PROTOCOL_OPERATION_ID = AUTHORITY_OPERATION_ID + "-activate-protocol"
PREDECESSOR_AUTHORITY_DIGEST = (
    "08b8dfb9039f22f220a40b78636ca0c418445e9f22c7924ba8fc6d308efe90c0"
)
AUTHORITY_PATHS = (
    "contracts/operations.yaml",
    "contracts/science.yaml",
)
REQUIRED_MARKERS = {
    "contracts/operations.yaml": (
        "prospective_engineering_reentry:\n",
        "  same_architecture_protocol_correction_supported: true\n",
        "  quant_team_review_binds_gap_disposition_and_successor: true\n",
    ),
    "contracts/science.yaml": (
        "  prospective_non_replay_engineering_reentry_supported: true\n",
        "  prospective_engineering_reentry:\n",
        "    predecessor_science_or_negative_memory_is_inherited: false\n",
    ),
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor differs")
    return text.replace(old, new, 1)


def _operations_contract(text: str) -> str:
    marker = "prospective_engineering_reentry:\n"
    if marker in text:
        return text
    return _replace_once(
        text,
        """  trial_holdout_and_candidate_delta: 0
replay_implementation_admission:
""",
        """  trial_holdout_and_candidate_delta: 0
prospective_engineering_reentry:
  single_writer: axiom_rift.operations.writer.StateWriter
  authority_schema: prospective_engineering_reentry.v1
  validation_schema: prospective_engineering_reentry_validation.v1
  exact_closed_study_diagnosis_completion_and_disposition_join_required: true
  requires_scientific_change_disposition_required: true
  registered_successor_artifact_and_baseline_executable_required: true
  successor_study_and_baseline_are_preregistered_before_outcomes: true
  same_semantic_question_requires_engineering_reentry_lineage: true
  predecessor_and_successor_study_identities_are_distinct: true
  predecessor_trial_executable_cannot_be_successor_baseline: true
  same_architecture_protocol_correction_supported: true
  changed_architecture_requires_exact_typed_equivalence: true
  accepted_actions:
    - contrast
    - deepen
  quant_team_review_binds_gap_disposition_and_successor: true
  unrelated_forest_options_remain_materially_selectable: true
  engineering_reentry_is_diagnosis_continuation_not_diagnosis_override: true
  scientific_trial_claim_failure_candidate_holdout_and_terminal_delta: 0
replay_implementation_admission:
""",
        label="operations prospective engineering reentry contract",
    )


def _science_contract(text: str) -> str:
    if "  prospective_non_replay_engineering_reentry_supported: true\n" in text:
        return text
    text = _replace_once(
        text,
        """  engineering_reentry_requires_exact_non_scientific_gap_and_successor_evidence: true
  not_identifiable_label_alone_is_reentry_authority: false
""",
        """  engineering_reentry_requires_exact_non_scientific_gap_and_successor_evidence: true
  prospective_non_replay_engineering_reentry_supported: true
  exact_gap_disposition_and_registered_successor_are_reentry_authority: true
  not_identifiable_label_alone_is_reentry_authority: false
""",
        label="science semantic-question reentry contract",
    )
    return _replace_once(
        text,
        """    - synthesize
    - revise_protocol
batch:
""",
        """    - synthesize
    - revise_protocol
  prospective_engineering_reentry:
    same_axis_only: true
    accepted_actions:
      - contrast
      - deepen
    exact_effective_engineering_gap_diagnosis_required: true
    requires_scientific_change_disposition_required: true
    quant_team_review_binds_diagnosis_close_completion_disposition_and_successor: true
    corrected_baseline_is_content_addressed_and_distinct: true
    same_architecture_protocol_correction_supported: true
    architecture_change_requires_explicit_equivalence: true
    successor_study_is_preregistered_before_result_access: true
    predecessor_science_or_negative_memory_is_inherited: false
    zero_credit_until_successor_produces_valid_evidence: true
    diversifying_option_remains_selectable: true
batch:
""",
        label="science Portfolio reentry contract",
    )


def _replacements(root: Path = ROOT) -> dict[str, bytes]:
    transforms = {
        "contracts/operations.yaml": _operations_contract,
        "contracts/science.yaml": _science_contract,
    }
    replacements: dict[str, bytes] = {}
    for relative, transform in transforms.items():
        text = transform((root / relative).read_bytes().decode("ascii"))
        if any(marker not in text for marker in REQUIRED_MARKERS[relative]):
            raise RuntimeError(f"{relative} lacks prospective reentry authority")
        if not isinstance(yaml.safe_load(text), dict):
            raise RuntimeError(f"{relative} is not an authority mapping")
        replacements[relative] = text.encode("ascii")
    return replacements


def _audit_manifest(replacements: dict[str, bytes]) -> bytes:
    return canonical_bytes(
        {
            "authority_paths": list(AUTHORITY_PATHS),
            "completion_record_id": (
                "f3ecc7e7934fde373998d012a455f8df0f0d85be79bc445fcd293f81469acac8"
            ),
            "diagnosis_id": (
                "diagnosis:731be2e2dfa9fe0dc707b4b233d848d54e193602ce61e37fb128b92e38922840"
            ),
            "disposition_record_id": (
                "e0ee048da9db4f6e4fcbc7badc243f1d7994a4c4a29ed0ac859713c1553f170a"
            ),
            "portfolio_snapshot_id": (
                "portfolio:e693ac3c70b098d3e7da5ed645e3c320d9ce73202ff6d3ed32cf13f0d96296ab"
            ),
            "predecessor_study_id": "STU-0122",
            "replacement_sha256": {
                relative: sha256(content).hexdigest()
                for relative, content in sorted(replacements.items())
            },
            "schema": "prospective_engineering_reentry_authority_audit.v1",
            "scientific_claim_delta": 0,
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
            "study_close_record_id": (
                "2bfc731c7596538c8f2fed5f0844dd900178d1039be456915839d3b0f6f41ab5"
            ),
            "successor_artifact_hash": (
                "39c45990a6e003cd71799cc64e6073ec15eaa5774a89d55c6822f11c2fbded3a"
            ),
            "successor_study_id": "STU-0123",
        }
    )


def plan_activation(root: Path = ROOT) -> dict[str, object]:
    replacements = _replacements(root)
    writer = StateWriter(root)
    control = writer.read_control()
    if control is None:
        raise RuntimeError("prospective reentry authority requires control")
    current_digest = control["authority"]["manifest_digest"]
    existing = None
    if current_digest != PREDECESSOR_AUTHORITY_DIGEST:
        with writer.open_stable_index() as (_control, index):
            existing = index.get("operation", AUTHORITY_OPERATION_ID)
        if existing is None:
            raise RuntimeError("prospective reentry authority predecessor differs")
    return {
        "authority_operation_id": AUTHORITY_OPERATION_ID,
        "current_manifest_digest": current_digest,
        "mode": "already_applied" if existing is not None else "activate",
        "protocol_operation_id": PROTOCOL_OPERATION_ID,
        "replacement_sha256": {
            relative: sha256(content).hexdigest()
            for relative, content in sorted(replacements.items())
        },
        "schema": "prospective_engineering_reentry_authority_plan.v1",
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    replacements = _replacements(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("prospective reentry authority requires control")
    before = deepcopy(before)
    audit = writer.evidence.finalize(_audit_manifest(replacements))
    migration = writer.migrate_authority(
        replacements=replacements,
        reason=(
            "bind typed prospective non-replay engineering-gap successor work"
        ),
        operation_id=AUTHORITY_OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    migrated = writer.read_control()
    if migrated is None:
        raise RuntimeError("prospective reentry migration lost control")
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
        raise RuntimeError("prospective reentry protocol activation lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"prospective reentry activation changed {field}")
    return {
        "authority_event_id": migration.event_id,
        "authority_reused": migration.reused,
        "new_manifest_digest": after["authority"]["manifest_digest"],
        "protocol_event_id": activation.event_id,
        "protocol_reused": activation.reused,
        "revision": after["revision"],
        "schema": "prospective_engineering_reentry_authority_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    result = apply_activation(ROOT) if arguments.apply else plan_activation(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
