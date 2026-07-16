from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.semantic_question_registry import (
    SemanticQuestionRegistryError,
    SemanticQuestionRegistryIntegrityError,
    backfill_semantic_question_records,
    require_repeated_core_lineage,
    require_semantic_question_registry_activation,
    semantic_question_equivalence_record,
    semantic_question_lineage_record,
    semantic_question_lineage_resolution_records,
    semantic_question_prospective_equivalence_record,
    semantic_question_prospective_lineage_record,
    semantic_question_registry_activation_record,
    study_semantic_evidence,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.semantic_question import (
    SemanticQuestionCore,
    SemanticQuestionEquivalenceProposal,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.storage.index import IndexRecord


def question(*, suffix: str = "") -> dict[str, object]:
    return {
        "causal_question": (
            "Does a fixed causal event create stable utility beyond its control?"
            + suffix
        ),
        "changed_variables": ["feature", "trade"],
        "controlled_variables": ["cost", "risk"],
        "done_conditions": ["evaluate one fixed contrast"],
        "evidence_modes": ["causal_contrast", "cost_and_execution"],
    }


def record(
    kind: str,
    record_id: str,
    *,
    subject: str,
    status: str,
    payload: dict[str, object] | None = None,
    fingerprint: str | None = None,
    authority_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=record_id if fingerprint is None else fingerprint,
        payload={} if payload is None else payload,
        authority_sequence=authority_sequence,
    )


def study_open(
    study_id: str,
    declared_question: dict[str, object],
    sequence: int,
) -> IndexRecord:
    question_hash = canonical_digest(
        domain="study-question",
        payload=declared_question,
    )
    return record(
        "study-open",
        study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint="study-input:" + str(sequence),
        payload={
            "question": declared_question,
            "question_hash": question_hash,
        },
        authority_sequence=sequence,
    )


class FakeIndex:
    def __init__(self, records: tuple[IndexRecord, ...] = ()) -> None:
        self.records: dict[tuple[str, str], IndexRecord] = {
            (item.kind, item.record_id): item for item in records
        }

    def add(self, *records: IndexRecord) -> None:
        for item in records:
            self.records[(item.kind, item.record_id)] = item

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self.records.get((kind, record_id))

    def records_by_kind_prefix(
        self, kind: str, record_id_prefix: str
    ) -> tuple[IndexRecord, ...]:
        return tuple(
            item
            for (item_kind, item_id), item in sorted(self.records.items())
            if item_kind == kind and item_id.startswith(record_id_prefix)
        )

    def records_by_kind(self, kind: str) -> tuple[IndexRecord, ...]:
        return tuple(
            item for item in self.records.values() if item.kind == kind
        )

    def records_by_fingerprint(self, fingerprint: str) -> tuple[IndexRecord, ...]:
        return tuple(
            item
            for item in self.records.values()
            if item.fingerprint == fingerprint
        )

    def records_by_subject_status(
        self, subject: str, status: str
    ) -> tuple[IndexRecord, ...]:
        return tuple(
            item
            for item in self.records.values()
            if item.subject == subject and item.status == status
        )

    def records_by_payload_text(
        self, kind: str, lookup_name: str, value: str
    ) -> tuple[IndexRecord, ...]:
        return tuple(
            item
            for item in self.records.values()
            if item.kind == kind and item.payload.get(lookup_name) == value
        )

    def event_head(self, stream: str):
        events = tuple(
            item
            for item in self.records.values()
            if item.event_stream == stream and item.event_sequence is not None
        )
        if not events:
            return None
        latest = max(events, key=lambda item: item.event_sequence or 0)
        return SimpleNamespace(
            sequence=latest.event_sequence,
            record_kind=latest.kind,
            record_id=latest.record_id,
        )


def historical_pair(
    *,
    predecessor_question: dict[str, object] | None = None,
    successor_question: dict[str, object] | None = None,
) -> tuple[FakeIndex, IndexRecord, IndexRecord, tuple[str, ...]]:
    predecessor = study_open(
        "STU-0001", question() if predecessor_question is None else predecessor_question, 1
    )
    successor = study_open(
        "STU-0002", question() if successor_question is None else successor_question, 20
    )
    batch_a = "batch:" + "a" * 64
    batch_b = "batch:" + "b" * 64
    executable = "executable:" + "e" * 64
    job_a = "job:" + "a" * 64
    job_b = "job:" + "b" * 64
    predecessor_close = record(
        "study-close",
        "close-a",
        subject="Study:STU-0001",
        status="not_evaluable",
        payload={"outcome": "not_evaluable"},
    )
    successor_close = record(
        "study-close",
        "close-b",
        subject="Study:STU-0002",
        status="not_supported",
        payload={"outcome": "not_supported"},
    )
    diagnosis = record(
        "study-diagnosis",
        "diagnosis-a",
        subject="Study:STU-0001",
        status="engineering_gap",
        payload={"study_id": "STU-0001"},
    )
    pred_batch_open = record(
        "batch-open",
        batch_a,
        subject="Study:STU-0001",
        status="open",
    )
    succ_batch_open = record(
        "batch-open",
        batch_b,
        subject="Study:STU-0002",
        status="open",
    )
    pred_batch_close = record(
        "batch-close",
        "batch-close-a",
        subject=f"Batch:{batch_a}",
        status="engineering_failure",
        payload={"outcome": "engineering_failure"},
    )
    succ_batch_close = record(
        "batch-close",
        "batch-close-b",
        subject=f"Batch:{batch_b}",
        status="completed",
        payload={"outcome": "completed"},
    )
    pred_trial = record(
        "trial",
        executable,
        subject=f"Batch:{batch_a}",
        status="evaluated",
        payload={"study_id": "STU-0001"},
    )
    pred_job = record(
        "job-declared",
        job_a,
        subject=f"Job:{job_a}",
        status="declared",
        payload={
            "batch_id": batch_a,
            "study_id": "STU-0001",
            "spec": {"evidence_subject": {"kind": "Executable", "id": executable}},
        },
    )
    succ_job = record(
        "job-declared",
        job_b,
        subject=f"Job:{job_b}",
        status="declared",
        payload={
            "batch_id": batch_b,
            "study_id": "STU-0002",
            "spec": {"evidence_subject": {"kind": "Executable", "id": executable}},
        },
    )
    pred_completion = record(
        "job-completed",
        "completion-a",
        subject=f"Job:{job_a}",
        status="failed",
        payload={
            "failure": {"failure_kind": "engineering"},
            "scientific": None,
        },
    )
    succ_completion = record(
        "job-completed",
        "completion-b",
        subject=f"Job:{job_b}",
        status="failed",
        payload={
            "failure": {"failure_kind": "scientific_falsification"},
            "scientific": {
                "executable_id": executable,
                "scientific_eligible": True,
                "verdict": "failed",
            },
        },
    )
    index = FakeIndex(
        (
            predecessor,
            successor,
            predecessor_close,
            successor_close,
            diagnosis,
            pred_batch_open,
            succ_batch_open,
            pred_batch_close,
            succ_batch_close,
            pred_trial,
            pred_job,
            succ_job,
            pred_completion,
            succ_completion,
        )
    )
    index.add(*backfill_semantic_question_records((predecessor, successor)))
    basis = tuple(
        sorted(
            (
                "study-open:STU-0001",
                "study-open:STU-0002",
                "study-close:close-a",
                "study-close:close-b",
                "study-diagnosis:diagnosis-a",
                "batch-close:batch-close-a",
                "job-completed:completion-a",
                "job-completed:completion-b",
            )
        )
    )
    return index, predecessor, successor, basis


class SemanticQuestionRegistryTests(unittest.TestCase):
    def test_backfill_groups_exact_core_but_keeps_study_bindings(self) -> None:
        first = study_open("STU-0001", question(), 1)
        second = study_open("STU-0002", question(), 2)
        records = backfill_semantic_question_records((first, second))
        self.assertEqual(
            sum(item.kind == "semantic-question-core" for item in records), 1
        )
        self.assertEqual(
            sum(item.kind == "semantic-question-study" for item in records), 2
        )
        bindings = tuple(
            item for item in records if item.kind == "semantic-question-study"
        )
        self.assertNotEqual(bindings[0].record_id, bindings[1].record_id)
        self.assertEqual(
            bindings[0].payload["semantic_question_core_id"],
            bindings[1].payload["semantic_question_core_id"],
        )

    def test_backfill_rejects_question_hash_drift(self) -> None:
        opened = study_open("STU-0001", question(), 1)
        malformed = replace(
            opened,
            payload={**opened.payload, "question_hash": "0" * 64},
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryIntegrityError, "question hash"
        ):
            backfill_semantic_question_records((malformed,))

    def test_historical_engineering_reentry_preserves_zero_credit(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        core = SemanticQuestionCore.from_question_manifest(question())
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Repair the predecessor gap before scientific judgment.",
            basis_record_ids=basis,
        )
        projected = semantic_question_lineage_record(index, proposal)
        self.assertEqual(projected.status, "accepted")
        self.assertEqual(projected.payload["scientific_trial_delta"], 0)
        self.assertEqual(projected.payload["scientific_failure_delta"], 0)
        self.assertEqual(projected.payload["evidence_transfer_authority"], "none")
        self.assertEqual(
            projected.payload["exact_executable_overlap_ids"],
            ["executable:" + "e" * 64],
        )
        self.assertEqual(
            projected.payload["successor_scientific_completion_ids"],
            ["completion-b"],
        )
        index.add(projected)
        self.assertEqual(
            semantic_question_lineage_record(index, proposal),
            projected,
        )

    def test_distinct_core_reentry_requires_exact_explicit_equivalence(self) -> None:
        revised = question(suffix=" Fixed accounting is clarified.")
        index, predecessor, successor, basis = historical_pair(
            successor_question=revised
        )
        first = SemanticQuestionCore.from_question_manifest(question())
        second = SemanticQuestionCore.from_question_manifest(revised)
        equivalence = SemanticQuestionEquivalenceProposal(
            canonical_study_id=predecessor.record_id,
            equivalent_study_id=successor.record_id,
            canonical_core_id=first.identity,
            equivalent_core_id=second.identity,
            rationale="Expert review binds the same estimand after accounting clarification.",
            basis_record_ids=(
                "study-open:STU-0001",
                "study-open:STU-0002",
            ),
        )
        accepted = semantic_question_equivalence_record(index, equivalence)
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=first.identity,
            successor_core_id=second.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Corrected work resolves the predecessor engineering gap.",
            basis_record_ids=basis,
            equivalence_proposal_id=equivalence.identity,
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryError, "accepted equivalence"
        ):
            semantic_question_lineage_record(index, lineage)
        projected = semantic_question_lineage_record(
            index, lineage, equivalence_record=accepted
        )
        self.assertEqual(
            projected.payload["proposal"]["equivalence_proposal_id"],
            equivalence.identity,
        )

    def test_semantic_revision_conflicts_with_accepted_equivalence(self) -> None:
        revised = question(suffix=" Fixed accounting is clarified.")
        index, predecessor, successor, basis = historical_pair(
            successor_question=revised
        )
        first = SemanticQuestionCore.from_question_manifest(question())
        second = SemanticQuestionCore.from_question_manifest(revised)
        equivalence = SemanticQuestionEquivalenceProposal(
            canonical_study_id=predecessor.record_id,
            equivalent_study_id=successor.record_id,
            canonical_core_id=first.identity,
            equivalent_core_id=second.identity,
            rationale="Expert review accepts the two declared estimands as equivalent.",
            basis_record_ids=(
                "study-open:STU-0001",
                "study-open:STU-0002",
            ),
        )
        index.add(semantic_question_equivalence_record(index, equivalence))
        revision = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=first.identity,
            successor_core_id=second.identity,
            relation=SemanticQuestionRelation.SEMANTIC_REVISION,
            rationale="A revision cannot contradict accepted exact equivalence.",
            basis_record_ids=basis,
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryError, "conflicts with accepted"
        ):
            semantic_question_lineage_record(index, revision)

    def test_historical_lineage_requires_both_exact_study_closes(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        index.records.pop(("study-close", "close-b"))
        core = SemanticQuestionCore.from_question_manifest(question())
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.CONTINUATION,
            rationale="Historical correction requires a closed successor.",
            basis_record_ids=tuple(
                item for item in basis if item != "study-close:close-b"
            ),
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryError, "both exact Study closes"
        ):
            semantic_question_lineage_record(index, lineage)

    def test_independent_replication_rejects_exact_executable_reuse(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        predecessor_close = index.get("study-close", "close-a")
        predecessor_completion = index.get("job-completed", "completion-a")
        assert predecessor_close is not None
        assert predecessor_completion is not None
        index.add(
            replace(
                predecessor_close,
                status="supported",
                payload={"outcome": "supported"},
            ),
            replace(
                predecessor_completion,
                status="success",
                payload={
                    "failure": None,
                    "scientific": {
                        "executable_id": "executable:" + "e" * 64,
                        "scientific_eligible": True,
                        "verdict": "passed",
                    },
                },
            ),
        )
        core = SemanticQuestionCore.from_question_manifest(question())
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.INDEPENDENT_REPLICATION,
            rationale="An exact Executable cache reuse is not independent replication.",
            basis_record_ids=basis,
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryError, "cannot reuse an exact Executable"
        ):
            semantic_question_lineage_record(index, lineage)

    def test_activation_fingerprint_drift_fails_closed(self) -> None:
        activation = semantic_question_registry_activation_record(
            operation_id="activate-semantic-question-registry-v1",
            study_count=2,
            core_count=1,
        )
        index = FakeIndex((replace(activation, fingerprint="0" * 64),))
        with self.assertRaisesRegex(
            SemanticQuestionRegistryIntegrityError, "activation is malformed"
        ):
            require_semantic_question_registry_activation(index)

    def test_activation_rejects_silent_exact_question_reuse(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        core = SemanticQuestionCore.from_question_manifest(question())
        index.add(
            semantic_question_registry_activation_record(
                operation_id="activate-semantic-question-registry-v1",
                study_count=2,
                core_count=1,
            )
        )
        with self.assertRaisesRegex(
            SemanticQuestionRegistryError, "requires typed Study lineage"
        ):
            require_repeated_core_lineage(
                index,
                successor_study_id=successor.record_id,
                successor_core_id=core.identity,
                proposal=None,
            )
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="The successor repairs the exact predecessor question.",
            basis_record_ids=basis,
        )
        require_repeated_core_lineage(
            index,
            successor_study_id=successor.record_id,
            successor_core_id=core.identity,
            proposal=proposal,
        )

    def test_prospective_records_bind_only_durable_predecessor_evidence(self) -> None:
        historical, predecessor, successor, _basis = historical_pair(
            successor_question=question(suffix=" Accounting clarified.")
        )
        successor_keys = {
            key
            for key, item in historical.records.items()
            if item.subject in {"Study:STU-0002", "Batch:batch:" + "b" * 64}
            or item.payload.get("study_id") == "STU-0002"
            or item.subject == "Job:job:" + "b" * 64
        }
        for key in successor_keys:
            historical.records.pop(key)
        for key in tuple(historical.records):
            if key[0] == "semantic-question-study" and historical.records[key].payload.get(
                "study_id"
            ) == "STU-0002":
                historical.records.pop(key)
        first = SemanticQuestionCore.from_question_manifest(question())
        second = SemanticQuestionCore.from_question_manifest(
            question(suffix=" Accounting clarified.")
        )
        prospective_basis = (
            "batch-close:batch-close-a",
            "job-completed:completion-a",
            "study-diagnosis:diagnosis-a",
            "study-close:close-a",
            "study-open:STU-0001",
        )
        equivalence = SemanticQuestionEquivalenceProposal(
            canonical_study_id=predecessor.record_id,
            equivalent_study_id=successor.record_id,
            canonical_core_id=first.identity,
            equivalent_core_id=second.identity,
            rationale="Accounting wording preserves the exact estimand.",
            basis_record_ids=prospective_basis,
        )
        accepted = semantic_question_prospective_equivalence_record(
            historical, successor, equivalence
        )
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=first.identity,
            successor_core_id=second.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Open corrected work without transferring scientific credit.",
            basis_record_ids=prospective_basis,
            equivalence_proposal_id=equivalence.identity,
        )
        projected = semantic_question_prospective_lineage_record(
            historical,
            successor,
            lineage,
            equivalence_record=accepted,
        )
        self.assertEqual(projected.status, "declared")
        self.assertEqual(
            projected.payload["resolution_scope"],
            "prospective_pending_successor_evidence",
        )
        self.assertEqual(projected.payload["successor_scientific_completion_ids"], [])

    def test_evidence_projection_keeps_registration_and_execution_separate(self) -> None:
        index, _predecessor, _successor, _basis = historical_pair()
        evidence = study_semantic_evidence(index, "STU-0002")
        self.assertEqual(evidence.registered_executable_ids, ())
        self.assertEqual(
            evidence.executed_executable_ids, ("executable:" + "e" * 64,)
        )

    def test_successor_close_resolves_lineage_without_back_credit(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        core = SemanticQuestionCore.from_question_manifest(question())
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Resolve only the successor work after its exact close.",
            basis_record_ids=basis,
        )
        accepted = semantic_question_lineage_record(index, proposal)
        declared = replace(
            accepted,
            status="declared",
            payload={
                **accepted.payload,
                "resolution_scope": "prospective_pending_successor_evidence",
            },
        )
        index.add(
            replace(
                successor,
                payload={
                    **successor.payload,
                    "semantic_question_lineage_id": proposal.identity,
                },
            ),
            declared,
        )
        close_record = index.get("study-close", "close-b")
        assert close_record is not None
        resolutions = semantic_question_lineage_resolution_records(
            index, close_record
        )
        self.assertEqual(len(resolutions), 1)
        resolution = resolutions[0]
        self.assertEqual(resolution.status, "scientific_result_recorded")
        self.assertEqual(resolution.payload["scientific_trial_delta"], 0)
        self.assertEqual(resolution.payload["scientific_failure_delta"], 0)
        self.assertEqual(resolution.payload["claim_delta"], "none")
        self.assertEqual(
            resolution.payload["successor_scientific_completion_ids"],
            ["completion-b"],
        )

    def test_writer_backfill_then_correction_is_zero_credit_and_stable(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        for key in tuple(index.records):
            if key[0] in {
                "semantic-question-core",
                "semantic-question-study",
            }:
                index.records.pop(key)
        control = {
            "next_action": {"kind": "portfolio_decision"},
            "scientific": {
                "active_batch": None,
                "active_executable": None,
                "active_holdout_evaluation": None,
                "active_job": None,
                "active_release": None,
                "active_repair": None,
                "active_study": None,
                "claim": "none",
            },
        }
        writer = object.__new__(StateWriter)
        writer.engineering_fixture = True

        def commit(**kwargs: object):
            prepare = kwargs["prepare"]
            return prepare(control, index)  # type: ignore[operator]

        with patch.object(writer, "_commit", side_effect=commit):
            _body, projected, result = writer.backfill_semantic_question_registry(
                operation_id="semantic-registry-backfill-test-v1"
            )
        self.assertEqual(result["study_binding_count"], 2)
        self.assertEqual(result["core_count"], 1)
        self.assertEqual(result["trial_delta"], 0)
        index.add(*projected)

        core = SemanticQuestionCore.from_question_manifest(question())
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Record the repaired historical Study without new credit.",
            basis_record_ids=basis,
        )
        with patch.object(writer, "_commit", side_effect=commit):
            body, corrections, result = (
                writer.record_semantic_question_corrections(
                    equivalence_proposals=(),
                    lineage_proposals=(lineage,),
                    review_artifact_hash="a" * 64,
                    operation_id="semantic-registry-correction-test-v1",
                )
            )
        self.assertEqual(body["next_action"], control["next_action"])
        self.assertEqual(result["lineage_count"], 1)
        self.assertEqual(result["trial_delta"], 0)
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].payload["claim_delta"], "none")

    def test_writer_correction_binds_current_protocol_review_artifact(self) -> None:
        index, predecessor, successor, basis = historical_pair()
        index.add(
            *backfill_semantic_question_records((predecessor, successor)),
            semantic_question_registry_activation_record(
                operation_id="semantic-registry-backfill-test-v1",
                study_count=2,
                core_count=1,
            ),
            replace(
                record(
                    "research-protocol-activation",
                    "research-protocol:" + "f" * 64,
                    subject="ProjectGoal:OPERATING_DIRECTION.md",
                    status="active",
                    payload={
                        "audit_artifact_hash": "b" * 64,
                        "authority_manifest_digest": "c" * 64,
                    },
                ),
                event_stream="research-protocol:scientific",
                event_sequence=1,
            ),
        )
        control = {
            "authority": {"manifest_digest": "c" * 64},
            "next_action": {"kind": "portfolio_decision"},
            "scientific": {
                "active_batch": None,
                "active_executable": None,
                "active_holdout_evaluation": None,
                "active_job": None,
                "active_release": None,
                "active_repair": None,
                "active_study": None,
                "claim": "none",
            },
        }
        core = SemanticQuestionCore.from_question_manifest(question())
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id=predecessor.record_id,
            successor_study_id=successor.record_id,
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Bind correction to the exact current multi-lens review.",
            basis_record_ids=basis,
        )
        writer = object.__new__(StateWriter)
        writer.engineering_fixture = False
        writer.evidence = SimpleNamespace(verify=lambda _digest: None)

        def commit(**kwargs: object):
            prepare = kwargs["prepare"]
            return prepare(control, index)  # type: ignore[operator]

        with (
            patch.object(
                writer,
                "_require_study_close_delivery_guard",
                return_value=None,
            ),
            patch.object(writer, "_commit", side_effect=commit),
        ):
            with self.assertRaisesRegex(
                TransitionError, "differs from the active protocol"
            ):
                writer.record_semantic_question_corrections(
                    equivalence_proposals=(),
                    lineage_proposals=(lineage,),
                    review_artifact_hash="a" * 64,
                    operation_id="reject-unbound-semantic-review",
                )
            _body, corrections, result = (
                writer.record_semantic_question_corrections(
                    equivalence_proposals=(),
                    lineage_proposals=(lineage,),
                    review_artifact_hash="b" * 64,
                    operation_id="accept-bound-semantic-review",
                )
            )
        self.assertEqual(len(corrections), 1)
        self.assertEqual(result["review_artifact_hash"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
