#!/usr/bin/env python3
"""Activate bounded Study-close validation and lag-tolerant KPI navigation."""

from __future__ import annotations

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
    require_all_study_close_deliveries,
    require_study_close_guard_ready,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402


OPERATION_ID = "study-kpi-lag-tolerant-navigation-v1"
REASON = "bound routine Study close to one KPI suffix and explicit navigation maintenance"
EXPECTED_PREDECESSOR_SHA256 = {
    "OPERATING_DIRECTION.md": "af90e2f4b6b51d0441f499a640f5b91d0886e741fd5641cbbe01e246bb3c5804",
    "contracts/operations.yaml": "4f59dbd579062eb4769e620989c916f935a7f0be4574e43e272605e104fbde38",
    "contracts/science.yaml": "48ff80f4fc2d416e76e9b5a4fc6b033042a36d213435170f911973feeb893136",
}


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor block differs")
    return text.replace(old, new, 1)


def _operating_direction(text: str) -> str:
    return _replace_once(
        text,
        """- [MUST] OD-REC-014 Every real Study close is one coherent user-observation
  checkpoint. It appends exactly one subject-bound summary row derived from
  the final validator completion or a Writer-verified disposed-Batch basis
  with no applicable final validator completion, creates one local-main
  closeout commit, and immediately attempts non-force delivery to origin/main
  before later scientific work.
""",
        """- [MUST] OD-REC-014 Every real Study close is one coherent user-observation
  checkpoint. It appends exactly one immutable subject-bound `study-kpi`
  Journal record derived from the final validator completion or a Writer-
  verified disposed-Batch basis with no applicable final validator completion,
  validates only the authenticated bounded suffix, creates one local-main
  closeout commit, and immediately attempts non-force delivery to origin/main
  before later scientific work. The complete Markdown KPI navigation view is
  lag-tolerant explicit maintenance and its freshness never blocks valid
  science.
""",
        label="operating direction Study-close clause",
    )


def _operations_contract(text: str) -> str:
    replacements = (
        (
            """    kpi_record_kind: study-kpi
    kpi_projection: records/STUDY_KPI.md
""",
            """    kpi_record_kind: study-kpi
    kpi_authority: immutable_journal_record
    kpi_projection: records/STUDY_KPI.md
    kpi_projection_role: lag_tolerant_navigation_only
    routine_kpi_projection_materialization_required: false
""",
            "operations KPI role",
        ),
        (
            """    remote_equality_required_before_later_scientific_work: false
    required_same_commit_paths:
      - state/control.json
      - records/STUDY_KPI.md
""",
            """    remote_equality_required_before_later_scientific_work: false
    required_same_commit_paths:
      - state/control.json
      - records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json
""",
            "operations Study-close paths",
        ),
        (
            """    one_commit_per_study_close: true
    separate_batch_job_fold_or_kpi_commit_allowed: false
""",
            """    one_commit_per_study_close: true
    separate_batch_job_or_fold_commit_allowed: false
    separate_kpi_navigation_maintenance_allowed: true
""",
            "operations close milestone split",
        ),
        (
            """      staged_state_journal_and_kpi_required_together: true
      deterministic_staged_kpi_rerender_required: true
      exact_contiguous_final_trailer_block_required: true
""",
            """      staged_control_journal_and_checkpoint_required_together: true
      routine_kpi_markdown_change_forbidden: true
      exact_new_kpi_record_semantic_validation_required: true
      complete_kpi_rerender: explicit_maintenance_only
      exact_contiguous_final_trailer_block_required: true
""",
            "operations automated close enforcement",
        ),
        (
            """      commit_changes_all_required_same_commit_paths: true
      commit_snapshot_journal_tail_matches_event: true
      commit_snapshot_control_head_matches_event_and_revision: true
      commit_snapshot_kpi_projection_equals_deterministic_journal_render: true
      local_commit_absence_requires_resume_before_state_or_science_action: true
""",
            """      commit_changes_all_required_same_commit_paths: true
      commit_snapshot_bounded_journal_suffix_matches_event: true
      commit_snapshot_control_and_index_heads_match_event: true
      commit_snapshot_new_kpi_record_and_checkpoint_transition_valid: true
      complete_kpi_projection_scan_required: false
      local_commit_absence_requires_resume_before_state_or_science_action: true
""",
            "operations boot close audit",
        ),
        (
            """  schema: study_close_delivery_checkpoint.v2
  git_authenticated_high_water: true
""",
            """  schema: study_close_delivery_checkpoint.v2
  validator_version: study_close_delivery_checkpoint.v3
  legacy_v2_transition: explicit_maintenance_activation
  git_authenticated_high_water: true
""",
            "operations checkpoint validator activation",
        ),
        (
            """  prospective_required_same_commit_paths:
    - state/control.json
    - records/STUDY_KPI.md
    - resolved_journal_paths
    - records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json
  omitted_modified_or_malformed_checkpoint_blocks_later_science: true
  no_op_guard_rewrites_local_projection: false
""",
            """  prospective_required_same_commit_paths:
    - state/control.json
    - resolved_journal_paths
    - records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json
  omitted_modified_or_malformed_checkpoint_blocks_later_science: true
  no_op_guard_rewrites_local_projection: false
  kpi_navigation_maintenance:
    complete_history_scan_required: true
    writes_markdown_projection: true
    checkpoint_kpi_digest_update_required: true
    may_share_with_no_close_cursor_advance: true
    no_op_commit_allowed: false
    later_science_freshness_gate: false
""",
            "operations checkpoint navigation maintenance",
        ),
    )
    for old, new, label in replacements:
        text = _replace_once(text, old, new, label=label)
    return text


def _science_contract(text: str) -> str:
    text = _replace_once(
        text,
        """  scientific_authority: false
  prospective_from_activation: true
""",
        """  scientific_authority: false
  materialization: explicit_stable_boundary_maintenance
  may_lag_journal_authority: true
  freshness_blocks_research: false
  current_decision_source: authenticated_query_projection
  prospective_from_activation: true
""",
        label="science KPI materialization role",
    )
    return _replace_once(
        text,
        """  one_row_per_real_study_close: true
  sequence:
""",
        """  eventual_one_row_per_real_study_close: true
  routine_close_row_materialization_required: false
  sequence:
""",
        label="science KPI row timing",
    )


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "OPERATING_DIRECTION.md": _operating_direction,
    "contracts/operations.yaml": _operations_contract,
    "contracts/science.yaml": _science_contract,
}
NEW_MARKERS = {
    "OPERATING_DIRECTION.md": "lag-tolerant explicit maintenance",
    "contracts/operations.yaml": "kpi_projection_role: lag_tolerant_navigation_only",
    "contracts/science.yaml": "materialization: explicit_stable_boundary_maintenance",
}


def _desired_replacements() -> tuple[dict[str, bytes], str]:
    current = {relative: (ROOT / relative).read_bytes() for relative in TRANSFORMS}
    observed = {
        relative: sha256(content).hexdigest()
        for relative, content in current.items()
    }
    predecessor = observed == EXPECTED_PREDECESSOR_SHA256
    activated = all(
        marker.encode("ascii") in current[relative]
        for relative, marker in NEW_MARKERS.items()
    )
    if not predecessor and not activated:
        raise RuntimeError("Study KPI authority predecessor is mixed or unknown")
    if activated:
        return current, "already_materialized"
    desired: dict[str, bytes] = {}
    for relative, transform in TRANSFORMS.items():
        text = current[relative].decode("ascii")
        replacement = transform(text).encode("ascii")
        if not replacement.endswith(b"\n"):
            raise RuntimeError(f"{relative} replacement lost its final newline")
        if relative.endswith(".yaml"):
            parsed = yaml.safe_load(replacement)
            if not isinstance(parsed, dict):
                raise RuntimeError(f"{relative} replacement is not a YAML mapping")
        desired[relative] = replacement
    return desired, "activate"


def main() -> None:
    require_study_close_guard_ready(ROOT)
    require_all_study_close_deliveries(ROOT)
    replacements, mode = _desired_replacements()
    writer = StateWriter(ROOT)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("Study KPI authority migration requires control")
    before = deepcopy(before)
    transition = writer.migrate_authority(
        replacements=replacements,
        reason=REASON,
        operation_id=OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    after = writer.read_control()
    if after is None:
        raise RuntimeError("Study KPI authority migration lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"Study KPI authority migration changed {field}")
    if after["revision"] != before["revision"] + (0 if transition.reused else 1):
        raise RuntimeError("Study KPI authority migration revision differs")
    print(
        json.dumps(
            {
                "event_id": transition.event_id,
                "mode": mode,
                "new_manifest_digest": after["authority"]["manifest_digest"],
                "reused": transition.reused,
                "revision": transition.revision,
                "schema": "study_kpi_navigation_activation.v1",
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
