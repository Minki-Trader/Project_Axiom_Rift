from __future__ import annotations

from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.axis_disposition import (
    AxisDispositionEvidenceError,
    derive_axis_evidence_binding,
    required_axis_scientific_references,
    required_axes_scientific_references,
)
from axiom_rift.operations.evidence_scope_projection import (
    evidence_scope_overlay_record,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.axis_disposition import (
    AxisDisposition,
    AxisDispositionAction,
    AxisDispositionError,
    AxisEvidenceKind,
    AxisEvidenceReference,
    AxisEvidenceState,
)
from axiom_rift.research.effective_evidence_scope import (
    HistoricalEvidenceScopeOverlay,
)
from axiom_rift.research.portfolio import PortfolioSnapshot
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXTURE_DELIVERY_CAPABILITY,
    FIXED_NOW,
    REPO_ROOT,
    PortfolioAxis,
    exhaustion_standard,
    initiative_objective,
    mission_goal,
    record_fixture_research_intake,
)


MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
)


def _digest(domain: str, tag: str) -> str:
    return canonical_digest(domain=domain, payload={"tag": tag})


class AxisDispositionModelTests(unittest.TestCase):
    def test_partial_positive_cannot_be_manufactured_as_retired(self) -> None:
        with self.assertRaises(AxisDispositionError):
            AxisDisposition(
                mission_id="MIS-DISPOSITION",
                portfolio_snapshot_id="portfolio:" + "a" * 64,
                axis_id="axis-a",
                axis_identity="axis:" + "b" * 64,
                evidence_state=AxisEvidenceState.PARTIAL_POSITIVE,
                action=AxisDispositionAction.RETIRE_WITH_REASON,
                evidence_references=(
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.JOB_COMPLETION,
                        record_id="c" * 64,
                    ),
                ),
                reason_codes=("caller_prune_request",),
                rationale="a partial positive cannot be rewritten as a prune",
                continuation_or_reopen_condition="replay on a registered family",
            )


class AxisDispositionWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.writer = StateWriter(
            self.temp.name,
            clock=lambda: FIXED_NOW,
            foundation_root=REPO_ROOT,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
        )
        self.writer.initialize_ready()
        self.mission_id = "MIS-DISPOSITION"
        self.writer.open_mission(
            mission_id=self.mission_id,
            goal=mission_goal("axis disposition"),
            operation_id="axis-disposition-mission",
        )
        intake = record_fixture_research_intake(
            self.writer,
            mission_id=self.mission_id,
            operation_id="axis-disposition-intake",
        )
        self.writer.open_initiative(
            initiative_id="INI-DISPOSITION",
            objective=initiative_objective("axis disposition"),
            operation_id="axis-disposition-initiative",
        )
        self.axes = (
            PortfolioAxis(
                axis_id="axis-disposition-a",
                causal_question="Does disposition axis A retain partial information?",
                mechanism_family="disposition-family-a",
            ),
            PortfolioAxis(
                axis_id="axis-disposition-b",
                causal_question="Does disposition axis B require valid replay?",
                mechanism_family="disposition-family-b",
            ),
            PortfolioAxis(
                axis_id="axis-disposition-c",
                causal_question="Is disposition axis C genuinely low information?",
                mechanism_family="disposition-family-c",
            ),
        )
        self.snapshot = PortfolioSnapshot(
            mission_id=self.mission_id,
            axes=self.axes,
            opportunity_cost_basis="retain non-negative forest information",
            research_intake_id=intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=self.snapshot,
            operation_id="axis-disposition-snapshot",
        )
        self.writer.close_initiative(
            outcome="continued_handoff",
            operation_id="axis-disposition-close-initiative",
        )

    def _job_records(
        self,
        *,
        axis_index: int,
        tag: str,
        state: str,
        candidate_eligible: bool = False,
        invalid_metrics: tuple[str, ...] = (),
    ) -> tuple[list[IndexRecord], str, str, str]:
        axis = self.axes[axis_index]
        executable_payload = {
            "schema": "axis_disposition_fixture_executable.v1",
            "source_contracts": [],
            "tag": tag,
        }
        executable_id = "executable:" + canonical_digest(
            domain="executable", payload=executable_payload
        )
        study_id = f"STU-DISPOSITION-{tag.upper()}"
        job_id = "job:" + _digest("axis-disposition-job", tag)
        completion_id = _digest("axis-disposition-completion", tag)
        verdict = (
            "passed"
            if state in {"frontier", "confirmed"}
            else "failed"
            if state == "contradicted"
            else "not_evaluable"
        )
        adjudication = {
            "candidate_eligible": candidate_eligible,
            "claims": [],
            "criteria": [],
            "evaluable": not invalid_metrics,
            "evidence_depth": "confirmation" if candidate_eligible else "discovery",
            "invalid_metrics": list(invalid_metrics),
            "legacy_verdict": verdict,
            "multiplicity": [],
            "schema": "scientific_adjudication.v1",
            "state": state,
        }
        records = [
            IndexRecord(
                kind="study-open",
                record_id=study_id,
                subject=f"Study:{study_id}",
                status="open",
                fingerprint=_digest("axis-disposition-study", tag),
                payload={
                    "mission_id": self.mission_id,
                    "portfolio_axis_id": axis.axis_id,
                    "portfolio_axis_identity": axis.identity,
                    "portfolio_snapshot_id": self.snapshot.identity,
                },
            ),
            IndexRecord(
                kind="trial",
                record_id=executable_id,
                subject=f"Batch:BAT-DISPOSITION-{tag.upper()}",
                status="evaluated",
                fingerprint=executable_id.removeprefix("executable:"),
                payload={
                    "executable": executable_payload,
                    "mission_id": self.mission_id,
                    "portfolio_axis_id": axis.axis_id,
                    "portfolio_axis_identity": axis.identity,
                    "portfolio_snapshot_id": self.snapshot.identity,
                    "study_id": study_id,
                },
            ),
            IndexRecord(
                kind="job-declared",
                record_id=job_id,
                subject=f"Job:{job_id}",
                status="declared",
                fingerprint=job_id.removeprefix("job:"),
                payload={
                    "mission_id": self.mission_id,
                    "study_id": study_id,
                    "spec": {
                        "evidence_subject": {
                            "kind": "Executable",
                            "id": executable_id,
                        }
                    },
                },
            ),
            IndexRecord(
                kind="job-completed",
                record_id=completion_id,
                subject=f"Job:{job_id}",
                status="success",
                fingerprint=job_id.removeprefix("job:"),
                payload={
                    "job_id": job_id,
                    "scientific": {
                        "adjudication": adjudication,
                        "candidate_eligible": candidate_eligible,
                        "evidence_depth": adjudication["evidence_depth"],
                        "executed_evidence_modes": list(MODES),
                        "executable_id": executable_id,
                        "scientific_eligible": True,
                        "verdict": verdict,
                    },
                },
            ),
        ]
        return records, completion_id, executable_id, study_id

    def _seed_forest_evidence(
        self,
        *,
        candidate_positive: bool = False,
    ) -> dict[str, object]:
        records: list[IndexRecord] = []
        partial, partial_completion, partial_executable, _ = self._job_records(
            axis_index=0,
            tag="partial",
            state="frontier" if candidate_positive else "partial_positive",
            candidate_eligible=candidate_positive,
        )
        records.extend(partial)
        partial_negative, partial_negative_completion, partial_negative_executable, partial_negative_study = self._job_records(
            axis_index=0,
            tag="partial-negative",
            state="contradicted",
        )
        records.extend(partial_negative)
        partial_negative_memory = "negative-memory:" + _digest(
            "axis-disposition-negative-memory", "partial-axis"
        )
        records.append(
            IndexRecord(
                kind="negative-memory",
                record_id=partial_negative_memory,
                subject=f"Executable:{partial_negative_executable}",
                status="durable",
                fingerprint=partial_negative_memory.removeprefix(
                    "negative-memory:"
                ),
                payload={
                    "evidence_references": [partial_negative_completion],
                    "executed_evidence_modes": list(MODES),
                    "mission_id": self.mission_id,
                    "portfolio_axis_id": self.axes[0].axis_id,
                    "portfolio_axis_identity": self.axes[0].identity,
                    "portfolio_snapshot_id": self.snapshot.identity,
                    "study_id": partial_negative_study,
                },
            )
        )

        historical_base, historical_completion, historical_executable, historical_study = (
            self._job_records(
                axis_index=1,
                tag="historical-invalid",
                state="unresolved",
            )
        )
        # The exact additive overlay, not the legacy coarse verdict, is the
        # terminal-relevant source for this axis.
        historical_id = "historical-adjudication:" + _digest(
            "axis-disposition-historical", "invalid"
        )
        historical_record = IndexRecord(
            kind="historical-scientific-adjudication",
            record_id=historical_id,
            subject=f"Study:{historical_study}",
            status="not_evaluable_qualification",
            fingerprint=historical_id.removeprefix("historical-adjudication:"),
            payload={
                "adjudication": {
                    "candidate_eligible": False,
                    "invalid_metrics": [],
                    "state": "unresolved",
                },
                "completion_record_id": historical_completion,
                "effective_state": "not_evaluable",
                "executable_id": historical_executable,
                "schema": "historical_scientific_adjudication.v2",
                "study_id": historical_study,
                "validity_overrides": [
                    {
                        "reason": "source_authority_invalidated",
                        "subject_id": "source:" + "e" * 64,
                        "evidence_record_id": (
                            "source-authority-invalidation:" + "f" * 64
                        ),
                    }
                ],
            },
            event_stream=f"historical-adjudication:{historical_completion}",
            event_sequence=1,
        )
        records.extend(historical_base)
        records.append(historical_record)

        negative_references: list[str] = []
        negative_completions: list[str] = []
        for ordinal in (1, 2):
            negative, completion_id, executable_id, study_id = self._job_records(
                axis_index=2,
                tag=f"negative-{ordinal}",
                state="contradicted",
            )
            records.extend(negative)
            memory_id = "negative-memory:" + _digest(
                "axis-disposition-negative-memory", str(ordinal)
            )
            records.append(
                IndexRecord(
                    kind="negative-memory",
                    record_id=memory_id,
                    subject=f"Executable:{executable_id}",
                    status="durable",
                    fingerprint=memory_id.removeprefix("negative-memory:"),
                    payload={
                        "evidence_references": [completion_id],
                        "executed_evidence_modes": list(MODES),
                        "mission_id": self.mission_id,
                        "portfolio_axis_id": self.axes[2].axis_id,
                        "portfolio_axis_identity": self.axes[2].identity,
                        "portfolio_snapshot_id": self.snapshot.identity,
                        "study_id": study_id,
                    },
                )
            )
            negative_references.append(memory_id)
            negative_completions.append(completion_id)

        def seed(current, _index):
            assert current is not None
            return self.writer._body(current), records, {"seeded": True}

        self.writer._commit(
            event_kind="axis_disposition_fixture_evidence_seeded",
            operation_id=(
                "axis-disposition-seed-candidate"
                if candidate_positive
                else "axis-disposition-seed"
            ),
            subject=f"Mission:{self.mission_id}",
            payload={"candidate_positive": candidate_positive},
            prepare=seed,
        )
        return {
            "historical": historical_id,
            "negative": tuple(negative_references),
            "negative_completions": tuple(negative_completions),
            "partial": partial_completion,
            "partial_executable": partial_executable,
            "partial_negative": partial_negative_completion,
            "partial_negative_memory": partial_negative_memory,
        }

    def _seed_candidate_stream(
        self,
        *,
        completion_id: str,
        executable_id: str,
        binds_completion: bool,
        tag: str,
    ) -> str:
        evidence_refs = [
            completion_id
            if binds_completion
            else _digest("axis-disposition-unbound-positive", tag)
        ]
        candidate_id = "candidate:" + canonical_digest(
            domain="mission-candidate",
            payload={
                "evidence_refs": sorted(evidence_refs),
                "executable_id": executable_id,
                "mission_id": self.mission_id,
            },
        )
        candidate = IndexRecord(
            kind="candidate",
            record_id=candidate_id,
            subject=f"Executable:{executable_id}",
            status="frozen",
            fingerprint=executable_id.removeprefix("executable:"),
            payload={
                "evidence_refs": evidence_refs,
                "executable": {"schema": "candidate_stream_fixture.v1"},
                "mission_id": self.mission_id,
                "scientific_eligible": True,
                "scheduler_eligible": False,
                "source_bindings": [],
            },
            event_stream=f"candidate:{executable_id}",
            event_sequence=1,
        )

        def seed_candidate(current, _index):
            assert current is not None
            return self.writer._body(current), [candidate], {"seeded": True}

        self.writer._commit(
            event_kind="axis_disposition_fixture_candidate_frozen",
            operation_id=f"axis-disposition-candidate-{tag}",
            subject=f"Executable:{executable_id}",
            payload={"candidate_id": candidate_id},
            prepare=seed_candidate,
        )
        reason = f"typed_fixture_disposition_{tag}"
        disposition_id = canonical_digest(
            domain="candidate-disposition",
            payload={
                "candidate_id": candidate_id,
                "disposition": "rejected",
                "reason": reason,
            },
        )
        disposition = IndexRecord(
            kind="candidate-disposition",
            record_id=disposition_id,
            subject=f"Executable:{executable_id}",
            status="rejected",
            fingerprint=executable_id.removeprefix("executable:"),
            payload={
                "candidate_id": candidate_id,
                "executable_id": executable_id,
                "mission_id": self.mission_id,
                "reason": reason,
            },
            event_stream=f"candidate:{executable_id}",
            event_sequence=2,
        )

        def seed_disposition(current, _index):
            assert current is not None
            return self.writer._body(current), [disposition], {"seeded": True}

        self.writer._commit(
            event_kind="axis_disposition_fixture_candidate_disposed",
            operation_id=f"axis-disposition-disposition-{tag}",
            subject=f"Executable:{executable_id}",
            payload={"candidate_disposition_id": disposition_id},
            prepare=seed_disposition,
        )
        return disposition_id

    def test_zero_credit_overlay_precedes_historical_adjudication(self) -> None:
        records, completion_id, executable_id, study_id = self._job_records(
            axis_index=1,
            tag="historical-zero-credit",
            state="unresolved",
        )
        valid_records, valid_completion_id, _valid_executable_id, _valid_study_id = (
            self._job_records(
                axis_index=1,
                tag="valid-after-zero-credit",
                state="confirmed",
            )
        )
        records.extend(valid_records)
        historical_id = "historical-adjudication:" + _digest(
            "axis-disposition-historical",
            "zero-credit",
        )
        records.append(
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=historical_id,
                subject=f"Study:{study_id}",
                status="not_evaluable_qualification",
                fingerprint=historical_id.removeprefix(
                    "historical-adjudication:"
                ),
                payload={
                    "adjudication": {
                        "candidate_eligible": False,
                        "invalid_metrics": [],
                        "state": "unresolved",
                    },
                    "completion_record_id": completion_id,
                    "effective_state": "not_evaluable",
                    "executable_id": executable_id,
                    "schema": "historical_scientific_adjudication.v2",
                    "study_id": study_id,
                    "validity_overrides": [],
                },
                event_stream=f"historical-adjudication:{completion_id}",
                event_sequence=1,
            )
        )
        replay_study_id = "STU-DISPOSITION-AUDIT-ONLY"
        replay_obligation_id = "historical-replay-obligation:" + _digest(
            "axis-disposition-replay-obligation",
            "zero-credit",
        )
        replay_resolution_id = "historical-replay-satisfaction:" + _digest(
            "axis-disposition-replay-satisfaction",
            "zero-credit",
        )
        records.extend(
            (
                IndexRecord(
                    kind="study-open",
                    record_id=replay_study_id,
                    subject=f"Study:{replay_study_id}",
                    status="open",
                    fingerprint=_digest(
                        "axis-disposition-replay-study",
                        "zero-credit",
                    ),
                    payload={"mission_id": self.mission_id},
                ),
                IndexRecord(
                    kind="historical-replay-obligation-resolution",
                    record_id=replay_resolution_id,
                    subject=f"Mission:{self.mission_id}",
                    status="satisfied",
                    fingerprint=replay_resolution_id.removeprefix(
                        "historical-replay-satisfaction:"
                    ),
                    payload={
                        "obligation_id": replay_obligation_id,
                        "resolution": {
                            "evidence_record_ids": [completion_id],
                            "obligation_id": replay_obligation_id,
                            "replay_study_id": replay_study_id,
                            "resolution_scope": "audit_only",
                        },
                    },
                ),
            )
        )
        overlay = HistoricalEvidenceScopeOverlay(
            completion_record_id=completion_id,
            governing_mission_id=self.mission_id,
            replay_study_id=replay_study_id,
            replay_obligation_ids=(replay_obligation_id,),
            replay_resolution_ids=(replay_resolution_id,),
        )
        records.append(evidence_scope_overlay_record(overlay))

        def seed(current, _index):
            assert current is not None
            return self.writer._body(current), records, {"seeded": True}

        self.writer._commit(
            event_kind="axis_disposition_zero_credit_fixture_seeded",
            operation_id="axis-disposition-zero-credit-seed",
            subject=f"Mission:{self.mission_id}",
            payload={"completion_record_id": completion_id},
            prepare=seed,
        )

        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(
                required_axis_scientific_references(
                    index,
                    mission_id=self.mission_id,
                    axis_id=self.axes[1].axis_id,
                    axis_identity=self.axes[1].identity,
                ),
                (
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.JOB_COMPLETION,
                        record_id=valid_completion_id,
                    ),
                ),
            )
            with self.assertRaisesRegex(
                AxisDispositionEvidenceError,
                "zero-credit completion",
            ):
                derive_axis_evidence_binding(
                    index,
                    reference=AxisEvidenceReference(
                        kind=AxisEvidenceKind.HISTORICAL_ADJUDICATION,
                        record_id=historical_id,
                    ),
                    mission_id=self.mission_id,
                    axis_id=self.axes[1].axis_id,
                    axis_identity=self.axes[1].identity,
                )

    def _dispositions(self, evidence: dict[str, object]) -> tuple[AxisDisposition, ...]:
        negative = evidence["negative"]
        negative_completions = evidence["negative_completions"]
        assert isinstance(negative, tuple)
        assert isinstance(negative_completions, tuple)
        return (
            AxisDisposition(
                mission_id=self.mission_id,
                portfolio_snapshot_id=self.snapshot.identity,
                axis_id=self.axes[0].axis_id,
                axis_identity=self.axes[0].identity,
                evidence_state=AxisEvidenceState.PARTIAL_POSITIVE,
                action=AxisDispositionAction.PRESERVE,
                evidence_references=(
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.JOB_COMPLETION,
                        record_id=str(evidence["partial"]),
                    ),
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.JOB_COMPLETION,
                        record_id=str(evidence["partial_negative"]),
                    ),
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                        record_id=str(evidence["partial_negative_memory"]),
                    ),
                ),
                reason_codes=("claim_scoped_partial_positive",),
                rationale="retain supported components without candidate authority",
                continuation_or_reopen_condition=(
                    "replay the exact concurrent family before confirmation"
                ),
            ),
            AxisDisposition(
                mission_id=self.mission_id,
                portfolio_snapshot_id=self.snapshot.identity,
                axis_id=self.axes[1].axis_id,
                axis_identity=self.axes[1].identity,
                evidence_state=AxisEvidenceState.INVALID,
                action=AxisDispositionAction.REPLAY,
                evidence_references=(
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.HISTORICAL_ADJUDICATION,
                        record_id=str(evidence["historical"]),
                    ),
                ),
                reason_codes=("source_authority_invalidated",),
                rationale="invalid source authority cannot support a negative claim",
                continuation_or_reopen_condition=(
                    "replay only after a new eligible source contract"
                ),
            ),
            AxisDisposition(
                mission_id=self.mission_id,
                portfolio_snapshot_id=self.snapshot.identity,
                axis_id=self.axes[2].axis_id,
                axis_identity=self.axes[2].identity,
                evidence_state=AxisEvidenceState.LOW_INFORMATION,
                action=AxisDispositionAction.RETIRE_WITH_REASON,
                evidence_references=(
                    *(
                        AxisEvidenceReference(
                            kind=AxisEvidenceKind.JOB_COMPLETION,
                            record_id=record_id,
                        )
                        for record_id in negative_completions
                    ),
                    *(
                        AxisEvidenceReference(
                            kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                            record_id=record_id,
                        )
                        for record_id in negative
                    ),
                ),
                reason_codes=("preregistered_negative_depth_satisfied",),
                rationale="two distinct exact surfaces exhausted this mechanism",
                continuation_or_reopen_condition=(
                    "reopen only with a materially new mechanism or information state"
                ),
            ),
        )

    def _candidate_positive_disposition(
        self, evidence: dict[str, object]
    ) -> AxisDisposition:
        return AxisDisposition(
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot.identity,
            axis_id=self.axes[0].axis_id,
            axis_identity=self.axes[0].identity,
            evidence_state=AxisEvidenceState.FRONTIER,
            action=AxisDispositionAction.PRESERVE,
            evidence_references=(
                AxisEvidenceReference(
                    kind=AxisEvidenceKind.JOB_COMPLETION,
                    record_id=str(evidence["partial"]),
                ),
                AxisEvidenceReference(
                    kind=AxisEvidenceKind.JOB_COMPLETION,
                    record_id=str(evidence["partial_negative"]),
                ),
                AxisEvidenceReference(
                    kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                    record_id=str(evidence["partial_negative_memory"]),
                ),
            ),
            reason_codes=("resolved_candidate_positive_preserved",),
            rationale=(
                "candidate authority was resolved without erasing the positive axis"
            ),
            continuation_or_reopen_condition=(
                "carry the exact positive evidence and candidate disposition forward"
            ),
        )

    @staticmethod
    def _frontier(disposition: AxisDisposition) -> tuple[dict[str, str], ...]:
        return (
            {"kind": "axis-disposition", "record_id": disposition.identity},
            *(reference.manifest() for reference in disposition.evidence_references),
        )

    def test_batched_scientific_reference_audit_matches_single_axis_projection(
        self,
    ) -> None:
        self._seed_forest_evidence()
        targets = tuple(
            (self.mission_id, axis.axis_id, axis.identity)
            for axis in self.axes
        )
        with LocalIndex(self.writer.index_path) as index:
            scanned_kinds: list[str] = []
            original_records_by_kind = index.records_by_kind

            def counted_records_by_kind(kind: str):
                scanned_kinds.append(kind)
                return original_records_by_kind(kind)

            with patch.object(
                index,
                "records_by_kind",
                side_effect=counted_records_by_kind,
            ):
                batched = required_axes_scientific_references(
                    index,
                    targets=targets,
                )
            self.assertEqual(scanned_kinds, ["job-completed"])
            self.assertEqual(
                batched,
                {
                    target: required_axis_scientific_references(
                        index,
                        mission_id=target[0],
                        axis_id=target[1],
                        axis_identity=target[2],
                    )
                    for target in targets
                },
            )

    def test_batched_scientific_reference_audit_remains_globally_fail_closed(
        self,
    ) -> None:
        malformed, _completion_id, _executable_id, _study_id = self._job_records(
            axis_index=2,
            tag="malformed-global-completion",
            state="contradicted",
        )
        malformed = [
            record for record in malformed if record.kind != "job-declared"
        ]

        def seed(current, _index):
            assert current is not None
            return self.writer._body(current), malformed, {"seeded": True}

        self.writer._commit(
            event_kind="axis_disposition_malformed_completion_seeded",
            operation_id="axis-disposition-malformed-completion-seed",
            subject=f"Mission:{self.mission_id}",
            payload={"axis_id": self.axes[2].axis_id},
            prepare=seed,
        )
        target = (
            self.mission_id,
            self.axes[0].axis_id,
            self.axes[0].identity,
        )
        with LocalIndex(self.writer.index_path) as index, self.assertRaisesRegex(
            AxisDispositionEvidenceError,
            "lacks its Job declaration",
        ):
            required_axes_scientific_references(index, targets=(target,))

    def test_multi_axis_writer_boundaries_call_one_batched_reference_audit(
        self,
    ) -> None:
        evidence = self._seed_forest_evidence()
        dispositions = self._dispositions(evidence)
        batch_calls: list[tuple[tuple[str, str, str], ...]] = []

        def counted_batch(index: LocalIndex, *, targets):
            batch_calls.append(targets)
            return required_axes_scientific_references(
                index,
                targets=targets,
            )

        with patch(
            "axiom_rift.operations.axis_disposition."
            "required_axes_scientific_references",
            side_effect=counted_batch,
        ):
            self.writer.record_axis_dispositions(
                dispositions=dispositions,
                operation_id="record-batched-axis-dispositions",
            )
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(len(batch_calls[0]), len(self.axes))

        batch_calls.clear()
        with patch(
            "axiom_rift.operations.axis_disposition."
            "required_axes_scientific_references",
            side_effect=counted_batch,
        ):
            self.writer.accept_exhaustion_audit(
                frontiers={
                    item.axis_id: self._frontier(item) for item in dispositions
                },
                diversity_basis="three exact axes remain explicit",
                opportunity_cost_audit="retire only the exact negative frontier",
                operation_id="accept-batched-axis-exhaustion",
            )
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(len(batch_calls[0]), len(self.axes))

    def test_mixed_forest_dispositions_support_honest_mission_terminal(self) -> None:
        evidence = self._seed_forest_evidence()
        dispositions = self._dispositions(evidence)
        omitted_partial = AxisDisposition(
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot.identity,
            axis_id=self.axes[0].axis_id,
            axis_identity=self.axes[0].identity,
            evidence_state=AxisEvidenceState.LOW_INFORMATION,
            action=AxisDispositionAction.RETIRE_WITH_REASON,
            evidence_references=(
                AxisEvidenceReference(
                    kind=AxisEvidenceKind.JOB_COMPLETION,
                    record_id=str(evidence["partial_negative"]),
                ),
                AxisEvidenceReference(
                    kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                    record_id=str(evidence["partial_negative_memory"]),
                ),
            ),
            reason_codes=("selected_negative_only",),
            rationale="a selected negative cannot erase the same axis partial positive",
            continuation_or_reopen_condition="include every latest scientific result",
        )
        with self.assertRaisesRegex(TransitionError, "omits or supersedes"):
            self.writer.record_axis_dispositions(
                dispositions=(omitted_partial,),
                operation_id="reject-omitted-axis-partial-positive",
            )
        forged_state = AxisDisposition(
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot.identity,
            axis_id=self.axes[0].axis_id,
            axis_identity=self.axes[0].identity,
            evidence_state=AxisEvidenceState.UNRESOLVED,
            action=AxisDispositionAction.REPLAY,
            evidence_references=dispositions[0].evidence_references,
            reason_codes=("caller_state_is_not_authority",),
            rationale="the Writer must derive the state from exact evidence",
            continuation_or_reopen_condition="use the actual partial-positive state",
        )
        with self.assertRaisesRegex(TransitionError, "Writer-derived"):
            self.writer.record_axis_dispositions(
                dispositions=(forged_state,),
                operation_id="reject-forged-axis-state",
            )
        with patch.object(
            self.writer,
            "_effective_axis_resolutions",
            side_effect=lambda _index, axes: tuple(
                SimpleNamespace(terminal_eligible=False) for _axis in axes
            ),
        ), self.assertRaisesRegex(TransitionError, "scope-blocked"):
            self.writer.record_axis_dispositions(
                dispositions=dispositions,
                operation_id="reject-effective-axis-blocked-dispositions",
            )
        before = self.writer.read_control()
        recorded = self.writer.record_axis_dispositions(
            dispositions=dispositions,
            operation_id="record-axis-dispositions",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(after["next_action"], before["next_action"])
        self.assertEqual(recorded.result["candidate_delta"], 0)
        self.assertEqual(recorded.result["trial_delta"], 0)

        frontier = {
            item.axis_id: self._frontier(item) for item in dispositions
        }
        with patch.object(
            self.writer,
            "_mission_effective_axis_blockers",
            return_value=(SimpleNamespace(obligation_id="blocked"),),
        ), self.assertRaisesRegex(TransitionError, "unresolved replay"):
            self.writer.accept_exhaustion_audit(
                frontiers=frontier,
                diversity_basis="three layers and three mechanisms remain explicit",
                opportunity_cost_audit=(
                    "carry partial and invalid axes forward while retiring only exact negatives"
                ),
                operation_id="reject-effective-axis-blocked-exhaustion",
            )
        accepted = self.writer.accept_exhaustion_audit(
            frontiers=frontier,
            diversity_basis="three layers and three mechanisms remain explicit",
            opportunity_cost_audit=(
                "carry partial and invalid axes forward while retiring only exact negatives"
            ),
            operation_id="accept-mixed-axis-exhaustion",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "close_mission")
        with LocalIndex(self.writer.index_path) as index:
            audit = index.get(
                "exhaustion-audit", accepted.result["basis_record_id"]
            )
        assert audit is not None
        self.assertEqual(
            audit.payload["scientifically_exhausted_axis_ids"],
            [self.axes[2].axis_id],
        )
        self.assertEqual(
            audit.payload["carried_forward_axis_ids"],
            [self.axes[0].axis_id, self.axes[1].axis_id],
        )
        self.assertEqual(audit.payload["unique_negative_executable_count"], 2)
        with patch.object(
            self.writer,
            "_mission_effective_axis_blockers",
            return_value=(SimpleNamespace(obligation_id="blocked"),),
        ), self.assertRaisesRegex(TransitionError, "scope-blocked"):
            self.writer.close_mission(
                outcome="closed_no_candidate",
                basis_record_id=accepted.result["basis_record_id"],
                operation_id="reject-effective-axis-blocked-terminal",
            )
        closed = self.writer.close_mission(
            outcome="closed_no_candidate",
            basis_record_id=accepted.result["basis_record_id"],
            operation_id="close-mixed-axis-negative-mission",
        )
        terminal = self.writer.read_control()
        assert terminal is not None
        self.assertFalse(closed.result["project_goal_complete"])
        self.assertEqual(terminal["next_action"]["kind"], "await_root_goal")
        self.assertEqual(
            terminal["next_action"]["predecessor_basis_record_id"],
            accepted.result["basis_record_id"],
        )
        self.assertEqual(
            terminal["next_action"]["predecessor_mission_id"], self.mission_id
        )

    def test_writer_rejects_forged_state_and_candidate_eligible_disposition(self) -> None:
        evidence = self._seed_forest_evidence(candidate_positive=True)
        candidate_disposition = self._candidate_positive_disposition(evidence)
        with self.assertRaisesRegex(TransitionError, "candidate-eligible"):
            self.writer.record_axis_dispositions(
                dispositions=(candidate_disposition,),
                operation_id="reject-candidate-axis-disposition",
            )

    def test_unbound_candidate_disposition_stream_cannot_resolve_positive(self) -> None:
        evidence = self._seed_forest_evidence(candidate_positive=True)
        self._seed_candidate_stream(
            completion_id=str(evidence["partial"]),
            executable_id=str(evidence["partial_executable"]),
            binds_completion=False,
            tag="unbound",
        )
        with self.assertRaisesRegex(TransitionError, "candidate-eligible"):
            self.writer.record_axis_dispositions(
                dispositions=(self._candidate_positive_disposition(evidence),),
                operation_id="reject-unbound-candidate-stream",
            )

    def test_resolved_candidate_positive_can_be_preserved_before_terminal(self) -> None:
        evidence = self._seed_forest_evidence(candidate_positive=True)
        candidate_disposition_id = self._seed_candidate_stream(
            completion_id=str(evidence["partial"]),
            executable_id=str(evidence["partial_executable"]),
            binds_completion=True,
            tag="resolved",
        )
        base = self._dispositions(evidence)
        dispositions = (
            self._candidate_positive_disposition(evidence),
            base[1],
            base[2],
        )
        recorded = self.writer.record_axis_dispositions(
            dispositions=dispositions,
            operation_id="record-resolved-candidate-axis-dispositions",
        )
        with LocalIndex(self.writer.index_path) as index:
            positive = index.get(
                "axis-disposition",
                recorded.result["axis_disposition_record_ids"][0],
            )
        assert positive is not None
        self.assertEqual(
            positive.payload["resolved_candidate_authority"],
            [
                {
                    "candidate_disposition_record_id": candidate_disposition_id,
                    "completion_record_id": evidence["partial"],
                }
            ],
        )
        accepted = self.writer.accept_exhaustion_audit(
            frontiers={
                item.axis_id: self._frontier(item) for item in dispositions
            },
            diversity_basis="resolved candidate forest remains fully explicit",
            opportunity_cost_audit=(
                "carry the resolved positive and invalid axes into the successor"
            ),
            operation_id="accept-resolved-candidate-exhaustion",
        )
        self.assertTrue(accepted.result["basis_record_id"])

    def test_exhaustion_rejects_carrying_every_axis_forward(self) -> None:
        evidence = self._seed_forest_evidence()
        base = self._dispositions(evidence)
        carried_negative = AxisDisposition(
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot.identity,
            axis_id=self.axes[2].axis_id,
            axis_identity=self.axes[2].identity,
            evidence_state=AxisEvidenceState.LOW_INFORMATION,
            action=AxisDispositionAction.REPLAY,
            evidence_references=base[2].evidence_references,
            reason_codes=("no_axis_retired",),
            rationale="retain even the fully negative axis for another replay",
            continuation_or_reopen_condition="run another bounded replay",
        )
        dispositions = (base[0], base[1], carried_negative)
        self.writer.record_axis_dispositions(
            dispositions=dispositions,
            operation_id="record-all-carried-axis-dispositions",
        )
        with self.assertRaisesRegex(
            TransitionError, "at least one genuinely scientifically exhausted"
        ):
            self.writer.accept_exhaustion_audit(
                frontiers={
                    item.axis_id: self._frontier(item) for item in dispositions
                },
                diversity_basis="all axes were carried forward",
                opportunity_cost_audit="zero retirement cannot close a Mission",
                operation_id="reject-zero-exhaustion-terminal",
            )

    def test_terminal_entry_points_require_study_close_delivery_guard(self) -> None:
        for name, invoke in (
            (
                "exhaustion",
                lambda: self.writer.accept_exhaustion_audit(
                    frontiers={},
                    diversity_basis="guard fixture",
                    opportunity_cost_audit="guard fixture",
                    operation_id="guard-exhaustion",
                ),
            ),
            (
                "close",
                lambda: self.writer.close_mission(
                    outcome="closed_no_candidate",
                    basis_record_id="missing",
                    operation_id="guard-close-mission",
                ),
            ),
        ):
            with self.subTest(name=name), patch.object(
                self.writer,
                "_require_study_close_delivery_guard",
                side_effect=TransitionError("guard blocked terminal"),
            ):
                with self.assertRaisesRegex(
                    TransitionError, "guard blocked terminal"
                ):
                    invoke()

    def test_exhaustion_rejects_frontier_that_omits_exact_disposition_evidence(self) -> None:
        evidence = self._seed_forest_evidence()
        dispositions = self._dispositions(evidence)
        self.writer.record_axis_dispositions(
            dispositions=dispositions,
            operation_id="record-axis-dispositions-forged-frontier",
        )
        frontiers = {
            item.axis_id: self._frontier(item) for item in dispositions
        }
        frontiers[self.axes[0].axis_id] = (
            {
                "kind": "axis-disposition",
                "record_id": dispositions[0].identity,
            },
        )
        with self.assertRaisesRegex(TransitionError, "exact axis disposition"):
            self.writer.accept_exhaustion_audit(
                frontiers=frontiers,
                diversity_basis="forged frontier fixture",
                opportunity_cost_audit="omitted evidence must fail closed",
                operation_id="reject-incomplete-axis-frontier",
            )


if __name__ == "__main__":
    unittest.main()
