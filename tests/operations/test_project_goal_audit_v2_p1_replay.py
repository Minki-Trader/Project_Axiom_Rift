from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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
    def test_family_is_exact_one_to_one_and_target_is_final(self) -> None:
        members = subject.ordered_replay_members()
        references = tuple(
            member.configuration.historical_reference_executable_id
            for member in members
        )
        self.assertEqual(len(members), 4)
        self.assertEqual(len(set(member.executable.identity for member in members)), 4)
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
        with LocalIndex(writer.index_path) as index:
            head = index.event_head(f"portfolio:{subject.MISSION_ID}")
            self.assertIsNotNone(head)
            assert head is not None
            base_snapshot_id = head.record_id
        design = subject.build_p1_replay_design(
            writer,
            base_snapshot_id=base_snapshot_id,
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
        self.assertEqual(
            design.batch_spec.concurrent_family.executable_ids,
            tuple(member.executable.identity for member in design.members),
        )
        self.assertEqual(
            design.batch_spec.acceptance()["concurrent_family"],
            design.batch_spec.concurrent_family.to_identity_payload(),
        )
        self.assertEqual(design.target_member.ordinal, 4)

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

    def test_historical_exposure_excludes_all_four_preregistered_p1_trials(
        self,
    ) -> None:
        members = subject.ordered_replay_members()
        historical = tuple(
            SimpleNamespace(record_id=f"executable:{index:064x}")
            for index in range(556)
        )
        p1 = tuple(
            SimpleNamespace(record_id=member.executable.identity)
            for member in members
        )
        index = SimpleNamespace(
            records_by_kind=lambda kind: historical + p1 if kind == "trial" else ()
        )
        writer = SimpleNamespace(foundation_root=subject.ROOT)
        accountant = SimpleNamespace(prior_global_multiplicity_floor=18)
        with patch.object(
            subject.TrialAccountant,
            "from_foundation",
            return_value=accountant,
        ):
            self.assertEqual(
                subject._require_historical_non_p1_exposure(
                    writer,
                    index,
                    members,
                ),
                574,
            )
            foreign = SimpleNamespace(record_id="executable:" + "f" * 64)
            index.records_by_kind = lambda kind: (
                historical + p1 + (foreign,) if kind == "trial" else ()
            )
            with self.assertRaisesRegex(RuntimeError, "context drifted"):
                subject._require_historical_non_p1_exposure(
                    writer,
                    index,
                    members,
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
