from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts import run_project_goal_audit_v2_p1_replay as subject
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.strict_operation_chain import (
    OperationStep,
    StrictOperationChainError,
    inspect_operation_prefix,
    stage_bounds,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.implementation_closure import (
    require_job_implementation_closure,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class _FakeIndex:
    records: dict[str, object] = {}
    by_kind: dict[tuple[str, str], object] = {}

    def __init__(self, _path: object = None) -> None:
        pass

    @classmethod
    def open_read_only(cls, path: object):
        return cls(path)

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def records_by_kind(self, kind: str):
        if kind == "operation":
            return tuple(self.records.values())
        return tuple(
            record
            for (record_kind, _), record in self.by_kind.items()
            if record_kind == kind
        )

    def records_by_kind_prefix(self, kind: str, record_id_prefix: str):
        if kind != "operation":
            return ()
        return tuple(
            record
            for record_id, record in sorted(self.records.items())
            if record_id.startswith(record_id_prefix)
        )

    def get(self, kind: str, record_id: str):
        if kind == "operation":
            return self.records.get(record_id)
        return self.by_kind.get((kind, record_id))


class _FakeJournal:
    def __init__(self, events: dict[int, dict[str, object]]) -> None:
        self.events = events

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ):
        event = self.events[offset]
        if (
            event["sequence"] != expected_sequence
            or event["event_id"] != expected_event_id
        ):
            raise AssertionError("fake Journal authority differs")
        return event


def _completion(*, state: str, incomplete: bool = False) -> IndexRecord:
    criteria = []
    for position, definition in enumerate(subject.ANALOG_REPLAY_CRITERIA):
        item = dict(definition)
        comparison = "failed" if position == 0 else "passed"
        item.update(
            {
                "comparison_state": comparison,
                "scientific_state": (
                    "diagnostic"
                    if definition["decision_role"] == "risk_diagnostic"
                    else "contradicted"
                    if comparison == "failed"
                    else "supported"
                ),
                "state": comparison,
                "value": int(definition["threshold"]),
            }
        )
        criteria.append(item)
    if incomplete:
        criteria.pop()
    return IndexRecord(
        kind="job-completed",
        record_id="c" * 64,
        subject="Job:fixture",
        status="success",
        fingerprint="f" * 64,
        payload={
            "scientific": {
                "adjudication": {
                    "criteria": criteria,
                    "evaluable": True,
                    "invalid_metrics": [],
                    "schema": "scientific_adjudication.v1",
                    "state": state,
                },
                "executed_evidence_modes": list(
                    subject.ANALOG_REPLAY_EVIDENCE_MODES
                ),
            }
        },
    )


class ProjectGoalAuditV2P1ReplayTests(unittest.TestCase):
    @staticmethod
    def _historical_completed_design(writer: StateWriter):
        def resolutions(_index, axes, **_kwargs):
            return tuple(
                SimpleNamespace(
                    status=(
                        subject.EffectiveAxisStatus.SELECTABLE
                        if axis.get("axis_id") == "axis-cost-aware-execution"
                        else subject.EffectiveAxisStatus.PRUNED
                    )
                )
                for axis in axes
            )

        with patch.object(
            subject,
            "effective_axis_resolutions",
            side_effect=resolutions,
        ):
            return subject.build_p1_replay_design(writer)

    def test_judgement_binding_uses_same_event_decision_record(self) -> None:
        event_id = "e" * 64
        job_id = "job:" + "1" * 64
        completion = IndexRecord(
            kind="job-completed",
            record_id="2" * 64,
            subject=f"Job:{job_id}",
            status="success",
            fingerprint="3" * 64,
            payload={"job_id": job_id},
            authority_sequence=4954,
            authority_event_id="d" * 64,
        )
        operation = IndexRecord(
            kind="operation",
            record_id="p1-stu0061-replay-v2-member-01-judge-job",
            subject="Job:completed",
            status="success",
            fingerprint="4" * 64,
            payload={
                "result": {
                    "disposition": "continue_batch",
                    "job_id": job_id,
                }
            },
            authority_sequence=4955,
            authority_event_id=event_id,
        )
        decision = IndexRecord(
            kind="job-evidence-decision",
            record_id="5" * 64,
            subject=f"Job:{job_id}",
            status="continue_batch",
            fingerprint=completion.fingerprint,
            payload={
                "completion_record_id": completion.record_id,
                "negative_memory_id": None,
            },
            authority_sequence=4955,
            authority_event_id=event_id,
        )
        index = SimpleNamespace(
            records_by_kind=lambda kind: (
                (decision,) if kind == "job-evidence-decision" else ()
            )
        )

        subject._require_job_judgement_binding(
            index,
            operation=operation,
            completion=completion,
            expected_disposition="continue_batch",
            expected_negative_memory_id=None,
            label="member-01",
        )

        forged = IndexRecord(
            kind=decision.kind,
            record_id=decision.record_id,
            subject=decision.subject,
            status=decision.status,
            fingerprint=decision.fingerprint,
            payload={
                "completion_record_id": "6" * 64,
                "negative_memory_id": None,
            },
            authority_sequence=decision.authority_sequence,
            authority_event_id=decision.authority_event_id,
        )
        forged_index = SimpleNamespace(
            records_by_kind=lambda kind: (
                (forged,) if kind == "job-evidence-decision" else ()
            )
        )
        with self.assertRaisesRegex(RuntimeError, "judgement drifted"):
            subject._require_job_judgement_binding(
                forged_index,
                operation=operation,
                completion=completion,
                expected_disposition="continue_batch",
                expected_negative_memory_id=None,
                label="member-01",
            )

    def test_read_only_main_requires_stable_head_and_emits_plan(self) -> None:
        writer = SimpleNamespace(
            require_stable_head=Mock(return_value={"stable": True}),
            recover=Mock(side_effect=AssertionError("read-only recovery attempted")),
        )
        boundary = SimpleNamespace(revision=4938, event_id="e" * 64)
        design = SimpleNamespace()
        expected = {"mode": "read_only_plan", "study_id": subject.STUDY_ID}
        with patch.object(subject, "StateWriter", return_value=writer), patch.object(
            subject,
            "validate_correction_predecessor",
            return_value=boundary,
        ) as validate_predecessor, patch.object(
            subject,
            "build_p1_replay_design",
            return_value=design,
        ) as build_design, patch.object(
            subject,
            "_read_only_summary",
            return_value=expected,
        ) as read_only_summary, patch("builtins.print") as print_output:
            subject.main(())

        writer.require_stable_head.assert_called_once_with()
        writer.recover.assert_not_called()
        validate_predecessor.assert_called_once_with(writer)
        build_design.assert_called_once_with(writer)
        read_only_summary.assert_called_once_with(
            writer,
            design,
            boundary=boundary,
        )
        summary = json.loads(print_output.call_args.args[0])
        self.assertEqual(summary["mode"], "read_only_plan")
        self.assertEqual(summary["study_id"], subject.STUDY_ID)

    def test_family_is_exact_one_to_one_and_target_is_final(self) -> None:
        members = subject.ordered_replay_members()
        execution_ids = tuple(
            member.executable.identity for member in members
        )
        references = tuple(
            member.configuration.historical_reference_executable_id
            for member in members
        )
        self.assertEqual(len(members), 4)
        self.assertEqual(len(set(execution_ids)), 4)
        self.assertEqual(
            subject._canonical_statistical_family_ids(members),
            tuple(sorted(execution_ids)),
        )
        self.assertNotEqual(execution_ids, tuple(sorted(execution_ids)))
        self.assertEqual(len(set(references)), 4)
        self.assertEqual(references[-1], subject.TARGET_ORIGINAL_EXECUTABLE_ID)
        for row, member in enumerate(members):
            payload = member.executable.to_identity_payload()
            self.assertEqual(
                tuple(
                    subject._payload_value_count(payload, str(reference))
                    for reference in references
                ),
                tuple(1 if row == column else 0 for column in range(4)),
            )

    def test_complete_negative_recomputation_satisfies_but_incomplete_preserves(self) -> None:
        negative = subject.interpret_replay_completion(
            _completion(state="contradicted")
        )
        self.assertTrue(negative.all_original_criteria_recomputed)
        self.assertEqual(negative.close_outcome, "pruned")
        self.assertEqual(negative.disposition.value, "prune")

        incomplete = subject.interpret_replay_completion(
            _completion(state="contradicted", incomplete=True)
        )
        self.assertFalse(incomplete.all_original_criteria_recomputed)
        self.assertEqual(incomplete.close_outcome, "not_evaluable")
        self.assertEqual(incomplete.disposition.value, "preserve")

    def test_operation_plan_is_sequential_and_target_resolution_is_dynamic(self) -> None:
        base = subject.operation_steps(replay_recomputed=False)
        satisfied = subject.operation_steps(replay_recomputed=True)
        failed = subject.operation_steps(
            failed_member_ordinals=(2,),
            replay_recomputed=True,
        )
        self.assertEqual(
            next(step.event_kind for step in base if step.operation_id.endswith("resolve-replay")),
            "historical_replay_obligations_deferred",
        )
        self.assertEqual(
            next(
                step.event_kind
                for step in satisfied
                if step.operation_id.endswith("resolve-replay")
            ),
            "historical_replay_obligations_resolved",
        )
        negative_index = next(
            index
            for index, step in enumerate(failed)
            if step.operation_id.endswith("member-02-negative-memory")
        )
        self.assertTrue(
            failed[negative_index - 1].operation_id.endswith("member-02-complete-job")
        )
        self.assertTrue(
            failed[negative_index + 1].operation_id.endswith("member-02-judge-job")
        )
        _, study_end = stage_bounds(satisfied, stage="study-close")
        diagnose_start, diagnose_end = stage_bounds(satisfied, stage="diagnose")
        self.assertEqual(study_end, diagnose_start)
        self.assertEqual(diagnose_end, len(satisfied))
        registration_positions = tuple(
            index
            for index, step in enumerate(satisfied)
            if step.operation_id.endswith("-register-trial")
        )
        self.assertEqual(len(registration_positions), 4)
        first_declaration = next(
            index
            for index, step in enumerate(satisfied)
            if step.operation_id.endswith("member-01-declare-job")
        )
        self.assertLess(max(registration_positions), first_declaration)
        self.assertEqual(
            registration_positions,
            tuple(range(registration_positions[0], first_declaration)),
        )
        first_completion = next(
            index
            for index, step in enumerate(satisfied)
            if step.operation_id.endswith("member-01-complete-job")
        )
        first_completion_prefix = satisfied[: first_completion + 1]
        self.assertEqual(
            sum(
                step.operation_id.endswith("-register-trial")
                for step in first_completion_prefix
            ),
            4,
        )
        target_complete = next(
            index
            for index, step in enumerate(satisfied)
            if step.operation_id.endswith("member-04-complete-job")
        )
        self.assertTrue(
            all(
                next(
                    index
                    for index, step in enumerate(satisfied)
                    if step.operation_id.endswith(f"member-{ordinal:02d}-judge-job")
                )
                < target_complete
                for ordinal in (1, 2, 3)
            )
        )

    def test_read_only_design_adds_one_bridge_and_selects_only_target_obligation(self) -> None:
        writer = StateWriter(subject.ROOT)
        design = subject.build_p1_replay_design(
            writer,
            base_snapshot_id=subject._base_snapshot_id(writer),
        )
        self.assertEqual(
            len(design.expanded_snapshot.axes),
            len(design.prior_axes) + 1,
        )
        self.assertEqual(design.bridge_decision.chosen.action.value, "new_mechanism")
        self.assertEqual(
            design.work_decision.replay_obligation_ids,
            (subject.TARGET_OBLIGATION_ID,),
        )
        self.assertEqual(design.batch_spec.max_trials, 4)
        assert design.batch_spec.concurrent_family is not None
        execution_ids = tuple(
            member.executable.identity for member in design.members
        )
        self.assertEqual(
            design.batch_spec.concurrent_family.executable_ids,
            tuple(sorted(execution_ids)),
        )
        self.assertNotEqual(execution_ids, tuple(sorted(execution_ids)))
        self.assertEqual(
            design.batch_spec.acceptance()["concurrent_family"],
            design.batch_spec.concurrent_family.to_identity_payload(),
        )
        self.assertEqual(design.target_member.ordinal, 4)
        with self.assertRaisesRegex(ValueError, "statistical family"):
            replace(
                design,
                batch_spec=SimpleNamespace(
                    concurrent_family=SimpleNamespace(
                        executable_ids=execution_ids,
                    )
                ),
            )

    def test_job_implementation_manifest_covers_direct_and_validator_dependencies(self) -> None:
        with TemporaryDirectory() as directory:
            writer = StateWriter(
                Path(directory),
                engineering_fixture=True,
                foundation_root=subject.ROOT,
            )
            member = subject.ordered_replay_members()[0]
            spec = subject.build_job_spec(writer, member)
            artifact = writer.evidence.verify(spec["implementation_identity"])
            manifest = parse_canonical(
                (writer.evidence._root / artifact.relative_path).read_bytes()
            )
            expected_paths = set(subject._implementation_dependency_paths())
            self.assertTrue(
                {Path(path).resolve() for path in SCIENTIFIC_VALIDATION_V2_DEPENDENCIES}
                .issubset(expected_paths)
            )
            self.assertTrue(
                set(subject.running_job_execution_context_dependency_paths())
                .issubset(expected_paths)
            )
            self.assertNotIn(
                (
                    subject.ROOT
                    / "src"
                    / "axiom_rift"
                    / "operations"
                    / "writer.py"
                ).resolve(),
                expected_paths,
            )
            self.assertEqual(
                set(manifest["artifact_hashes"]),
                {sha256(path.read_bytes()).hexdigest() for path in expected_paths},
            )
            self.assertEqual(len(spec["expected_outputs"]), 6)
            self.assertEqual(
                spec["output_classes"][
                    subject.ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
                ],
                "reproducible_cache",
            )
            self.assertEqual(
                tuple(spec["output_classes"].values()).count("durable_evidence"),
                5,
            )
            self.assertTrue(
                require_job_implementation_closure(
                    executable_manifest=member.executable.to_identity_payload(),
                    job_artifact_hashes=manifest["artifact_hashes"],
                    artifact_reader=writer.evidence.read_verified,
                )
            )

    def test_job_implementation_identity_ignores_writer_but_binds_context(
        self,
    ) -> None:
        baseline = subject._implementation_identity(  # type: ignore[arg-type]
            None,
            materialize=False,
        )
        writer_path = (
            subject.ROOT
            / "src"
            / "axiom_rift"
            / "operations"
            / "writer.py"
        ).resolve()
        running_job_path = (
            subject.ROOT
            / "src"
            / "axiom_rift"
            / "operations"
            / "running_job.py"
        ).resolve()
        original_read_bytes = Path.read_bytes

        def perturb_writer(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == writer_path:
                return content + b"\n# unrelated writer perturbation"
            return content

        with patch.object(Path, "read_bytes", perturb_writer):
            self.assertEqual(
                subject._implementation_identity(  # type: ignore[arg-type]
                    None,
                    materialize=False,
                ),
                baseline,
            )

        def perturb_context(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == running_job_path:
                return content + b"\n# running context perturbation"
            return content

        with patch.object(Path, "read_bytes", perturb_context):
            self.assertNotEqual(
                subject._implementation_identity(  # type: ignore[arg-type]
                    None,
                    materialize=False,
                ),
                baseline,
            )

    def test_later_job_specs_bind_first_cache_and_trace_once(self) -> None:
        with TemporaryDirectory() as directory:
            writer = StateWriter(
                Path(directory),
                engineering_fixture=True,
                foundation_root=subject.ROOT,
            )
            members = subject.ordered_replay_members()
            first = members[0]
            cache_hash = "a" * 64
            trace_hash = "b" * 64
            first_outputs = {
                name: "c" * 64
                for name in first.replay_plan.expected_outputs(
                    produce_family_cache=True
                )
            }
            first_outputs[subject.ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME] = (
                cache_hash
            )
            first_outputs[first.replay_plan.output_names["trace"]] = trace_hash
            completion = IndexRecord(
                kind="job-completed",
                record_id="d" * 64,
                subject="Job:producer",
                status="success",
                fingerprint="e" * 64,
                payload={"outputs": first_outputs},
            )
            with patch.object(subject, "_member_completion", return_value=completion):
                for member in members[1:]:
                    spec = subject.build_job_spec(writer, member)
                    self.assertEqual(len(spec["expected_outputs"]), 5)
                    self.assertNotIn(
                        subject.ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
                        spec["expected_outputs"],
                    )
                    self.assertEqual(
                        set(spec["output_classes"].values()),
                        {"durable_evidence"},
                    )
                    self.assertEqual(spec["input_hashes"].count(cache_hash), 1)
                    self.assertEqual(spec["input_hashes"].count(trace_hash), 1)
                    self.assertEqual(
                        tuple(spec["input_hashes"]),
                        member.replay_plan.job_input_hashes(
                            family_trace_cache_hash=cache_hash,
                            family_trace_manifest_hash=trace_hash,
                        ),
                    )
            with patch.object(subject, "_member_completion", return_value=None):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "lack the exact first completion",
                ):
                    subject.build_job_spec(writer, members[1])

    def test_read_only_summary_separates_durable_and_cache_outputs(self) -> None:
        design = SimpleNamespace(
            expanded_snapshot=SimpleNamespace(axes=(1, 2)),
            prior_axes=(1,),
            base_snapshot_id="portfolio:base",
            members=subject.ordered_replay_members(),
            replay_axis=SimpleNamespace(axis_id=subject.AXIS_ID),
            work_decision=SimpleNamespace(
                replay_obligation_ids=(subject.TARGET_OBLIGATION_ID,)
            ),
            target_member=SimpleNamespace(ordinal=4),
            historical_family=SimpleNamespace(
                family_executable_ids=tuple(
                    f"executable:{ordinal:064x}" for ordinal in range(1, 5)
                ),
                batch_id="batch:" + "b" * 64,
                prior_global_exposure_count=574,
            ),
        )
        steps = subject.operation_steps()
        with patch.object(
            subject,
            "inspect_replay_prefix",
            return_value=(0, steps),
        ):
            summary = subject._read_only_summary(
                SimpleNamespace(),
                design,
                boundary=SimpleNamespace(),
            )
        self.assertEqual(summary["durable_output_count"], 20)
        self.assertEqual(summary["reproducible_cache_output_count"], 1)
        self.assertEqual(summary["historical_non_p1_exposure_count"], 574)
        self.assertTrue(summary["audit_only"])
        self.assertEqual(summary["scientific_credit"], 0)
        self.assertEqual(summary["terminal_credit"], 0)
        self.assertEqual(
            summary["executable_ids"],
            summary["historical_registered_executable_ids"],
        )
        self.assertNotEqual(
            summary["executable_ids"],
            summary["prospective_current_executable_ids"],
        )
        self.assertEqual(summary["historical_batch_id"], "batch:" + "b" * 64)

    def test_historical_exposure_freezes_before_all_four_p1_trials(
        self,
    ) -> None:
        members = subject.ordered_replay_members()
        writer = StateWriter(subject.ROOT)
        with LocalIndex.open_read_only(writer.index_path) as index:
            observation = subject._require_historical_non_p1_exposure(
                writer,
                index,
                members,
            )
        self.assertEqual(observation.prior_global_exposure_count, 574)
        self.assertEqual(
            tuple(member.configuration.configuration_id for member in members),
            tuple(member.configuration_id for member in observation.members),
        )
        current_ids = tuple(member.executable.identity for member in members)
        self.assertNotEqual(observation.family_executable_ids, current_ids)
        design = SimpleNamespace(
            members=members,
            historical_family=observation,
        )
        with self.assertRaisesRegex(RuntimeError, "successor STU-0112"):
            subject._require_current_prospective_execution_family(design)
        self.assertNotIn(
            'records_by_kind("trial")',
            (
                subject.ROOT
                / "scripts"
                / "run_project_goal_audit_v2_p1_replay.py"
            ).read_text(encoding="ascii"),
        )

    def test_historical_completed_chain_ignores_current_implementation_drift(
        self,
    ) -> None:
        writer = StateWriter(subject.ROOT)
        design = self._historical_completed_design(writer)
        steps = subject.operation_steps(writer, design=design)
        with LocalIndex.open_read_only(writer.index_path) as index, patch.object(
            subject,
            "analog_family_executable",
            side_effect=AssertionError("current implementation was consulted"),
        ), patch.object(
            subject,
            "build_job_spec",
            side_effect=AssertionError("current Job identity was rebuilt"),
        ):
            subject._validate_historical_completed_replay_chain(
                writer,
                index,
                design=design,
                steps=steps,
            )

    def test_historical_completed_chain_rejects_payload_or_owner_tampering(
        self,
    ) -> None:
        class ForgedIndex:
            def __init__(self, index, replacement_record: IndexRecord) -> None:
                self.index = index
                self.replacement_record = replacement_record

            def __getattr__(self, name: str):
                return getattr(self.index, name)

            def get(self, kind: str, record_id: str):
                replacement = self.replacement_record
                if replacement.kind == kind and replacement.record_id == record_id:
                    return replacement
                return self.index.get(kind, record_id)

        writer = StateWriter(subject.ROOT)
        design = self._historical_completed_design(writer)
        steps = subject.operation_steps(writer, design=design)
        with LocalIndex.open_read_only(writer.index_path) as index:
            operation_id = subject.OPERATION_PREFIX + "open-batch"
            operation = index.get("operation", operation_id)
            assert operation is not None
            forged_owner = replace(operation, subject="Batch:forged")
            with self.assertRaisesRegex(RuntimeError, "operation ownership"):
                subject._validate_historical_completed_replay_chain(
                    writer,
                    ForgedIndex(index, forged_owner),
                    design=design,
                    steps=steps,
                )

            member = design.historical_family.members[0]
            trial = index.get("trial", member.executable_id)
            assert trial is not None
            forged_payload = replace(
                trial,
                payload={**trial.payload, "trial_delta": 2},
            )
            with self.assertRaisesRegex(RuntimeError, "trial authority"):
                subject._validate_historical_completed_replay_chain(
                    writer,
                    ForgedIndex(index, forged_payload),
                    design=design,
                    steps=steps,
                )

    def test_close_provenance_uses_durable_traces_without_requiring_cache_file(
        self,
    ) -> None:
        members = subject.ordered_replay_members()
        neutral = {"family": "durable-neutral-trace"}
        neutral_content = canonical_bytes(neutral)
        cache_hash = sha256(neutral_content).hexdigest()
        producer_manifest = {"cache_sha256": cache_hash, "schema": "fixture"}
        artifacts: dict[str, bytes] = {}
        completions = []
        for member in members:
            job_id = f"job:{member.ordinal:064x}"
            job_hash = f"{member.ordinal + 8:064x}"
            trace = {
                "job_hash": job_hash,
                "job_id": job_id,
                "mission_id": subject.MISSION_ID,
                "subject_executable_id": member.executable.identity,
            }
            content = canonical_bytes(trace)
            trace_hash = sha256(content).hexdigest()
            artifacts[trace_hash] = content
            completions.append(
                (
                    member,
                    IndexRecord(
                        kind="job-completed",
                        record_id=f"{member.ordinal + 20:064x}",
                        subject=f"Job:{job_id}",
                        status="success",
                        fingerprint=job_hash,
                        payload={
                            "job_id": job_id,
                            "outputs": {
                                member.replay_plan.output_names["trace"]: trace_hash,
                                **(
                                    {
                                        subject.ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME: (
                                            cache_hash
                                        )
                                    }
                                    if member.ordinal == 1
                                    else {}
                                ),
                            },
                        },
                    ),
                )
            )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            writer = SimpleNamespace(
                root=root,
                evidence=SimpleNamespace(
                    read_verified=lambda identity: artifacts[identity]
                ),
            )
            cache = SimpleNamespace(
                content=neutral_content,
                sha256=cache_hash,
            )
            with (
                patch.object(
                    subject,
                    "verify_analog_family_trace_cache_producer",
                    return_value=(
                        cache,
                        next(iter(completions))[1].payload["outputs"][
                            members[0].replay_plan.output_names["trace"]
                        ],
                        producer_manifest,
                    ),
                ) as verify,
                patch.object(
                    subject.trace_module,
                    "extract_analog_family_trace_cache_material",
                    return_value=(neutral, producer_manifest),
                ),
            ):
                subject._verify_durable_family_trace_provenance(
                    writer,
                    SimpleNamespace(members=members),
                    member_completions=tuple(completions),
                    cache_hash=cache_hash,
                )
            self.assertFalse(
                (root / subject.ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).exists()
            )
            self.assertFalse(verify.call_args.kwargs["materialize_missing"])
            mismatched_manifest = {
                "cache_sha256": cache_hash,
                "schema": "different-producer",
            }

            def extract_with_one_mismatch(trace, *, require_producer=False):
                del require_producer
                manifest = (
                    mismatched_manifest
                    if trace["subject_executable_id"]
                    == members[1].executable.identity
                    else producer_manifest
                )
                return neutral, manifest

            with (
                patch.object(
                    subject,
                    "verify_analog_family_trace_cache_producer",
                    return_value=(
                        cache,
                        completions[0][1].payload["outputs"][
                            members[0].replay_plan.output_names["trace"]
                        ],
                        producer_manifest,
                    ),
                ),
                patch.object(
                    subject.trace_module,
                    "extract_analog_family_trace_cache_material",
                    side_effect=extract_with_one_mismatch,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "provenance drifted"):
                    subject._verify_durable_family_trace_provenance(
                        writer,
                        SimpleNamespace(members=members),
                        member_completions=tuple(completions),
                        cache_hash=cache_hash,
                    )

    def test_strict_chain_accepts_only_an_exact_prefix_and_legal_full_suffix(self) -> None:
        steps = (
            OperationStep("p1-a", "a", "one"),
            OperationStep("p1-b", "b", "one"),
            OperationStep("p1-c", "c", "two"),
        )
        predecessor = "0" * 64

        def fixture(positions: tuple[int, ...], *, foreign: bool = False):
            _FakeIndex.records = {}
            events = {}
            prior = predecessor
            for position in positions:
                step = steps[position]
                event_id = f"{position + 1:064x}"
                record = SimpleNamespace(
                    record_id=step.operation_id,
                    status="success",
                    payload={"event_kind": step.event_kind},
                    authority_sequence=101 + position,
                    authority_event_id=event_id,
                    authority_offset=position + 1,
                )
                _FakeIndex.records[record.record_id] = record
                events[position + 1] = {
                    "event_id": event_id,
                    "event_kind": step.event_kind,
                    "operation_id": step.operation_id,
                    "previous_event_id": prior,
                    "sequence": 101 + position,
                }
                prior = event_id
            if foreign:
                _FakeIndex.records["p1-foreign"] = SimpleNamespace(
                    record_id="p1-foreign"
                )
            return _FakeIndex(), _FakeJournal(events)

        index, journal = fixture((0, 1))
        self.assertEqual(
            inspect_operation_prefix(
                index=index,
                journal=journal,
                steps=steps,
                operation_prefix="p1-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=102,
            ),
            2,
        )
        index, journal = fixture((0, 2))
        with self.assertRaisesRegex(StrictOperationChainError, "strict prefix"):
            inspect_operation_prefix(
                index=index,
                journal=journal,
                steps=steps,
                operation_prefix="p1-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=102,
            )
        index, journal = fixture((0, 1, 2), foreign=True)
        with self.assertRaisesRegex(StrictOperationChainError, "undeclared"):
            inspect_operation_prefix(
                index=index,
                journal=journal,
                steps=steps,
                operation_prefix="p1-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=103,
            )
        index, journal = fixture((0, 1, 2))
        self.assertEqual(
            inspect_operation_prefix(
                index=index,
                journal=journal,
                steps=steps,
                operation_prefix="p1-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=999,
            ),
            3,
        )

    def test_semantic_prefix_rejects_same_operation_and_kind_with_wrong_payload(self) -> None:
        operation_id = subject.OPERATION_PREFIX + "open-initiative"
        _FakeIndex.records = {
            operation_id: SimpleNamespace(
                record_id=operation_id,
                status="success",
                payload={
                    "event_kind": "initiative_opened",
                    "result": {"initiative_id": subject.INITIATIVE_ID},
                },
            )
        }
        _FakeIndex.by_kind = {
            ("initiative-open", subject.INITIATIVE_ID): IndexRecord(
                kind="initiative-open",
                record_id=subject.INITIATIVE_ID,
                subject=f"Initiative:{subject.INITIATIVE_ID}",
                status="open",
                fingerprint="f" * 64,
                payload={"objective": {"objective": "wrong"}},
            )
        }
        writer = SimpleNamespace(index_path=Path("unused"))
        with patch.object(subject, "LocalIndex", _FakeIndex):
            with self.assertRaisesRegex(RuntimeError, "Initiative identity drifted"):
                subject.validate_replay_prefix_semantics(
                    writer,
                    design=SimpleNamespace(),
                    prefix=1,
                    steps=(
                        OperationStep(
                            operation_id,
                            "initiative_opened",
                            "study-close",
                        ),
                    ),
                )

    def test_cli_plan_and_mutating_stages_are_explicitly_separated(self) -> None:
        plan = subject.parse_arguments([])
        self.assertIsNone(plan.stage)
        self.assertFalse(plan.recover)
        close = subject.parse_arguments(["--stage", "study-close", "--recover"])
        self.assertEqual(close.stage, "study-close")
        self.assertTrue(close.recover)
        diagnose = subject.parse_arguments(
            [
                "--stage",
                "diagnose",
                "--study-close-event-id",
                "a" * 64,
                "--study-close-revision",
                "5000",
            ]
        )
        self.assertEqual(diagnose.study_close_revision, 5000)


if __name__ == "__main__":
    unittest.main()
