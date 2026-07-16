#!/usr/bin/env python3
"""Activate the typed final-completion boundary for started Batch exit."""

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
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
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
    "project-goal-audit-v2-typed-started-batch-exit-v1"
)
PROTOCOL_OPERATION_ID = (
    "project-goal-audit-v2-typed-started-batch-exit-v1-activate-protocol"
)
AUTHORITY_REASON = (
    "require final stop completion for every started non-budget Batch exit"
)
AUDIT_REPORT = Path(
    "records/audits/2026-07-16_typed_started_batch_exit.md"
)
EXPECTED_REPORT_SHA256 = (
    "e053b41545caab70d3820bcd255cb661672e9df0c2c3f40c17106729b4593d6f"
)
EXPECTED_REPORT_SIZE = 1891
EXPECTED_REPORT_MARKERS = (
    "status: repaired_pending_activation",
    "A `continue_batch` Decision keeps bounded work or Repair open",
    "scientific_claim_delta: 0",
)
EXPECTED_PREDECESSOR_SHA256 = {
    "contracts/operations.yaml": (
        "38ced94305b7102e1eb2bea86b37f146b6db68668b82a29cc5ef1d8b891c010e"
    ),
    "contracts/science.yaml": (
        "1d03c78721bf31ff3a471661e542bf952bb5fd44d8a8496e9a74303f71c8e201"
    ),
}
EXPECTED_SUCCESSOR_SHA256 = {
    "contracts/operations.yaml": (
        "68ae8fc5e40d8cc9c1d60afda5e1d2aaffdf99a34c2fd46d510e8d11ad1f6114"
    ),
    "contracts/science.yaml": (
        "9b15f3fc4c67a49aa2a5603a487fa3c39703414b19b12f41a8735c10c5e384df"
    ),
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor block differs")
    return text.replace(old, new, 1)


def _science_contract(text: str) -> str:
    text = _replace_once(
        text,
        """    typed_final_engineering_failure_can_stop_batch_as_not_evaluable: true
    scientific_close_outcome_matches_exact_adjudication: true
""",
        """    typed_final_engineering_failure_can_stop_batch_as_not_evaluable: true
    started_nonbudget_exit_requires_exact_stop_completion: true
    continue_batch_is_started_batch_close_authority: false
    scientific_close_outcome_matches_exact_adjudication: true
""",
        label="science typed started-Batch exit",
    )
    return _replace_once(
        text,
        """      started_batch_outcomes:
        budget_exhausted: exact_frozen_compute_wall_or_trial_bound
        stopped_early: explicit_typed_disposition
        not_evaluable: final_non_scientific_not_evaluable_failure
        engineering_failure: final_non_scientific_engineering_failure
""",
        """      started_batch_outcomes:
        budget_exhausted: exact_frozen_compute_wall_or_trial_bound
      legacy_started_batch_outcomes_before_typed_exit_activation:
        read_only_projection_compatibility: true
        stopped_early: pre_activation_untyped_disposition
        not_evaluable: pre_activation_final_non_scientific_failure
        engineering_failure: pre_activation_final_non_scientific_failure
""",
        label="science no-final-completion outcomes",
    )


def _operations_contract(text: str) -> str:
    return _replace_once(
        text,
        """repair:
  scientific_identity_frozen: true
  scientific_trial_delta: 0
  scientific_failure_delta: 0
  required:
""",
        """repair:
  scientific_identity_frozen: true
  scientific_trial_delta: 0
  scientific_failure_delta: 0
  started_batch_exit:
    no_final_completion_outcomes: [budget_exhausted]
    exact_frozen_budget_exhaustion_is_writer_derived: true
    engineering_not_evaluable_or_early_stop_requires_stop_batch: true
    typed_unrecovered_engineering_completion_required: true
    batch_outcome_must_match_typed_engineering_completion: true
    continue_batch_can_dispose_started_batch: false
    legacy_pre_activation_projection_is_read_only: true
  required:
""",
        label="operations started-Batch exit",
    )


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "contracts/operations.yaml": _operations_contract,
    "contracts/science.yaml": _science_contract,
}


def _read_audit_report(root: Path = ROOT) -> bytes:
    content = (root / AUDIT_REPORT).read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("typed started-Batch audit report is not ASCII") from exc
    if (
        len(content) != EXPECTED_REPORT_SIZE
        or sha256(content).hexdigest() != EXPECTED_REPORT_SHA256
        or any(text.count(marker) != 1 for marker in EXPECTED_REPORT_MARKERS)
    ):
        raise RuntimeError("typed started-Batch audit report bytes differ")
    return content


def desired_replacements(
    root: Path = ROOT,
) -> tuple[dict[str, bytes], str]:
    current = {
        relative: (root / relative).read_bytes()
        for relative in TRANSFORMS
    }
    observed = {
        relative: sha256(content).hexdigest()
        for relative, content in current.items()
    }
    if observed == EXPECTED_SUCCESSOR_SHA256:
        return current, "already_materialized"
    if observed != EXPECTED_PREDECESSOR_SHA256:
        raise RuntimeError(
            "typed started-Batch authority predecessor is mixed or unknown"
        )
    desired: dict[str, bytes] = {}
    for relative, transform in TRANSFORMS.items():
        content = transform(current[relative].decode("ascii")).encode("ascii")
        if not content.endswith(b"\n"):
            raise RuntimeError(f"{relative} replacement lost its final newline")
        parsed = yaml.safe_load(content.decode("ascii"))
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{relative} replacement is not a YAML mapping")
        desired[relative] = content
    transformed = {
        relative: sha256(content).hexdigest()
        for relative, content in desired.items()
    }
    if transformed != EXPECTED_SUCCESSOR_SHA256:
        raise RuntimeError("typed started-Batch successor hashes differ")
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
        "schema": "typed_started_batch_exit_activation_plan.v1",
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    report = _read_audit_report(root)
    replacements, mode = desired_replacements(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("typed started-Batch activation requires control")
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
        raise RuntimeError("typed started-Batch authority migration lost control")
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
        raise RuntimeError("typed started-Batch protocol activation lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(
                f"typed started-Batch activation changed {field}"
            )
    event_delta = int(not migration.reused) + int(not activation.reused)
    if after["revision"] != before["revision"] + event_delta:
        raise RuntimeError("typed started-Batch activation revision differs")
    if after["authority"]["manifest_digest"] == before["authority"]["manifest_digest"]:
        if not migration.reused:
            raise RuntimeError("typed started-Batch migration changed no authority")
    elif migration.reused:
        raise RuntimeError("typed started-Batch authority changed on reused migration")
    return {
        "authority_event_id": migration.event_id,
        "authority_reused": migration.reused,
        "mode": mode,
        "new_manifest_digest": after["authority"]["manifest_digest"],
        "protocol_event_id": activation.event_id,
        "protocol_reused": activation.reused,
        "revision": after["revision"],
        "schema": "typed_started_batch_exit_activation_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the two typed StateWriter activation events",
    )
    args = parser.parse_args()
    result = apply_activation(ROOT) if args.apply else plan_activation(ROOT)
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
