from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.operations.runtime_source_readiness import (
    _require_state,
    validate_completion_receipt_reuse,
)
from axiom_rift.research.sources import (
    SourceContract,
    SourceContractError,
    SourceEligibility,
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
    SourceType,
    recertify_source,
)
from axiom_rift.runtime.guards import (
    EvidenceDepth,
    REQUIRED_CASES,
    REQUIRED_PARITY,
    REQUIRED_RELEASE_ARTIFACT_ROLES,
)
from axiom_rift.runtime.source_lifecycle_coverage import (
    derive_source_lifecycle_coverage,
)
from axiom_rift.storage.index import LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    REPO_ROOT,
    executable_spec,
    mission_goal,
    runtime_job_spec,
    source_contract,
)


class RuntimeSourceReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = "2026-07-11T00:00:00Z"
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: self.now,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id="MIS-SOURCE-READINESS",
            goal=mission_goal("runtime source readiness reuse"),
            operation_id="source-readiness-mission",
        )
        self.contract = source_contract()
        self.eligible, self.r1 = self._qualify_source(self.contract)
        base = executable_spec("source-readiness")
        component = base.components[0]
        source_component = ComponentSpec(
            display_name=component.display_name,
            protocol=component.protocol,
            implementation=component.implementation,
            spec=component.specification(),
            semantic_dependencies=(self.contract.source_contract_id,),
        )
        second_source_component = ComponentSpec(
            display_name="second source-dependent fixture sleeve",
            protocol="feature.second_source_fixture.v1",
            implementation="tests.second_source_fixture",
            spec={"fixture": "second-dependent"},
            semantic_dependencies=(self.contract.source_contract_id,),
        )
        self.executable = ExecutableSpec(
            display_name=base.display_name,
            components=(source_component, second_source_component),
            parameters=base.parameter_values(),
            data_contract=base.data_contract,
            split_contract=base.split_contract,
            clock_contract=base.clock_contract,
            cost_contract=base.cost_contract,
            engine_contract=base.engine_contract,
            source_contracts=(self.contract.source_contract_id,),
        )
        frozen = self.writer.freeze_candidate(
            executable=self.executable,
            evidence_refs=("engineering-candidate-evidence",),
            operation_id="source-readiness-candidate",
        )
        self.executable_id = frozen.result["executable_id"]
        self.candidate_id = frozen.result["candidate_id"]

    def test_runtime_numeric_authority_rejects_bool(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence must be"):
            _require_state(
                None,
                source_contract_id=self.contract.source_contract_id,
                sequence=True,  # type: ignore[arg-type]
                expected_contract={},
            )
        with self.assertRaisesRegex(ValueError, "authority sequences"):
            validate_completion_receipt_reuse(
                index=None,  # type: ignore[arg-type]
                source_contract_id=self.contract.source_contract_id,
                candidate_mapping_identity="mapping",
                completion_receipt_ids=(),
                completion_source_snapshot={},
                current_state=None,  # type: ignore[arg-type]
                engine_entry_authority_sequence=True,  # type: ignore[arg-type]
                completion_authority_sequence=1,
                engine_entry_occurred_at_utc=self.now,
                completion_occurred_at_utc=self.now,
                verify_artifact=lambda _identity: None,
            )
        with self.assertRaisesRegex(SourceContractError, "latency_ms"):
            self._receipt(
                transition=(
                    SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF
                ),
                tag="bool-latency",
                facts={
                    "complete_or_closed": True,
                    "fresh": True,
                    "historical_runtime_field_parity": True,
                    "latency_ms": True,
                    "local_realtime_retrieval": True,
                    "synchronized": True,
                },
            )

    def _receipt(
        self,
        *,
        transition: SourceTransitionEvidence,
        tag: str,
        facts: dict[str, object],
        source_contract_id: str | None = None,
    ) -> SourceEligibilityReceipt:
        artifact = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "observed_at_utc": self.now,
                    "schema": "runtime_source_readiness_fixture.v1",
                    "tag": tag,
                }
            )
        )
        return SourceEligibilityReceipt(
            source_contract_id=(
                self.contract.source_contract_id
                if source_contract_id is None
                else source_contract_id
            ),
            evidence=transition,
            producer_completion_id="engineering-fixture",
            observed_at_utc=self.now,
            artifact_hashes=(artifact.sha256,),
            facts=facts,
        )

    def _qualify_source(
        self,
        contract: SourceContract,
    ) -> tuple[SourceEligibility, SourceEligibilityReceipt]:
        context = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id="source-readiness-register",
        )
        historical = self._receipt(
            transition=SourceTransitionEvidence.HISTORICAL_AUDIT,
            tag="historical-audit",
            source_contract_id=contract.source_contract_id,
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
        audited = context.complete_historical_audit(historical.identity)
        self.writer.record_source_eligibility(
            eligibility=audited,
            receipt=historical,
            operation_id="source-readiness-audit",
        )
        runtime = self._receipt(
            transition=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            tag="runtime-r1",
            source_contract_id=contract.source_contract_id,
            facts={
                "complete_or_closed": True,
                "fresh": True,
                "historical_runtime_field_parity": True,
                "latency_ms": 1,
                "local_realtime_retrieval": True,
                "synchronized": True,
            },
        )
        eligible = audited.prove_runtime_availability(runtime.identity)
        self.writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime,
            operation_id="source-readiness-r1",
        )
        return eligible, runtime

    def _recertify(
        self,
        *,
        changed_surface: str,
        drift_at_utc: str = "2026-07-11T00:00:30Z",
        recertified_at_utc: str = "2026-07-11T00:00:31Z",
        cycle: str = "r2",
    ) -> tuple[SourceEligibility, SourceEligibilityReceipt]:
        self.now = drift_at_utc
        drift = self._receipt(
            transition=SourceTransitionEvidence.DRIFT,
            tag=f"drift-{changed_surface}-{cycle}",
            facts={
                "changed_surface": changed_surface,
                "dependent_action": "fail_closed",
                "observed_change": f"fixture {changed_surface} changed",
            },
        )
        suspended = self.eligible.suspend(
            receipt_id=drift.identity,
            reason=f"fixture {changed_surface} drift",
        )
        self.writer.record_source_eligibility(
            eligibility=suspended,
            receipt=drift,
            operation_id=(
                f"source-readiness-suspend-{changed_surface}-{cycle}"
            ),
        )
        self.now = recertified_at_utc
        r2 = self._receipt(
            transition=SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            tag=f"recertify-{changed_surface}-{cycle}",
            facts={
                "mapping_parity": True,
                "schema_field_clock_parity": True,
                "semantic_equivalence": True,
            },
        )
        restored = recertify_source(
            suspended,
            proposed_contract=self.contract,
            receipt_id=r2.identity,
        ).eligibility
        self.writer.record_source_eligibility(
            eligibility=restored,
            receipt=r2,
            operation_id=f"source-readiness-{cycle}-{changed_surface}",
        )
        self.eligible = restored
        return restored, r2

    def _run_runtime_job(
        self,
        *,
        depth: EvidenceDepth,
        tag: str,
        roles: tuple[str, ...],
        prior_role_hashes: dict[str, str],
        planned_source_lifecycle_coverage_ids: tuple[str, ...] | None = None,
        unscoped_source_lifecycle: bool = False,
    ) -> tuple[str, dict[str, str]]:
        output_name = f"evidence/{tag}"
        spec = runtime_job_spec(
            writer=self.writer,
            executable_id=self.executable_id,
            depth=depth,
            output_name=output_name,
            artifact_roles=roles,
        )
        binding = spec["runtime_binding"]
        assert isinstance(binding, dict)
        if planned_source_lifecycle_coverage_ids is not None:
            binding["planned_source_lifecycle_coverage_ids"] = sorted(
                planned_source_lifecycle_coverage_ids
            )
        declared = self.writer.declare_job(
            spec=spec,
            operation_id=f"declare-{tag}",
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
            operation_id=f"job-permit-{tag}",
        )
        action = (
            "run_execution_proof"
            if depth is EvidenceDepth.EXECUTION_PROOF
            else "materialize"
        )
        runtime_permit = self.writer.issue_permit(
            kind=PermitKind.RUNTIME,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=self.executable_id,
            input_hash=declared.result["job_hash"],
            actions=(action,),
            scope=(
                f"candidate:{self.candidate_id}",
                f"depth:{depth.value}",
                f"executable:{self.executable_id}",
                f"job:{declared.result['job_id']}",
                f"source:{self.contract.source_contract_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=False,
            operation_id=f"runtime-permit-{tag}",
        )
        self.writer.start_job(
            permit=job_permit,
            runtime_permit=runtime_permit,
            operation_id=f"start-{tag}",
        )
        entry = self.writer.validate_runtime_entry(
            permit=runtime_permit,
            executable_id=self.executable_id,
            input_hash=declared.result["job_hash"],
            action=action,
            depth=depth,
            operation_id=f"entry-{tag}",
        )
        claims = (
            sorted(REQUIRED_PARITY)
            if depth is EvidenceDepth.EXECUTION_PROOF
            else sorted(REQUIRED_CASES)
        )
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "claims": claims,
                    "schema": "engineering_runtime_measurement.v1",
                }
            )
        )
        role_outputs = binding["artifact_roles"]
        assert isinstance(role_outputs, dict)
        role_hashes = dict(prior_role_hashes)
        output_manifest = {
            f"{output_name}-measurement": measurement.sha256,
        }
        for role, role_output in role_outputs.items():
            if role == "local_handoff_manifest":
                continue
            artifact = self.writer.evidence.finalize(
                canonical_bytes(
                    {
                        "role": role,
                        "schema": "engineering_runtime_role.v1",
                    }
                )
            )
            output_manifest[role_output] = artifact.sha256
            role_hashes[role] = artifact.sha256
        if "local_handoff_manifest" in role_outputs:
            control = self.writer.read_control()
            assert control is not None
            handoff = self.writer.evidence.finalize(
                canonical_bytes(
                    {
                        "artifact_roles": dict(sorted(role_hashes.items())),
                        "authority_manifest_digest": control["authority"][
                            "manifest_digest"
                        ],
                        "candidate_id": self.candidate_id,
                        "executable_id": self.executable_id,
                        "mission_id": "MIS-SOURCE-READINESS",
                        "schema": "axiom_local_handoff.v1",
                        "source_receipt_ids": entry.result[
                            "current_source_receipts"
                        ],
                    }
                )
            )
            output_manifest[role_outputs["local_handoff_manifest"]] = (
                handoff.sha256
            )
            role_hashes["local_handoff_manifest"] = handoff.sha256
        result = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "action": action,
                    "candidate_id": self.candidate_id,
                    "evidence_depth": depth.value,
                    "executable_id": self.executable_id,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "mission_id": "MIS-SOURCE-READINESS",
                    "observations": [
                        {
                            "claim_id": claim,
                            "measurement_artifact_hash": measurement.sha256,
                            **(
                                {
                                    "source_lifecycle_coverage_id": row[
                                        "coverage_id"
                                    ]
                                }
                                if row is not None
                                and not unscoped_source_lifecycle
                                else {}
                            ),
                            "status": "caller_reported",
                        }
                        for claim in claims
                        for row in (
                            [
                                candidate_row
                                for candidate_row in (
                                    derive_source_lifecycle_coverage(
                                        self.executable.to_identity_payload()
                                    )
                                )
                                if candidate_row["materialization_case"]
                                == claim
                                and candidate_row["coverage_id"]
                                in binding[
                                    "planned_source_lifecycle_coverage_ids"
                                ]
                            ]
                            if claim
                            in {
                                "source_interruption",
                                "stale_or_missing_input",
                            }
                            and not unscoped_source_lifecycle
                            else [None]
                        )
                    ],
                    "runtime_permit_id": runtime_permit.permit_id,
                    "schema": "runtime_job_evidence.v1",
                }
            )
        )
        output_manifest[binding["result_manifest_output"]] = result.sha256
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest=output_manifest,
            operation_id=f"complete-{tag}",
        )
        return completed.result["completion_record_id"], role_hashes

    def _source_lifecycle_rows(self) -> tuple[dict[str, object], ...]:
        return derive_source_lifecycle_coverage(
            self.executable.to_identity_payload()
        )

    def _mixed_receipt_completions(
        self,
        *,
        changed_surface: str,
    ) -> tuple[tuple[str, str], SourceEligibilityReceipt]:
        execution_roles = ("native_execution_report", "parity_report")
        execution, execution_hashes = self._run_runtime_job(
            depth=EvidenceDepth.EXECUTION_PROOF,
            tag=f"execution-{changed_surface}",
            roles=execution_roles,
            prior_role_hashes={},
        )
        _, r2 = self._recertify(changed_surface=changed_surface)
        materialization_roles = tuple(
            sorted(REQUIRED_RELEASE_ARTIFACT_ROLES - set(execution_roles))
        )
        materialization, _ = self._run_runtime_job(
            depth=EvidenceDepth.MATERIALIZATION,
            tag=f"materialization-{changed_surface}",
            roles=materialization_roles,
            prior_role_hashes=execution_hashes,
        )
        return (execution, materialization), r2

    def test_release_reuses_r1_success_with_fresh_same_semantics_r2(self) -> None:
        completions, r2 = self._mixed_receipt_completions(
            changed_surface="runtime_eligibility_receipt_age"
        )
        basis = self.writer.validate_release_basis_fixture(
            executable_id=self.executable_id,
            candidate_id=self.candidate_id,
            completion_record_ids=completions,
        )
        self.assertEqual(basis["source_receipt_ids"], [r2.identity])
        lifecycle = basis["source_lifecycle_coverage"]
        self.assertEqual(
            lifecycle["schema"],
            "release_source_lifecycle_coverage.v1",
        )
        self.assertEqual(
            lifecycle["satisfied_coverage_ids"],
            sorted(
                row["coverage_id"]
                for row in lifecycle["required_rows"]
            ),
        )
        readiness = basis["source_readiness"]
        self.assertEqual(readiness["schema"], "release_source_readiness.v1")
        self.assertEqual(readiness["current"][0]["receipt_id"], r2.identity)
        self.assertEqual(
            [
                item["sources"][0]["disposition"]
                for item in readiness["completion_uses"]
            ],
            ["unchanged_success_reused", "exact_current_receipt"],
        )
        _, r3 = self._recertify(
            changed_surface="runtime_eligibility_receipt_age",
            drift_at_utc="2026-07-11T00:00:45Z",
            recertified_at_utc="2026-07-11T00:00:46Z",
            cycle="r3",
        )
        r3_basis = self.writer.validate_release_basis_fixture(
            executable_id=self.executable_id,
            candidate_id=self.candidate_id,
            completion_record_ids=completions,
        )
        self.assertEqual(r3_basis["source_receipt_ids"], [r3.identity])
        self.assertEqual(
            [
                item["sources"][0]["disposition"]
                for item in r3_basis["source_readiness"]["completion_uses"]
            ],
            ["unchanged_success_reused", "unchanged_success_reused"],
        )
        self.now = "2026-07-11T00:02:00Z"
        with self.assertRaisesRegex(TransitionError, "runtime provenance"):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=completions,
            )

    def test_one_global_lifecycle_claim_cannot_cover_the_matrix(self) -> None:
        with self.assertRaisesRegex(
            TransitionError,
            "lacks its exact coverage row",
        ):
            self._run_runtime_job(
                depth=EvidenceDepth.MATERIALIZATION,
                tag="unscoped-source-lifecycle",
                roles=("materialization_report",),
                prior_role_hashes={},
                unscoped_source_lifecycle=True,
            )

    def test_release_requires_the_union_of_exact_lifecycle_rows(self) -> None:
        rows = self._source_lifecycle_rows()
        component_ids = sorted(
            {str(row["dependent_component_id"]) for row in rows}
        )
        self.assertEqual(len(component_ids), 2)
        first_ids = tuple(
            sorted(
                str(row["coverage_id"])
                for row in rows
                if row["dependent_component_id"] == component_ids[0]
            )
        )
        second_ids = tuple(
            sorted(
                str(row["coverage_id"])
                for row in rows
                if row["dependent_component_id"] == component_ids[1]
            )
        )
        execution_roles = ("native_execution_report", "parity_report")
        execution, hashes = self._run_runtime_job(
            depth=EvidenceDepth.EXECUTION_PROOF,
            tag="matrix-union-execution",
            roles=execution_roles,
            prior_role_hashes={},
        )
        materialization_roles = sorted(
            REQUIRED_RELEASE_ARTIFACT_ROLES - set(execution_roles)
        )
        first_role = next(
            role
            for role in materialization_roles
            if role != "local_handoff_manifest"
        )
        first, hashes = self._run_runtime_job(
            depth=EvidenceDepth.MATERIALIZATION,
            tag="matrix-union-first",
            roles=(first_role,),
            prior_role_hashes=hashes,
            planned_source_lifecycle_coverage_ids=first_ids,
        )
        with self.assertRaisesRegex(
            TransitionError,
            "source_lifecycle=.*source-lifecycle-coverage:",
        ):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=(execution, first),
            )
        second_roles = tuple(
            role for role in materialization_roles if role != first_role
        )
        second, _ = self._run_runtime_job(
            depth=EvidenceDepth.MATERIALIZATION,
            tag="matrix-union-second",
            roles=second_roles,
            prior_role_hashes=hashes,
            planned_source_lifecycle_coverage_ids=second_ids,
        )
        basis = self.writer.validate_release_basis_fixture(
            executable_id=self.executable_id,
            candidate_id=self.candidate_id,
            completion_record_ids=(execution, first, second),
        )
        self.assertEqual(
            basis["source_lifecycle_coverage"][
                "satisfied_coverage_ids"
            ],
            sorted((*first_ids, *second_ids)),
        )

    def test_mapping_drift_invalidates_only_the_old_completion(self) -> None:
        completions, _ = self._mixed_receipt_completions(
            changed_surface="mapping"
        )
        with self.assertRaisesRegex(
            TransitionError,
            "mapping_drift_invalidates_completion",
        ):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=completions,
            )
        with self.assertRaisesRegex(TransitionError, "coverage is incomplete"):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=(completions[1],),
            )

    def test_build_drift_cannot_reuse_old_runtime_evidence(self) -> None:
        completions, _ = self._mixed_receipt_completions(
            changed_surface="terminal_build"
        )
        with self.assertRaisesRegex(
            TransitionError,
            "build_drift_invalidates_completion",
        ):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=completions,
            )

    def test_cross_source_snapshot_swap_fails_before_release_coverage(self) -> None:
        completion_id, _ = self._run_runtime_job(
            depth=EvidenceDepth.EXECUTION_PROOF,
            tag="cross-source-swap",
            roles=("native_execution_report", "parity_report"),
            prior_role_hashes={},
        )
        with LocalIndex(self.writer.index_path) as index:
            completion = index.get("job-completed", completion_id)
        assert completion is not None
        runtime = dict(completion.payload["runtime"])
        rows = [dict(row) for row in runtime["source_snapshot_rows"]]
        rows[0]["source_contract_id"] = "source:" + "0" * 64
        runtime["source_snapshot_rows"] = rows
        swapped = replace(
            completion,
            payload={**completion.payload, "runtime": runtime},
        )
        original_get = LocalIndex.get

        def swapped_get(index: LocalIndex, kind: str, record_id: str):
            if kind == "job-completed" and record_id == completion_id:
                return swapped
            return original_get(index, kind, record_id)

        with (
            patch.object(LocalIndex, "get", new=swapped_get),
            self.assertRaisesRegex(
                TransitionError,
                "runtime provenance|source snapshot rows|engine-entry provenance",
            ),
        ):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=(completion_id,),
            )

    def test_semantic_change_leaves_old_candidate_source_ineligible(self) -> None:
        execution_roles = ("native_execution_report", "parity_report")
        execution, hashes = self._run_runtime_job(
            depth=EvidenceDepth.EXECUTION_PROOF,
            tag="execution-semantic-change",
            roles=execution_roles,
            prior_role_hashes={},
        )
        materialization, _ = self._run_runtime_job(
            depth=EvidenceDepth.MATERIALIZATION,
            tag="materialization-semantic-change",
            roles=tuple(
                sorted(REQUIRED_RELEASE_ARTIFACT_ROLES - set(execution_roles))
            ),
            prior_role_hashes=hashes,
        )
        self.now = "2026-07-11T00:00:30Z"
        drift = self._receipt(
            transition=SourceTransitionEvidence.DRIFT,
            tag="semantic-change",
            facts={
                "changed_surface": "source_semantics",
                "dependent_action": "fail_closed",
                "observed_change": "runtime symbol semantics changed",
            },
        )
        suspended = self.eligible.suspend(
            receipt_id=drift.identity,
            reason="source semantics changed",
        )
        self.writer.record_source_eligibility(
            eligibility=suspended,
            receipt=drift,
            operation_id="source-readiness-semantic-suspend",
        )
        changed_contract = SourceContract(
            display_name="changed semantic source",
            canonical_instrument=self.contract.canonical_instrument,
            runtime_identifier="SYN.CHANGED",
            source_type=SourceType.BAR,
            instrument_semantics=self.contract.instrument(),
            mapping_semantics={
                "mapping_rule": "changed_runtime_symbol",
                "runtime_symbol": "SYN.CHANGED",
            },
            schema_semantics=self.contract.schema(),
            field_semantics=self.contract.fields(),
            clock_semantics=self.contract.clock(),
            availability_semantics=self.contract.availability(),
        )
        replacement = recertify_source(
            suspended,
            proposed_contract=changed_contract,
            receipt_id="source-receipt:" + "f" * 64,
        )
        self.assertFalse(replacement.identity_preserved)
        self.writer.record_source_eligibility(
            eligibility=replacement.eligibility,
            receipt=None,
            operation_id="source-readiness-register-semantic-replacement",
        )
        with self.assertRaisesRegex(TransitionError, "runtime provenance"):
            self.writer.validate_release_basis_fixture(
                executable_id=self.executable_id,
                candidate_id=self.candidate_id,
                completion_record_ids=(execution, materialization),
            )


if __name__ == "__main__":
    unittest.main()
