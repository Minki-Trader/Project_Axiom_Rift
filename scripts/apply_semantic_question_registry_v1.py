#!/usr/bin/env python3
"""Audit, backfill, and correct the semantic-question Study registry."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.running_job import RunningJobAuthority  # noqa: E402
from axiom_rift.operations.semantic_question_registry import (  # noqa: E402
    SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID,
    backfill_semantic_question_records,
    require_semantic_question_projection,
    require_semantic_question_registry_activation,
    semantic_question_equivalence_record,
    semantic_question_lineage_record,
    semantic_question_registry_activation_record,
    study_semantic_evidence,
)
from axiom_rift.operations.study_close_git import (  # noqa: E402
    require_study_close_guard_ready,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionEquivalenceProposal,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndexView  # noqa: E402


BACKFILL_OPERATION_ID = (
    "project-goal-audit-v2-semantic-question-registry-backfill-v1"
)
CORRECTION_OPERATION_ID = (
    "project-goal-audit-v2-semantic-question-historical-corrections-v1"
)
AUDIT_REPORT = Path(
    "records/audits/2026-07-16_semantic_question_lineage_audit.md"
)
REVIEW_ARTIFACT_SHA256 = (
    "fb7146f4897a985406381ee96ef7f1966246b7fab7e8c20379d522a86ec03101"
)
EXPECTED_STUDY_COUNT = 112
EXPECTED_CORE_COUNT = 108
EXPECTED_PROJECTION_COUNT = 220
EXPECTED_DUPLICATE_GROUPS = {
    ("STU-0018", "STU-0019", "STU-0094"),
    ("STU-0073", "STU-0083"),
    ("STU-0097", "STU-0098"),
}
EXPECTED_NON_SCIENTIFIC_GAPS = {
    "STU-0001",
    "STU-0006",
    "STU-0007",
    "STU-0010",
    "STU-0011",
    "STU-0044",
    "STU-0053",
    "STU-0070",
    "STU-0073",
    "STU-0097",
    "STU-0099",
    "STU-0103",
}
UNRESOLVED_EXTERNAL_GAP = "STU-0099"


@dataclass(frozen=True, slots=True)
class EquivalenceSpec:
    predecessor: str
    successor: str
    rationale: str


@dataclass(frozen=True, slots=True)
class LineageSpec:
    predecessor: str
    successor: str
    relation: SemanticQuestionRelation
    rationale: str


EQUIVALENCE_SPECS = (
    EquivalenceSpec(
        "STU-0053",
        "STU-0054",
        "The successor preserves the exact estimand after repairing the prior implementation gap.",
    ),
    EquivalenceSpec(
        "STU-0070",
        "STU-0071",
        "The successor preserves the exact estimand after replacing the failed evidence implementation.",
    ),
    EquivalenceSpec(
        "STU-0103",
        "STU-0104",
        "The successor preserves the exact estimand after correcting the source-bound execution path.",
    ),
)

LINEAGE_SPECS = (
    LineageSpec(
        "STU-0001",
        "STU-0002",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor changes the estimand after the predecessor remained non-evaluable.",
    ),
    LineageSpec(
        "STU-0006",
        "STU-0007",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor changes the scientific question rather than claiming a repaired result.",
    ),
    LineageSpec(
        "STU-0007",
        "STU-0008",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor changes the scientific question and retains a distinct estimand.",
    ),
    LineageSpec(
        "STU-0010",
        "STU-0011",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor revises the unresolved question without resolving its predecessor.",
    ),
    LineageSpec(
        "STU-0011",
        "STU-0012",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor revises the unresolved question without retrospective evidence transfer.",
    ),
    LineageSpec(
        "STU-0018",
        "STU-0019",
        SemanticQuestionRelation.CONTINUATION,
        "The successor requalifies the exact source-eligibility question under the next protocol version.",
    ),
    LineageSpec(
        "STU-0019",
        "STU-0094",
        SemanticQuestionRelation.CONTINUATION,
        "The successor recertifies the exact source-eligibility question in the later Mission context.",
    ),
    LineageSpec(
        "STU-0044",
        "STU-0045",
        SemanticQuestionRelation.SEMANTIC_REVISION,
        "The successor changes the estimand after the predecessor evidence gap.",
    ),
    LineageSpec(
        "STU-0053",
        "STU-0054",
        SemanticQuestionRelation.ENGINEERING_REENTRY,
        "The successor repairs the predecessor implementation gap and earns only its own result.",
    ),
    LineageSpec(
        "STU-0070",
        "STU-0071",
        SemanticQuestionRelation.ENGINEERING_REENTRY,
        "The successor repairs the predecessor evidence path and earns only its own result.",
    ),
    LineageSpec(
        "STU-0073",
        "STU-0083",
        SemanticQuestionRelation.ENGINEERING_REENTRY,
        "The successor resolves the exact deterministic score-projection identifiability gap.",
    ),
    LineageSpec(
        "STU-0097",
        "STU-0098",
        SemanticQuestionRelation.ENGINEERING_REENTRY,
        "The successor repairs the exact source-bound Study before scientific adjudication.",
    ),
    LineageSpec(
        "STU-0103",
        "STU-0104",
        SemanticQuestionRelation.ENGINEERING_REENTRY,
        "The successor repairs the source-bound execution gap and earns only its own result.",
    ),
)


class OverlayIndex:
    """Read-only authenticated index plus deterministic not-yet-written rows."""

    def __init__(self, base: LocalIndexView) -> None:
        self.base = base
        self.records: dict[tuple[str, str], IndexRecord] = {}

    def add(self, *records: IndexRecord) -> None:
        for record in records:
            key = (record.kind, record.record_id)
            current = self.get(*key)
            if current is not None and current != record:
                raise RuntimeError(f"overlay record collision: {key!r}")
            if current is None:
                self.records[key] = record

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self.records.get((kind, record_id)) or self.base.get(kind, record_id)

    def _merged(self, rows: Iterable[IndexRecord]) -> tuple[IndexRecord, ...]:
        merged = {(row.kind, row.record_id): row for row in rows}
        merged.update(self.records)
        return tuple(merged[key] for key in sorted(merged))

    def records_by_kind(self, kind: str) -> tuple[IndexRecord, ...]:
        return tuple(row for row in self._merged(self.base.records_by_kind(kind)) if row.kind == kind)

    def records_by_fingerprint(self, fingerprint: str) -> tuple[IndexRecord, ...]:
        return tuple(
            row
            for row in self._merged(self.base.records_by_fingerprint(fingerprint))
            if row.fingerprint == fingerprint
        )

    def records_by_subject_status(self, subject: str, status: str) -> tuple[IndexRecord, ...]:
        return tuple(
            row
            for row in self._merged(self.base.records_by_subject_status(subject, status))
            if row.subject == subject and row.status == status
        )

    def records_by_payload_text(self, kind: str, lookup_name: str, value: str) -> tuple[IndexRecord, ...]:
        return tuple(
            row
            for row in self._merged(self.base.records_by_payload_text(kind, lookup_name, value))
            if row.kind == kind and row.payload.get(lookup_name) == value
        )

    def event_head(self, stream: str):
        candidates = [
            row
            for row in self.records.values()
            if row.event_stream == stream and row.event_sequence is not None
        ]
        base_head = self.base.event_head(stream)
        if base_head is not None:
            candidates.append(
                self.base.get(base_head.record_kind, base_head.record_id)
            )
        candidates = [row for row in candidates if row is not None]
        if not candidates:
            return None
        latest = max(candidates, key=lambda row: row.event_sequence or 0)
        return SimpleNamespace(
            sequence=latest.event_sequence,
            record_kind=latest.kind,
            record_id=latest.record_id,
        )


@dataclass(frozen=True, slots=True)
class RegistryPlan:
    equivalences: tuple[SemanticQuestionEquivalenceProposal, ...]
    lineages: tuple[SemanticQuestionLineageProposal, ...]
    summary: Mapping[str, object]


def _require_review_report(root: Path) -> str:
    content = (root / AUDIT_REPORT).read_bytes()
    try:
        content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("semantic question review report is not ASCII") from exc
    observed = sha256(content).hexdigest()
    if observed != REVIEW_ARTIFACT_SHA256:
        raise RuntimeError("semantic question review report bytes differ")
    return observed


def _add_or_verify(index: OverlayIndex, records: Sequence[IndexRecord]) -> None:
    for record in records:
        pending = require_semantic_question_projection(index, record)
        if pending is not None:
            index.add(pending)


def _duplicate_groups(records: Sequence[IndexRecord]) -> set[tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for record in records:
        if record.kind == "semantic-question-study":
            grouped.setdefault(record.fingerprint, []).append(
                str(record.payload["study_id"])
            )
    return {
        tuple(sorted(studies))
        for studies in grouped.values()
        if len(studies) > 1
    }


def _require_duplicate_connectivity(
    groups: set[tuple[str, ...]],
    lineages: Sequence[SemanticQuestionLineageProposal],
) -> None:
    edges = {
        frozenset((lineage.predecessor_study_id, lineage.successor_study_id))
        for lineage in lineages
        if lineage.predecessor_core_id == lineage.successor_core_id
    }
    for group in groups:
        reached = {group[0]}
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if reached.intersection(edge) and not edge.issubset(reached):
                    reached.update(edge)
                    changed = True
        if reached != set(group):
            raise RuntimeError(f"duplicate semantic core lacks connected lineage: {group}")


def build_registry_plan(base: LocalIndexView) -> RegistryPlan:
    overlay = OverlayIndex(base)
    study_opens = tuple(base.records_by_kind("study-open"))
    if len(study_opens) != EXPECTED_STUDY_COUNT:
        raise RuntimeError(
            f"historical Study count differs: {len(study_opens)} != {EXPECTED_STUDY_COUNT}"
        )
    projections = backfill_semantic_question_records(study_opens)
    core_count = sum(row.kind == "semantic-question-core" for row in projections)
    binding_count = sum(row.kind == "semantic-question-study" for row in projections)
    if (
        len(projections) != EXPECTED_PROJECTION_COUNT
        or core_count != EXPECTED_CORE_COUNT
        or binding_count != EXPECTED_STUDY_COUNT
    ):
        raise RuntimeError("semantic question projection counts differ")
    duplicate_groups = _duplicate_groups(projections)
    if duplicate_groups != EXPECTED_DUPLICATE_GROUPS:
        raise RuntimeError(f"semantic duplicate groups differ: {duplicate_groups!r}")
    _add_or_verify(overlay, projections)
    activation = semantic_question_registry_activation_record(
        operation_id=BACKFILL_OPERATION_ID,
        study_count=binding_count,
        core_count=core_count,
    )
    _add_or_verify(overlay, (activation,))
    if require_semantic_question_registry_activation(overlay) is None:
        raise RuntimeError("semantic question registry activation disappeared")

    evidence = {
        study.record_id: study_semantic_evidence(overlay, study.record_id)
        for study in study_opens
    }
    close_gap_ids = {
        study_id
        for study_id, value in evidence.items()
        if any(
            close.status in {"not_evaluable", "evidence_gap"}
            for close in value.study_closes
        )
    }
    if close_gap_ids != EXPECTED_NON_SCIENTIFIC_GAPS:
        raise RuntimeError(
            f"non-scientific Study close set differs: {sorted(close_gap_ids)!r}"
        )
    reentry_gap_ids = {
        study_id
        for study_id, value in evidence.items()
        if value.has_non_scientific_reentry_gap
    }
    expected_reentry_gaps = EXPECTED_NON_SCIENTIFIC_GAPS - {"STU-0001"}
    if reentry_gap_ids != expected_reentry_gaps:
        raise RuntimeError(
            f"recoverable reentry gap set differs: {sorted(reentry_gap_ids)!r}"
        )

    equivalences: list[SemanticQuestionEquivalenceProposal] = []
    accepted: dict[tuple[str, str], IndexRecord] = {}
    for spec in EQUIVALENCE_SPECS:
        predecessor = evidence[spec.predecessor]
        successor = evidence[spec.successor]
        proposal = SemanticQuestionEquivalenceProposal(
            canonical_study_id=spec.predecessor,
            equivalent_study_id=spec.successor,
            canonical_core_id=predecessor.core.identity,
            equivalent_core_id=successor.core.identity,
            rationale=spec.rationale,
            basis_record_ids=(
                f"study-open:{spec.predecessor}",
                f"study-open:{spec.successor}",
            ),
        )
        record = semantic_question_equivalence_record(overlay, proposal)
        _add_or_verify(overlay, (record,))
        equivalences.append(proposal)
        accepted[(spec.predecessor, spec.successor)] = record

    lineages: list[SemanticQuestionLineageProposal] = []
    for spec in LINEAGE_SPECS:
        predecessor = evidence[spec.predecessor]
        successor = evidence[spec.successor]
        equivalence = accepted.get((spec.predecessor, spec.successor))
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=spec.predecessor,
            successor_study_id=spec.successor,
            predecessor_core_id=predecessor.core.identity,
            successor_core_id=successor.core.identity,
            relation=spec.relation,
            rationale=spec.rationale,
            basis_record_ids=tuple(
                sorted(
                    set(predecessor.record_references).union(
                        successor.record_references
                    )
                )
            ),
            equivalence_proposal_id=(
                None if equivalence is None else equivalence.fingerprint
            ),
        )
        record = semantic_question_lineage_record(
            overlay,
            proposal,
            equivalence_record=equivalence,
        )
        _add_or_verify(overlay, (record,))
        if (
            record.payload.get("scientific_trial_delta") != 0
            or record.payload.get("scientific_failure_delta") != 0
            or record.payload.get("claim_delta") != "none"
            or record.payload.get("evidence_transfer_authority") != "none"
        ):
            raise RuntimeError("semantic lineage manufactured scientific credit")
        lineages.append(proposal)

    covered_gap_ids = {
        item.predecessor_study_id
        for item in lineages
        if item.predecessor_study_id in close_gap_ids
    }
    expected_covered = close_gap_ids - {UNRESOLVED_EXTERNAL_GAP}
    if covered_gap_ids != expected_covered:
        raise RuntimeError("historical gap lineage coverage differs")
    _require_duplicate_connectivity(duplicate_groups, lineages)
    relation_counts = {
        relation.value: sum(item.relation is relation for item in lineages)
        for relation in SemanticQuestionRelation
    }
    expected_relation_counts = {
        "engineering_reentry": 5,
        "continuation": 2,
        "independent_replication": 0,
        "confirmation": 0,
        "semantic_revision": 6,
    }
    if relation_counts != expected_relation_counts:
        raise RuntimeError("semantic lineage relation counts differ")

    summary = {
        "activation_record_id": SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID,
        "backfill_operation_id": BACKFILL_OPERATION_ID,
        "core_count": core_count,
        "correction_operation_id": CORRECTION_OPERATION_ID,
        "duplicate_core_groups": [list(group) for group in sorted(duplicate_groups)],
        "equivalence_count": len(equivalences),
        "equivalence_proposal_ids": sorted(item.identity for item in equivalences),
        "historical_non_scientific_gap_count": len(close_gap_ids),
        "lineage_count": len(lineages),
        "lineage_proposal_ids": sorted(item.identity for item in lineages),
        "projection_count": len(projections),
        "relation_counts": relation_counts,
        "review_artifact_hash": REVIEW_ARTIFACT_SHA256,
        "scientific_claim_delta": 0,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "study_binding_count": binding_count,
        "unresolved_external_gap": UNRESOLVED_EXTERNAL_GAP,
    }
    return RegistryPlan(
        equivalences=tuple(equivalences),
        lineages=tuple(lineages),
        summary=summary,
    )


def plan_registry(root: Path = ROOT) -> Mapping[str, object]:
    _require_review_report(root)
    authority = RunningJobAuthority(root, foundation_root=root)
    with authority.open_stable_index() as (control, index):
        plan = build_registry_plan(index)
        return {
            **plan.summary,
            "current_revision": control["revision"],
            "schema": "semantic_question_registry_plan.v1",
        }


def apply_registry(root: Path = ROOT) -> Mapping[str, object]:
    require_study_close_guard_ready(root)
    review_artifact_hash = _require_review_report(root)
    before_authority = RunningJobAuthority(root, foundation_root=root)
    with before_authority.open_stable_index() as (before, before_index):
        preliminary = build_registry_plan(before_index)
    writer = StateWriter(root)
    backfill = writer.backfill_semantic_question_registry(
        operation_id=BACKFILL_OPERATION_ID
    )
    middle_authority = RunningJobAuthority(root, foundation_root=root)
    with middle_authority.open_stable_index() as (_middle, middle_index):
        correction_plan = build_registry_plan(middle_index)
    if preliminary.summary != correction_plan.summary:
        raise RuntimeError("semantic question plan drifted after atomic backfill")
    corrections = writer.record_semantic_question_corrections(
        equivalence_proposals=correction_plan.equivalences,
        lineage_proposals=correction_plan.lineages,
        review_artifact_hash=review_artifact_hash,
        operation_id=CORRECTION_OPERATION_ID,
    )
    after_authority = RunningJobAuthority(root, foundation_root=root)
    with after_authority.open_stable_index() as (after, after_index):
        verified = build_registry_plan(after_index)
        for kind, expected in (
            ("semantic-question-core", EXPECTED_CORE_COUNT),
            ("semantic-question-study", EXPECTED_STUDY_COUNT),
            ("semantic-question-equivalence", len(EQUIVALENCE_SPECS)),
            ("semantic-question-lineage", len(LINEAGE_SPECS)),
        ):
            observed = len(after_index.records_by_kind(kind))
            if observed != expected:
                raise RuntimeError(f"canonical {kind} count differs: {observed} != {expected}")
    if before["initiative"] != after["initiative"]:
        raise RuntimeError("semantic question correction changed Initiative state")
    for field in ("next_action", "scientific"):
        if before[field] != after[field]:
            raise RuntimeError(f"semantic question correction changed {field}")
    event_delta = int(not backfill.reused) + int(not corrections.reused)
    if after["revision"] != before["revision"] + event_delta:
        raise RuntimeError("semantic question correction revision differs")
    if verified.summary != correction_plan.summary:
        raise RuntimeError("canonical semantic question plan differs after correction")
    return {
        **verified.summary,
        "backfill_event_id": backfill.event_id,
        "backfill_reused": backfill.reused,
        "correction_event_id": corrections.event_id,
        "correction_reused": corrections.reused,
        "revision": after["revision"],
        "schema": "semantic_question_registry_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the backfill and historical correction events",
    )
    args = parser.parse_args()
    result = apply_registry(ROOT) if args.apply else plan_registry(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
