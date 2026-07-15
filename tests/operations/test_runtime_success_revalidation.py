from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.sources import (
    RuntimeSourceDriftObservation,
    SourceEligibility,
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
)
from axiom_rift.runtime.guards import EvidenceDepth, REQUIRED_PARITY
from axiom_rift.storage.index import EventHead, IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    REPO_ROOT,
    mission_goal,
    runtime_job_spec,
    source_contract,
)


MISSION_ID = "MIS-RUNTIME-SUCCESS-REVALIDATION"


class RuntimeSuccessRevalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id=MISSION_ID,
            goal=mission_goal("runtime success revalidation"),
            operation_id="runtime-success-mission",
        )

    def _candidate(self, tag: str):
        contract = source_contract()
        registered = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=registered,
            receipt=None,
            operation_id=f"{tag}-source-context",
        )
        historical_artifact = self.writer.evidence.finalize(
            f"{tag} historical source audit".encode("ascii")
        )
        historical_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(historical_artifact.sha256,),
            facts={
                "acquisition_observed": True,
                "content_hash_verified": True,
                "coverage_audited": True,
                "event_time_audited": True,
                "first_availability_audited": True,
                "gaps_audited": True,
                "information_complete_at_audited": True,
                "revision_or_vintage_audited": True,
            },
        )
        audited = registered.complete_historical_audit(
            historical_receipt.identity
        )
        self.writer.record_source_eligibility(
            eligibility=audited,
            receipt=historical_receipt,
            operation_id=f"{tag}-source-audit",
        )
        runtime_artifact = self.writer.evidence.finalize(
            f"{tag} runtime source proof".encode("ascii")
        )
        runtime_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(runtime_artifact.sha256,),
            facts={
                "complete_or_closed": True,
                "fresh": True,
                "historical_runtime_field_parity": True,
                "latency_ms": 5,
                "local_realtime_retrieval": True,
                "synchronized": True,
            },
        )
        eligible = audited.prove_runtime_availability(runtime_receipt.identity)
        self.writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime_receipt,
            operation_id=f"{tag}-source-runtime",
        )
        component = ComponentSpec(
            display_name=f"{tag} source component",
            protocol="feature.engineering_fixture.v1",
            implementation=f"fixture.component.{tag}",
            spec={"tag": tag},
            semantic_dependencies=(contract.source_contract_id,),
        )
        executable = ExecutableSpec(
            display_name=f"{tag} runtime executable",
            components=(component,),
            parameters={"tag": tag},
            data_contract="data:engineering_fixture",
            split_contract="split:engineering_fixture",
            clock_contract="clock:completed_bar_fixture",
            cost_contract="cost:engineering_fixture",
            engine_contract="engine:engineering_fixture",
            source_contracts=(contract.source_contract_id,),
        )
        frozen = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-runtime-candidate-evidence",),
            operation_id=f"{tag}-candidate-freeze",
        )
        return contract, eligible, executable, frozen

    def _start_runtime_job(self, tag: str):
        contract, eligible, executable, frozen = self._candidate(tag)
        output_name = f"evidence/{tag}-runtime"
        spec = runtime_job_spec(
            writer=self.writer,
            executable_id=executable.identity,
            depth=EvidenceDepth.EXECUTION_PROOF,
            output_name=output_name,
            artifact_roles=("native_execution_report",),
        )
        declared = self.writer.declare_job(
            spec=spec,
            operation_id=f"{tag}-job-declare",
        )
        job_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-job-permit",
        )
        runtime_permit = self.writer.issue_permit(
            kind=PermitKind.RUNTIME,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=executable.identity,
            input_hash=declared.result["job_hash"],
            actions=("run_execution_proof",),
            scope=(
                f"candidate:{frozen.result['candidate_id']}",
                "depth:execution_proof",
                f"executable:{executable.identity}",
                f"job:{declared.result['job_id']}",
                f"source:{contract.source_contract_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=False,
            operation_id=f"{tag}-runtime-permit",
        )
        self.writer.start_job(
            permit=job_permit,
            runtime_permit=runtime_permit,
            operation_id=f"{tag}-job-start",
        )
        entered = self.writer.validate_runtime_entry(
            permit=runtime_permit,
            executable_id=executable.identity,
            input_hash=declared.result["job_hash"],
            action="run_execution_proof",
            depth=EvidenceDepth.EXECUTION_PROOF,
            operation_id=f"{tag}-runtime-entry",
        )
        return {
            "contract": contract,
            "declared": declared,
            "eligible": eligible,
            "entered": entered,
            "executable": executable,
            "frozen": frozen,
            "output_name": output_name,
            "runtime_permit": runtime_permit,
            "spec": spec,
        }

    def _success_outputs(self, context: dict[str, object]) -> dict[str, str]:
        spec = context["spec"]
        declared = context["declared"]
        executable = context["executable"]
        frozen = context["frozen"]
        runtime_permit = context["runtime_permit"]
        output_name = context["output_name"]
        assert isinstance(spec, dict)
        binding = spec["runtime_binding"]
        assert isinstance(binding, dict)
        assert isinstance(output_name, str)
        claims = sorted(REQUIRED_PARITY)
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "claims": claims,
                    "schema": "engineering_runtime_measurement.v1",
                }
            )
        )
        outputs = {
            f"{output_name}-measurement": measurement.sha256,
        }
        role_outputs = binding["artifact_roles"]
        assert isinstance(role_outputs, dict)
        for role, role_output in role_outputs.items():
            artifact = self.writer.evidence.finalize(
                canonical_bytes(
                    {"role": role, "schema": "engineering_runtime_role.v1"}
                )
            )
            outputs[role_output] = artifact.sha256
        manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "action": "run_execution_proof",
                    "candidate_id": frozen.result["candidate_id"],
                    "evidence_depth": "execution_proof",
                    "executable_id": executable.identity,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "mission_id": MISSION_ID,
                    "observations": [
                        {
                            "claim_id": claim,
                            "measurement_artifact_hash": measurement.sha256,
                            "status": "caller_reported",
                        }
                        for claim in claims
                    ],
                    "runtime_permit_id": runtime_permit.permit_id,
                    "schema": "runtime_job_evidence.v1",
                }
            )
        )
        outputs[binding["result_manifest_output"]] = manifest.sha256
        return outputs

    def _complete_source_gap(
        self,
        *,
        context: dict[str, object],
        source_state_record_id: str,
        evidence_hash: str,
        operation_id: str,
    ):
        contract = context["contract"]
        spec = context["spec"]
        assert isinstance(spec, dict)
        return self.writer.complete_job(
            outcome="not_evaluable",
            output_manifest={},
            failure={
                "failure_kind": "runtime_source_ineligibility",
                "interrupted_action": spec["callable_identity"],
                "minimum_reproduction_evidence": [evidence_hash],
                "resume_action": spec["resume_action"],
                "root_cause": "runtime source was not eligible at completion",
                "source_contract_id": contract.source_contract_id,
                "source_state_record_id": source_state_record_id,
            },
            operation_id=operation_id,
        )

    def test_ordinary_exact_runtime_success_is_accepted(self) -> None:
        context = self._start_runtime_job("ordinary-success")
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest=self._success_outputs(context),
            operation_id="ordinary-success-complete",
        )
        with LocalIndex(self.writer.index_path) as index:
            record = index.get(
                "job-completed", completed.result["completion_record_id"]
            )
        assert record is not None
        rows = record.payload["runtime"]["source_snapshot_rows"]
        self.assertEqual(
            [row["source_contract_id"] for row in rows],
            [context["contract"].source_contract_id],
        )

    def test_ttl_expired_in_flight_runtime_success_is_rejected(self) -> None:
        context = self._start_runtime_job("ttl-expired")
        outputs = self._success_outputs(context)
        self.writer.clock = lambda: "2026-07-11T00:02:00Z"
        with self.assertRaisesRegex(TransitionError, "runtime provenance"):
            self.writer.complete_job(
                outcome="success",
                output_manifest=outputs,
                operation_id="reject-ttl-expired-success",
            )
        contract = context["contract"]
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
        assert source_head is not None
        evidence = self.writer.evidence.finalize(
            b"runtime source TTL expired before completion"
        )
        completed = self._complete_source_gap(
            context=context,
            source_state_record_id=source_head.record_id,
            evidence_hash=evidence.sha256,
            operation_id="complete-ttl-expired-source-gap",
        )
        self.assertEqual(completed.result["outcome"], "not_evaluable")

    def test_suspended_drift_cannot_be_completed_as_success(self) -> None:
        context = self._start_runtime_job("suspended-drift")
        outputs = self._success_outputs(context)
        contract = context["contract"]
        control = self.writer.read_control()
        assert control is not None
        active_job = control["scientific"]["active_job"]
        assert isinstance(active_job, dict)
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
        assert source_head is not None
        facts = {
            "changed_surface": "runtime_availability",
            "dependent_action": "fail_closed",
            "observed_change": "source suspended during runtime execution",
        }
        observation = RuntimeSourceDriftObservation(
            candidate_id=context["frozen"].result["candidate_id"],
            executable_id=context["executable"].identity,
            facts=facts,
            job_hash=context["declared"].result["job_hash"],
            job_id=context["declared"].result["job_id"],
            job_start_record_id=active_job["start_record_id"],
            observed_at_utc=FIXED_NOW,
            prior_source_receipt_id=(
                context["eligible"].evidence_receipt_id
            ),
            prior_source_state_record_id=source_head.record_id,
            producer_record_id=context["entered"].result[
                "runtime_entry_record_id"
            ],
            source_contract_id=contract.source_contract_id,
        )
        observation_artifact = self.writer.evidence.finalize(
            observation.to_bytes()
        )
        drift_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id=context["entered"].result[
                "runtime_entry_record_id"
            ],
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(observation_artifact.sha256,),
            facts=facts,
        )
        suspended = context["eligible"].suspend(
            receipt_id=drift_receipt.identity,
            reason="runtime source suspended in flight",
        )
        self.writer.record_source_eligibility(
            eligibility=suspended,
            receipt=drift_receipt,
            operation_id="record-in-flight-runtime-suspension",
        )
        with self.assertRaisesRegex(
            TransitionError, "normal running-Job direction"
        ):
            self.writer.complete_job(
                outcome="success",
                output_manifest=outputs,
                operation_id="reject-suspended-runtime-success",
            )
        with LocalIndex(self.writer.index_path) as index:
            suspended_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
        assert suspended_head is not None
        completed = self._complete_source_gap(
            context=context,
            source_state_record_id=suspended_head.record_id,
            evidence_hash=observation_artifact.sha256,
            operation_id="complete-suspended-runtime-gap",
        )
        self.assertEqual(completed.result["outcome"], "not_evaluable")

    def test_changed_source_receipt_and_head_are_rejected(self) -> None:
        context = self._start_runtime_job("changed-source-head")
        outputs = self._success_outputs(context)
        contract = context["contract"]
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
            source = index.get("source-state", source_head.record_id)
        assert source_head is not None
        assert source is not None
        changed_receipt_id = "source-receipt:" + canonical_digest(
            domain="changed-runtime-source-receipt",
            payload={"source_contract_id": contract.source_contract_id},
        )
        changed_state_id = canonical_digest(
            domain="changed-runtime-source-state",
            payload={"source_contract_id": contract.source_contract_id},
        )
        changed_source = replace(
            source,
            record_id=changed_state_id,
            payload={
                **source.payload,
                "evidence_receipt_id": changed_receipt_id,
            },
            event_sequence=source_head.sequence + 2,
        )
        changed_head = EventHead(
            stream=source_head.stream,
            sequence=source_head.sequence + 2,
            record_kind="source-state",
            record_id=changed_state_id,
            fingerprint=source_head.fingerprint,
        )
        original_require = self.writer._require_runtime_source
        original_event_head = LocalIndex.event_head

        def require_changed_source(
            index: LocalIndex,
            source_id: str,
            **kwargs: object,
        ) -> IndexRecord:
            if source_id == contract.source_contract_id:
                return changed_source
            return original_require(index, source_id, **kwargs)

        def changed_event_head(index: LocalIndex, stream: str):
            if stream == f"source:{contract.source_contract_id}":
                return changed_head
            return original_event_head(index, stream)

        with (
            patch.object(
                self.writer,
                "_require_runtime_source",
                side_effect=require_changed_source,
            ),
            patch.object(LocalIndex, "event_head", new=changed_event_head),
            self.assertRaisesRegex(
                TransitionError, "source snapshot changed after declaration"
            ),
        ):
            self.writer.complete_job(
                outcome="success",
                output_manifest=outputs,
                operation_id="reject-changed-source-head-success",
            )


if __name__ == "__main__":
    unittest.main()
