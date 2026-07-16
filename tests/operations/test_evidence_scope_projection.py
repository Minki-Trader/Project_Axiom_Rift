from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.evidence_scope_projection import (
    effective_completion_evidence_scope,
)
from axiom_rift.operations.axis_disposition import (
    AxisDispositionEvidenceError,
    derive_axis_evidence_binding,
    required_axis_scientific_references,
)
from axiom_rift.operations.replay_projection import (
    prepare_audit_only_scope_overlay,
)
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.replay_obligation import (
    ReplayResolutionScope,
    ReplaySatisfaction,
)
from axiom_rift.research.axis_disposition import (
    AxisEvidenceKind,
    AxisEvidenceReference,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class EffectiveEvidenceScopeProjectionTests(unittest.TestCase):
    def test_audit_overlay_preserves_raw_completion_and_removes_all_credit(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                mission_id = "MIS-EFFECTIVE-SCOPE"
                study_id = "STU-EFFECTIVE-SCOPE"
                completion_id = "1" * 64
                job_id = "job:" + "2" * 64
                component = ComponentSpec(
                    display_name="effective scope fixture",
                    protocol="fixture.effective_scope.v1",
                    implementation="fixture.effective_scope.run.v1",
                    spec={"surface": "fixture"},
                )
                executable = ExecutableSpec(
                    display_name="effective scope executable",
                    components=(component,),
                    parameters={"profile": "fixture"},
                    data_contract="data:effective_scope_fixture",
                    split_contract="split:effective_scope_fixture",
                    clock_contract="clock:effective_scope_fixture",
                    cost_contract="cost:effective_scope_fixture",
                    engine_contract="engine:effective_scope_fixture",
                )
                executable_id = executable.identity
                axis_id = "axis-effective-scope"
                axis_identity = "axis:" + "a" * 64
                raw_scientific = {
                    "adjudication": {
                        "candidate_eligible": False,
                        "invalid_metrics": [],
                        "schema": "scientific_adjudication.v1",
                        "state": "unresolved",
                    },
                    "candidate_eligible": False,
                    "executed_evidence_modes": [
                        "causal_contrast",
                        "cost_and_execution",
                        "sensitivity_or_stress",
                    ],
                    "executable_id": executable_id,
                    "scientific_eligible": True,
                }
                completion = IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="success",
                    fingerprint="3" * 64,
                    payload={"job_id": job_id, "scientific": raw_scientific},
                )
                index.put_many(
                    (
                        IndexRecord(
                            kind="job-declared",
                            record_id=job_id,
                            subject=f"Job:{job_id}",
                            status="declared",
                            fingerprint="3" * 64,
                            payload={
                                "mission_id": mission_id,
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
                            kind="study-open",
                            record_id=study_id,
                            subject=f"Study:{study_id}",
                            status="open",
                            fingerprint="4" * 64,
                            payload={
                                "mission_id": mission_id,
                                "portfolio_axis_id": axis_id,
                                "portfolio_axis_identity": axis_identity,
                            },
                        ),
                        IndexRecord(
                            kind="trial",
                            record_id=executable_id,
                            subject="Batch:BAT-EFFECTIVE-SCOPE",
                            status="evaluated",
                            fingerprint=executable_id.removeprefix("executable:"),
                            payload={
                                "executable": executable.to_identity_payload(),
                                "mission_id": mission_id,
                                "portfolio_axis_id": axis_id,
                                "portfolio_axis_identity": axis_identity,
                                "study_id": study_id,
                            },
                        ),
                        completion,
                    )
                )
                raw = effective_completion_evidence_scope(index, completion)
                self.assertTrue(raw.scientific_eligible)
                self.assertEqual(raw.scientific_credit, 1)
                self.assertEqual(raw.economic_credit, 1)
                self.assertEqual(raw.candidate_credit, 0)
                self.assertEqual(raw.terminal_credit, 1)
                self.assertTrue(raw.negative_memory_authoritative)
                self.assertIsNone(raw.invalidation_record_id)
                reference = AxisEvidenceReference(
                    kind=AxisEvidenceKind.JOB_COMPLETION,
                    record_id=completion_id,
                )
                self.assertEqual(
                    derive_axis_evidence_binding(
                        index,
                        reference=reference,
                        mission_id=mission_id,
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                    ).evidence_modes,
                    tuple(raw_scientific["executed_evidence_modes"]),
                )
                self.assertEqual(
                    required_axis_scientific_references(
                        index,
                        mission_id=mission_id,
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                    ),
                    (reference,),
                )

                satisfactions = tuple(
                    ReplaySatisfaction(
                        obligation_id=(
                            "historical-replay-obligation:" + f"{ordinal:064x}"
                        ),
                        resolution_scope=ReplayResolutionScope.AUDIT_ONLY,
                        portfolio_decision_id="decision:" + "5" * 64,
                        replay_study_id=study_id,
                        replay_executable_id="executable:" + "6" * 64,
                        replay_study_close_record_id="7" * 64,
                        study_diagnosis_id="diagnosis:" + "8" * 64,
                        satisfied_criterion_ids=(f"criterion-{ordinal}",),
                        evidence_record_ids=(completion_id,),
                        remaining_scientific_condition=(
                            "prospective_paired_control_or_independent_family"
                        ),
                    )
                    for ordinal in (1, 2)
                )
                overlay = prepare_audit_only_scope_overlay(
                    index,
                    mission_id=mission_id,
                    satisfactions=satisfactions,
                )
                resolution_records = tuple(
                    IndexRecord(
                        kind="historical-replay-obligation-resolution",
                        record_id=item.identity,
                        subject=f"Mission:{mission_id}",
                        status="satisfied",
                        fingerprint=item.identity.removeprefix(
                            "historical-replay-satisfaction:"
                        ),
                        payload={
                            "obligation_id": item.obligation_id,
                            "resolution": item.to_identity_payload(),
                        },
                    )
                    for item in satisfactions
                )
                index.put_many((*resolution_records, overlay))

                effective = effective_completion_evidence_scope(index, completion)
                self.assertEqual(effective.evidence_modes, ("audit_integrity",))
                self.assertFalse(effective.scientific_eligible)
                self.assertFalse(effective.candidate_eligible)
                self.assertEqual(effective.scientific_credit, 0)
                self.assertEqual(effective.economic_credit, 0)
                self.assertEqual(effective.candidate_credit, 0)
                self.assertEqual(effective.terminal_credit, 0)
                self.assertFalse(effective.negative_memory_authoritative)
                self.assertEqual(effective.negative_memory_role, "diagnostic_only")
                self.assertEqual(effective.overlay_record_id, overlay.record_id)
                self.assertIsNone(effective.invalidation_record_id)
                with self.assertRaisesRegex(
                    AxisDispositionEvidenceError,
                    "lacks current rich scientific authority",
                ):
                    derive_axis_evidence_binding(
                        index,
                        reference=reference,
                        mission_id=mission_id,
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                    )
                self.assertEqual(
                    required_axis_scientific_references(
                        index,
                        mission_id=mission_id,
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                    ),
                    (),
                )
                stored = index.get("job-completed", completion_id)
                assert stored is not None
                self.assertEqual(stored.payload["scientific"], raw_scientific)


if __name__ == "__main__":
    unittest.main()
