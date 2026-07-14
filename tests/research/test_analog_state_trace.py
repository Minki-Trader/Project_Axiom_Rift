from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidationArtifact,
)
from axiom_rift.operations.replay_projection import payload_contains_exact_value
from axiom_rift.operations.writer import (
    RunningJobExecution,
    _hardcoded_control_ids,
)
from axiom_rift.research import analog_state_family as analog_family_module
from axiom_rift.research import analog_state_replay as analog_replay_module
from axiom_rift.research import analog_state_trace as analog_trace_module
from axiom_rift.research.analog_state_family import (
    CURRENT_H48_N15_ANALOG_FAMILY,
    P1_STU0061_ANALOG_FAMILY,
    analog_family_executable_map,
    analog_replay_controlled_chassis,
)
from axiom_rift.research.analog_state_replay import (
    ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
    FROZEN_STU0061_RAW_METRICS,
    STU0061_REPLAY_CRITERION_IDS,
    AnalogFamilyTraceCache,
    assert_frozen_stu0061_raw_metric_parity,
    build_analog_family_trace_cache_manifest,
    build_analog_replay_measurement,
    build_analog_replay_plan,
    build_analog_replay_result,
    compute_analog_replay_trace,
    execute_analog_replay_job,
    load_or_compute_analog_family_trace,
    validated_stu0061_recomputed_criterion_ids,
    verify_analog_family_trace_cache_producer,
)
from axiom_rift.research.chassis import validate_controlled_executable
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CONTROLS,
    ANALOG_REPLAY_CRITERIA,
    ANALOG_REPLAY_EVIDENCE_MODES,
    ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT,
    ANALOG_REPLAY_TRACE_ATTRIBUTION,
    analog_family_execution_contracts,
    analog_family_trace_implementation_identities,
    analog_observation_id,
    analog_original_family_provenance,
    bind_analog_family_trace,
    build_analog_trace_calculation,
    expected_analog_family_inventory,
    extract_analog_family_trace_cache_binding,
    extract_analog_family_trace_cache_manifest,
    extract_analog_family_trace_cache_material,
    extract_analog_family_trace_from_subject,
    validate_analog_family_trace,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_STATE_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


MISSION_ID = "MIS-ATOMIC-ANALOG"
STUDY_ID = "STU-ATOMIC-ANALOG"
JOB_ID = "job:" + "d" * 64
JOB_HASH = "a" * 64


class _FakeEvidenceStore:
    def __init__(self, artifacts: dict[str, bytes]) -> None:
        self.artifacts = artifacts

    def read_verified(self, identity: str) -> bytes:
        try:
            content = self.artifacts[identity]
        except KeyError as exc:
            raise FileNotFoundError(identity) from exc
        if sha256(content).hexdigest() != identity:
            raise RuntimeError("fake evidence content hash drifted")
        return content

    def finalize(self, content: bytes) -> SimpleNamespace:
        identity = sha256(content).hexdigest()
        self.artifacts[identity] = content
        return SimpleNamespace(sha256=identity)


class _FakeWriter:
    def __init__(
        self,
        artifacts: dict[str, bytes],
        *,
        producer_error: Exception | None = None,
    ) -> None:
        self.evidence = _FakeEvidenceStore(artifacts)
        self.producer_error = producer_error
        self.producer_calls: list[tuple[RunningJobExecution, dict[str, object]]] = []
        self.running_bindings: dict[str, dict[str, object]] = {}

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        *,
        expected_callable_identity: str,
    ) -> dict[str, object]:
        self.asserted_callable_identity = expected_callable_identity
        return self.running_bindings[execution.job_id]

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: object,
    ) -> None:
        self.producer_calls.append((producer, dict(kwargs)))
        if self.producer_error is not None:
            raise self.producer_error


def _synthetic_family_trace() -> dict[str, object]:
    inventory = expected_analog_family_inventory()
    windows: list[dict[str, object]] = []
    dates_by_fold: dict[str, list[str]] = {}
    base = datetime(2025, 1, 1)
    for index, fold_id in enumerate(EXPECTED_FOLD_IDS):
        test_start = base + timedelta(days=7 * index)
        eligible = [
            (test_start + timedelta(days=offset)).date().isoformat()
            for offset in range(4)
        ]
        dates_by_fold[fold_id] = eligible
        windows.append(
            {
                "eligible_dates": eligible,
                "fold_id": fold_id,
                "test_end": (test_start + timedelta(days=3, hours=23)).isoformat(),
                "test_start": test_start.isoformat(),
                "train_end": (test_start - timedelta(days=2)).isoformat(),
                "train_start": (test_start - timedelta(days=40)).isoformat(),
            }
        )
    trades: list[dict[str, object]] = []
    intents: list[dict[str, object]] = []
    eligible_rows: list[dict[str, object]] = []
    for member_index, member in enumerate(inventory):
        configuration_id = str(member["configuration_id"])
        for fold_index, fold_id in enumerate(EXPECTED_FOLD_IDS):
            fold_trade_rows: list[dict[str, object]] = []
            for day_index, day in enumerate(dates_by_fold[fold_id]):
                bar_open = datetime.fromisoformat(day + "T10:00:00")
                entry = bar_open + timedelta(minutes=5)
                exit_time = entry + timedelta(minutes=120)
                signed_edge = (5 - member_index * 2) * 1_000
                native_net = signed_edge + ((fold_index + day_index) % 3 - 1) * 250
                native_cost = 100
                stress_cost = 150
                gross = native_net + native_cost
                row: dict[str, object] = {
                    "availability_time": entry.isoformat(),
                    "configuration_id": configuration_id,
                    "decision_bar_open_time": bar_open.isoformat(),
                    "decision_time": entry.isoformat(),
                    "direction": 1 if day_index % 2 == 0 else -1,
                    "entry_time": entry.isoformat(),
                    "executable_id": member["executable_id"],
                    "exit_time": exit_time.isoformat(),
                    "fold_id": fold_id,
                    "gross_pnl_micropoints": gross,
                    "historical_reference_executable_id": member[
                        "historical_reference_executable_id"
                    ],
                    "native_cost_micropoints": native_cost,
                    "native_net_pnl_micropoints": native_net,
                    "observation_id": "pending",
                    "regime": ("low", "middle", "high")[day_index % 3],
                    "stress_cost_micropoints": stress_cost,
                    "stress_net_pnl_micropoints": gross - stress_cost,
                }
                row["observation_id"] = analog_observation_id("trade", row)
                fold_trade_rows.append(row)
                trades.append(row)
                for scope in ("full", "prefix"):
                    intent: dict[str, object] = {
                        "availability_time": entry.isoformat(),
                        "configuration_id": configuration_id,
                        "decision_time": entry.isoformat(),
                        "direction": row["direction"],
                        "entry_time": entry.isoformat(),
                        "executable_id": member["executable_id"],
                        "exit_time": exit_time.isoformat(),
                        "fold_id": fold_id,
                        "observation_id": "pending",
                        "ordinal": day_index + 1,
                        "scope": scope,
                        "status": "executed",
                    }
                    intent["observation_id"] = analog_observation_id(
                        "intent", intent
                    )
                    intents.append(intent)
            by_day = {
                str(row["decision_time"])[:10]: row for row in fold_trade_rows
            }
            for day in dates_by_fold[fold_id]:
                row = by_day[day]
                eligible_rows.append(
                    {
                        "configuration_id": configuration_id,
                        "date": day,
                        "entry_count": 1,
                        "executable_id": member["executable_id"],
                        "fold_id": fold_id,
                        "native_net_pnl_micropoints": row[
                            "native_net_pnl_micropoints"
                        ],
                        "stress_net_pnl_micropoints": row[
                            "stress_net_pnl_micropoints"
                        ],
                    }
                )
    trades.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["decision_time"],
            item["observation_id"],
        )
    )
    intents.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["scope"],
            item["ordinal"],
            item["observation_id"],
        )
    )
    eligible_rows.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["date"],
        )
    )
    comparisons = []
    for window in windows:
        for profile in P1_STU0061_ANALOG_FAMILY.profiles:
            digest = sha256(
                f"{window['fold_id']}:{profile.profile_id}".encode("ascii")
            ).hexdigest()
            comparisons.append(
                {
                    "compared_row_count": 1_000,
                    "fold_id": window["fold_id"],
                    "full_score_values_sha256": digest,
                    "prefix_score_values_sha256": digest,
                    "profile_id": profile.profile_id,
                }
            )
    contracts = analog_family_execution_contracts()
    return {
        "attribution": ANALOG_REPLAY_TRACE_ATTRIBUTION,
        "clock_contract": contracts["clock_contract"],
        "controls": ANALOG_REPLAY_CONTROLS,
        "cost_contract": contracts["cost_contract"],
        "dataset_sha256": DATASET_SHA256,
        "eligible_day_observations": eligible_rows,
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_implementation_identities()
        ),
        "intent_observations": intents,
        "invariance_comparisons": comparisons,
        "material_identity": OBSERVED_MATERIAL_ID,
        "ordered_family": list(inventory),
        "original_family_provenance": analog_original_family_provenance(),
        "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trade_observations": trades,
        "windows": windows,
    }


def _synthetic_trace(executable_id: str) -> dict[str, object]:
    return bind_analog_family_trace(
        family_trace=_synthetic_family_trace(),
        mission_id=MISSION_ID,
        executable_id=executable_id,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
    )


class AnalogStateTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapping = analog_family_executable_map(P1_STU0061_ANALOG_FAMILY)
        self.executable_id = next(iter(self.mapping))

    def _producer_cache_capability(
        self,
    ) -> tuple[
        AnalogFamilyTraceCache,
        RunningJobExecution,
        dict[str, object],
        bytes,
        str,
    ]:
        family_trace = validate_analog_family_trace(_synthetic_family_trace())
        cache_content = canonical_bytes(family_trace)
        family_cache = AnalogFamilyTraceCache(
            content=cache_content,
            produced=False,
            sha256=sha256(cache_content).hexdigest(),
        )
        execution = RunningJobExecution(
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            job_permit_id="b" * 64,
            start_record_id="c" * 64,
        )
        producer_id = str(
            expected_analog_family_inventory()[0]["executable_id"]
        )
        producer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=producer_id,
        )
        manifest = build_analog_family_trace_cache_manifest(
            replay_plan=producer_plan,
            execution=execution,
            cache_sha256=family_cache.sha256,
        )
        producer_trace = bind_analog_family_trace(
            family_trace=family_trace,
            mission_id=MISSION_ID,
            executable_id=producer_id,
            job_id=execution.job_id,
            job_hash=execution.job_hash,
            cache_manifest=manifest,
        )
        trace_content = canonical_bytes(producer_trace)
        return (
            family_cache,
            execution,
            producer_trace,
            trace_content,
            sha256(trace_content).hexdigest(),
        )

    def test_typed_family_retains_one_exact_historical_reference_per_member(self) -> None:
        self.assertEqual(P1_STU0061_ANALOG_FAMILY.horizon, 24)
        self.assertEqual(P1_STU0061_ANALOG_FAMILY.neighbors, 25)
        self.assertEqual(P1_STU0061_ANALOG_FAMILY.library_stride, 12)
        self.assertEqual(len(self.mapping), 4)
        references = {
            configuration.historical_reference_executable_id
            for configuration in self.mapping.values()
        }
        self.assertEqual(
            references,
            {
                "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463",
                "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7",
                "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df",
                "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8",
            },
        )
        for executable_id, configuration in self.mapping.items():
            executable_payload = analog_family_module.analog_family_executable(
                configuration
            ).to_identity_payload()
            matched_references = tuple(
                sorted(
                    reference
                    for reference in references
                    if payload_contains_exact_value(
                        executable_payload,
                        str(reference),
                    )
                )
            )
            self.assertEqual(
                matched_references,
                (configuration.historical_reference_executable_id,),
            )
            parameters = next(
                value
                for value in expected_analog_family_inventory()
                if value["executable_id"] == executable_id
            )
            self.assertEqual(
                parameters["historical_reference_executable_id"],
                configuration.historical_reference_executable_id,
            )
        self.assertEqual(CURRENT_H48_N15_ANALOG_FAMILY.horizon, 48)
        self.assertEqual(CURRENT_H48_N15_ANALOG_FAMILY.neighbors, 15)

    def test_family_trace_is_neutral_exact_and_binding_rejects_tamper(self) -> None:
        family_trace = _synthetic_family_trace()
        validated = validate_analog_family_trace(family_trace)
        self.assertEqual(validated["schema"], ANALOG_FAMILY_TRACE_SCHEMA)
        for forbidden in (
            "family_trace_sha256",
            "job_hash",
            "job_id",
            "mission_id",
            "subject_executable_id",
        ):
            self.assertNotIn(forbidden, validated)
        references = [
            item["historical_reference_executable_id"]
            for item in validated["ordered_family"]
        ]
        self.assertEqual(len(references), 4)
        self.assertEqual(len(set(references)), 4)
        bound = bind_analog_family_trace(
            family_trace=validated,
            mission_id=MISSION_ID,
            executable_id=self.executable_id,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )
        self.assertEqual(bound["subject_executable_id"], self.executable_id)
        self.assertEqual(
            bound["attribution"]["family_trace_binding"][
                "family_trace_sha256"
            ],
            sha256(canonical_bytes(validated)).hexdigest(),
        )
        tampered = deepcopy(validated)
        tampered["trade_observations"][0][
            "native_net_pnl_micropoints"
        ] += 1
        tampered["trade_observations"][0]["observation_id"] = (
            analog_observation_id("trade", tampered["trade_observations"][0])
        )
        with self.assertRaisesRegex(ValueError, "cost arithmetic"):
            bind_analog_family_trace(
                family_trace=tampered,
                mission_id=MISSION_ID,
                executable_id=self.executable_id,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )

    def test_574_context_is_descriptive_and_492_is_original_provenance(self) -> None:
        self.assertEqual(
            ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
            492,
        )
        self.assertEqual(ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT, 574)
        family_trace = _synthetic_family_trace()
        self.assertEqual(
            family_trace["original_family_provenance"][
                "end_global_exposure_count"
            ],
            492,
        )
        trace = bind_analog_family_trace(
            family_trace=family_trace,
            mission_id=MISSION_ID,
            executable_id=self.executable_id,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )
        calculation = build_analog_trace_calculation(
            trace=trace,
            trace_output_name="trace.json",
            trace_hash=sha256(canonical_bytes(trace)).hexdigest(),
        )
        parameters = calculation["parameters"]
        statistics = calculation["statistics"]
        self.assertEqual(
            parameters["historical_context_prior_global_exposure_count"],
            574,
        )
        self.assertEqual(
            statistics["historical_context"],
            {
                "adjustment_authority": (
                    "context_only_never_adjustment_factor"
                ),
                "context_id": (
                    "historical-search:stu0061-prospective-replay-through-574"
                ),
                "prior_global_exposure_count": 574,
            },
        )
        self.assertEqual(
            statistics["selection_family"]["plan"]["family_size"],
            4,
        )
        self.assertEqual(
            statistics["selection_family"]["method"][
                "historical_exposure_adjustment"
            ],
            "forbidden",
        )
        self.assertNotIn("historical_context", statistics["selection_family"])
        self.assertEqual(
            statistics["exposure_semantics"],
            {
                "exact_concurrent_family_adjustment_factor": 4,
                "historical_context_adjustment_authority": (
                    "context_only_never_adjustment_factor"
                ),
                "original_family_end_global_exposure_count": 492,
                "prospective_prior_global_exposure_count": 574,
            },
        )

    def test_family_cache_computes_once_then_reuses_exact_bytes(self) -> None:
        family_trace = _synthetic_family_trace()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                analog_replay_module,
                "compute_analog_family_trace",
                return_value=(family_trace, {}),
            ) as compute:
                produced = load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=True,
                )
                reused = load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=(produced.sha256,),
                )
            self.assertEqual(compute.call_count, 1)
            self.assertTrue(produced.produced)
            self.assertFalse(reused.produced)
            self.assertEqual(produced.content, reused.content)
            self.assertEqual(
                (root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).read_bytes(),
                produced.content,
            )
            plan = build_analog_replay_plan(
                mission_id=MISSION_ID,
                study_id=STUDY_ID,
                executable_id=self.executable_id,
            )
            self.assertEqual(
                plan.expected_output_classes(produce_family_cache=True)[
                    ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
                ],
                "reproducible_cache",
            )
            self.assertEqual(
                len(plan.expected_outputs(produce_family_cache=True)),
                6,
            )
            self.assertEqual(len(plan.expected_outputs()), 5)
            self.assertNotIn(
                ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
                plan.expected_outputs(),
            )

    def test_cache_manifest_is_first_subject_trace_and_hash_pair_is_atomic(
        self,
    ) -> None:
        (
            family_cache,
            execution,
            producer_trace,
            trace_content,
            trace_hash,
        ) = self._producer_cache_capability()
        manifest = extract_analog_family_trace_cache_manifest(producer_trace)
        self.assertEqual(manifest["cache_sha256"], family_cache.sha256)
        neutral, material_manifest = extract_analog_family_trace_cache_material(
            producer_trace,
            require_producer=True,
        )
        self.assertEqual(canonical_bytes(neutral), family_cache.content)
        self.assertEqual(material_manifest, manifest)
        self.assertEqual(
            canonical_bytes(
                extract_analog_family_trace_from_subject(producer_trace)
            ),
            family_cache.content,
        )
        self.assertEqual(
            extract_analog_family_trace_cache_binding(producer_trace),
            manifest,
        )
        self.assertEqual(
            manifest["producer_execution"],
            {**execution.payload(), "identity": execution.identity},
        )
        self.assertNotIn("job_id", family_cache.trace())
        self.assertEqual(sha256(trace_content).hexdigest(), trace_hash)
        consumer_id = str(
            expected_analog_family_inventory()[1]["executable_id"]
        )
        consumer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=consumer_id,
        )
        inputs = consumer_plan.job_input_hashes(
            family_trace_cache_hash=family_cache.sha256,
            family_trace_manifest_hash=trace_hash,
        )
        self.assertEqual(inputs.count(family_cache.sha256), 1)
        self.assertEqual(inputs.count(trace_hash), 1)
        with self.assertRaisesRegex(ValueError, "inseparable"):
            consumer_plan.job_input_hashes(
                family_trace_cache_hash=family_cache.sha256,
            )
        with self.assertRaisesRegex(ValueError, "must differ"):
            consumer_plan.job_input_hashes(
                family_trace_cache_hash=family_cache.sha256,
                family_trace_manifest_hash=family_cache.sha256,
            )

    def test_cache_consumer_requires_trace_and_writer_producer_capability(
        self,
    ) -> None:
        (
            family_cache,
            execution,
            producer_trace,
            trace_content,
            trace_hash,
        ) = self._producer_cache_capability()
        consumer_id = str(
            expected_analog_family_inventory()[1]["executable_id"]
        )
        consumer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=consumer_id,
        )
        inputs = consumer_plan.job_input_hashes(
            family_trace_cache_hash=family_cache.sha256,
            family_trace_manifest_hash=trace_hash,
        )
        writer = _FakeWriter({trace_hash: trace_content})
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                analog_replay_module,
                "compute_analog_family_trace",
            ) as compute:
                observed_cache, observed_hash, observed_manifest = (
                    verify_analog_family_trace_cache_producer(
                        writer,  # type: ignore[arg-type]
                        replay_plan=consumer_plan,
                        repository_root=root,
                        input_hashes=inputs,
                    )
                )
            compute.assert_not_called()
            self.assertEqual(
                (root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).read_bytes(),
                family_cache.content,
            )
        self.assertEqual(observed_cache, family_cache)
        self.assertEqual(observed_hash, trace_hash)
        self.assertEqual(
            observed_manifest,
            extract_analog_family_trace_cache_manifest(producer_trace),
        )
        self.assertEqual(len(writer.producer_calls), 1)
        observed_execution, observed_arguments = writer.producer_calls[0]
        self.assertEqual(observed_execution, execution)
        self.assertEqual(observed_arguments["cache_hash"], family_cache.sha256)
        self.assertEqual(observed_arguments["manifest_hash"], trace_hash)
        rejecting_writer = _FakeWriter(
            {trace_hash: trace_content},
            producer_error=ValueError("producer capability unavailable"),
        )
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "capability unavailable"):
                verify_analog_family_trace_cache_producer(
                    rejecting_writer,  # type: ignore[arg-type]
                    replay_plan=consumer_plan,
                    repository_root=temporary,
                    input_hashes=inputs,
                )

    def test_durable_producer_allows_absent_cache_but_rejects_existing_tamper(
        self,
    ) -> None:
        (
            family_cache,
            _,
            _,
            trace_content,
            trace_hash,
        ) = self._producer_cache_capability()
        consumer_id = str(
            expected_analog_family_inventory()[1]["executable_id"]
        )
        consumer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=consumer_id,
        )
        inputs = consumer_plan.job_input_hashes(
            family_trace_cache_hash=family_cache.sha256,
            family_trace_manifest_hash=trace_hash,
        )
        writer = _FakeWriter({trace_hash: trace_content})
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            recovered, _, _ = verify_analog_family_trace_cache_producer(
                writer,  # type: ignore[arg-type]
                replay_plan=consumer_plan,
                repository_root=root,
                input_hashes=inputs,
                materialize_missing=False,
            )
            self.assertEqual(recovered, family_cache)
            target = root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
            self.assertFalse(target.exists())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"tampered-cache")
            with self.assertRaisesRegex(ValueError, "different bytes"):
                verify_analog_family_trace_cache_producer(
                    writer,  # type: ignore[arg-type]
                    replay_plan=consumer_plan,
                    repository_root=root,
                    input_hashes=inputs,
                    materialize_missing=False,
                )

    def test_executor_produces_once_then_reuses_authorized_cache(self) -> None:
        producer_id = str(
            expected_analog_family_inventory()[0]["executable_id"]
        )
        consumer_id = str(
            expected_analog_family_inventory()[1]["executable_id"]
        )
        producer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=producer_id,
        )
        consumer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=consumer_id,
        )
        producer_execution = RunningJobExecution(
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            job_permit_id="b" * 64,
            start_record_id="c" * 64,
        )
        consumer_execution = RunningJobExecution(
            job_id="job:" + "e" * 64,
            job_hash="f" * 64,
            job_permit_id="1" * 64,
            start_record_id="2" * 64,
        )
        writer = _FakeWriter({})
        writer.running_bindings[producer_execution.job_id] = {
            "mission_id": MISSION_ID,
            "study_id": STUDY_ID,
            "spec": {
                "evidence_subject": {"kind": "Executable", "id": producer_id},
                "expected_outputs": list(
                    producer_plan.expected_outputs(produce_family_cache=True)
                ),
                "input_hashes": list(producer_plan.job_input_hashes()),
                "output_classes": producer_plan.expected_output_classes(
                    produce_family_cache=True
                ),
            },
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(
                    analog_replay_module,
                    "StateWriter",
                    return_value=writer,
                ),
                patch.object(
                    analog_replay_module,
                    "compute_analog_family_trace",
                    return_value=(_synthetic_family_trace(), {}),
                ) as compute,
            ):
                producer_packet = execute_analog_replay_job(
                    repository_root=root,
                    execution=producer_execution,
                )
                producer_outputs = producer_packet.outputs()
                cache_hash = producer_outputs[
                    ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
                ]
                producer_trace_hash = producer_outputs[
                    producer_plan.output_names["trace"]
                ]
                consumer_inputs = consumer_plan.job_input_hashes(
                    family_trace_cache_hash=cache_hash,
                    family_trace_manifest_hash=producer_trace_hash,
                )
                (root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).unlink()
                writer.running_bindings[consumer_execution.job_id] = {
                    "mission_id": MISSION_ID,
                    "study_id": STUDY_ID,
                    "spec": {
                        "evidence_subject": {
                            "kind": "Executable",
                            "id": consumer_id,
                        },
                        "expected_outputs": list(
                            consumer_plan.expected_outputs()
                        ),
                        "input_hashes": list(consumer_inputs),
                        "output_classes": (
                            consumer_plan.expected_output_classes()
                        ),
                    },
                }
                consumer_packet = execute_analog_replay_job(
                    repository_root=root,
                    execution=consumer_execution,
                )
                self.assertEqual(
                    sha256(
                        (root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).read_bytes()
                    ).hexdigest(),
                    cache_hash,
                )
        self.assertEqual(compute.call_count, 1)
        self.assertNotIn(
            ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
            consumer_packet.outputs(),
        )
        self.assertEqual(len(writer.producer_calls), 1)
        self.assertEqual(
            writer.producer_calls[0][1]["manifest_hash"],
            producer_trace_hash,
        )
        producer_trace = analog_replay_module.parse_canonical(
            writer.evidence.read_verified(producer_trace_hash)
        )
        self.assertEqual(
            extract_analog_family_trace_cache_manifest(producer_trace)[
                "cache_sha256"
            ],
            cache_hash,
        )

    def test_cache_consumer_rejects_missing_duplicate_and_forged_provenance(
        self,
    ) -> None:
        (
            family_cache,
            _,
            producer_trace,
            trace_content,
            trace_hash,
        ) = self._producer_cache_capability()
        consumer_id = str(
            expected_analog_family_inventory()[1]["executable_id"]
        )
        consumer_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=consumer_id,
        )
        writer = _FakeWriter({trace_hash: trace_content})
        for inputs, message in (
            ((family_cache.sha256,), "one exact.*producer trace"),
            ((trace_hash,), "cache hash must be exactly one"),
            (
                (family_cache.sha256, family_cache.sha256, trace_hash),
                "cache hash must be exactly one",
            ),
            (
                (family_cache.sha256, trace_hash, trace_hash),
                "producer trace must be exactly one",
            ),
        ):
            with self.subTest(inputs=inputs):
                with TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, message):
                        verify_analog_family_trace_cache_producer(
                            writer,  # type: ignore[arg-type]
                            replay_plan=consumer_plan,
                            repository_root=temporary,
                            input_hashes=inputs,
                        )

        forged_values: list[tuple[str, dict[str, object], str]] = []
        tampered = deepcopy(producer_trace)
        tampered["attribution"]["family_trace_binding"]["cache_manifest"][
            "cache_sha256"
        ] = "f" * 64
        forged_values.append(("tampered", tampered, "producer trace is invalid"))
        wrong_producer = deepcopy(producer_trace)
        wrong_producer["attribution"]["family_trace_binding"][
            "cache_manifest"
        ]["producer_executable_id"] = consumer_id
        forged_values.append(
            ("wrong producer", wrong_producer, "producer trace is invalid")
        )
        wrong_study = deepcopy(producer_trace)
        wrong_study["attribution"]["family_trace_binding"]["cache_manifest"][
            "study_id"
        ] = "STU-WRONG"
        forged_values.append(
            ("wrong Study", wrong_study, "manifest is out of scope")
        )
        for name, forged, message in forged_values:
            forged_content = canonical_bytes(forged)
            forged_hash = sha256(forged_content).hexdigest()
            forged_writer = _FakeWriter({forged_hash: forged_content})
            with self.subTest(name=name):
                with TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, message):
                        verify_analog_family_trace_cache_producer(
                            forged_writer,  # type: ignore[arg-type]
                            replay_plan=consumer_plan,
                            repository_root=temporary,
                            input_hashes=(family_cache.sha256, forged_hash),
                        )

    def test_legacy_compute_wrapper_binds_without_mutating_family_bytes(self) -> None:
        family_trace = _synthetic_family_trace()
        original_bytes = canonical_bytes(family_trace)
        legacy_metrics = {"marker": {"trade_count": 1}}
        with patch.object(
            analog_replay_module,
            "compute_analog_family_trace",
            return_value=(family_trace, legacy_metrics),
        ) as compute:
            trace, observed_metrics = compute_analog_replay_trace(
                Path("."),
                mission_id=MISSION_ID,
                executable_id=self.executable_id,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )
        self.assertEqual(compute.call_count, 1)
        self.assertEqual(observed_metrics, legacy_metrics)
        self.assertEqual(trace["subject_executable_id"], self.executable_id)
        self.assertEqual(canonical_bytes(family_trace), original_bytes)

    def test_family_cache_fail_closed_for_missing_tamper_stale_and_unbound(self) -> None:
        family_trace = _synthetic_family_trace()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=("0" * 64,),
                )
            with patch.object(
                analog_replay_module,
                "compute_analog_family_trace",
                return_value=(family_trace, {}),
            ):
                produced = load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=True,
                )
            with self.assertRaisesRegex(ValueError, "exactly one Job input"):
                load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=(),
                )
            target = root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
            target.write_bytes(produced.content + b" ")
            with self.assertRaisesRegex(ValueError, "exactly one Job input"):
                load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=(produced.sha256,),
                )
            stale = deepcopy(family_trace)
            stale["implementation_identities"]["analog_replay_sha256"] = (
                "f" * 64
            )
            stale_bytes = canonical_bytes(stale)
            target.write_bytes(stale_bytes)
            with self.assertRaisesRegex(ValueError, "implementation is stale"):
                load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=(sha256(stale_bytes).hexdigest(),),
                )
            wrong_family = deepcopy(family_trace)
            wrong_family["family_id"] = "family:wrong"
            wrong_bytes = canonical_bytes(wrong_family)
            target.write_bytes(wrong_bytes)
            with self.assertRaisesRegex(ValueError, "not the P1 replay family"):
                load_or_compute_analog_family_trace(
                    root,
                    produce_family_cache=False,
                    input_hashes=(sha256(wrong_bytes).hexdigest(),),
                )

    def test_plan_recomputes_all_original_criteria_with_four_honest_modes(self) -> None:
        replay_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.executable_id,
        )
        self.assertEqual(len(ANALOG_REPLAY_CRITERIA), 20)
        self.assertEqual(
            {item["criterion_id"] for item in replay_plan.plan["criteria"]},
            {item["criterion_id"] for item in ANALOG_REPLAY_CRITERIA},
        )
        self.assertEqual(
            tuple(replay_plan.plan["evidence_modes"]),
            ANALOG_REPLAY_EVIDENCE_MODES,
        )
        self.assertEqual(len(replay_plan.plan["proof_requirements"]), 8)
        self.assertEqual(
            len(
                {
                    item["output_name"]
                    for item in replay_plan.plan["proof_requirements"]
                }
            ),
            2,
        )
        self.assertNotIn(
            ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
            {
                item["output_name"]
                for item in replay_plan.plan["proof_requirements"]
            },
        )

    def test_family_exposes_one_self_checked_factorial_study_chassis(self) -> None:
        chassis = analog_replay_controlled_chassis(P1_STU0061_ANALOG_FAMILY)
        self.assertEqual(
            [item.value for item in chassis.changed_domains],
            ["feature", "synthesis", "trade"],
        )
        self.assertEqual(
            [item.value for item in chassis.controlled_domains],
            [
                "execution",
                "label",
                "lifecycle",
                "model",
                "portfolio",
                "risk",
                "selector",
            ],
        )
        for executable_id in self.mapping:
            configuration = self.mapping[executable_id]
            validate_controlled_executable(
                chassis.to_identity_payload(),
                analog_family_module.analog_family_executable(configuration),
            )

    def test_prospective_modules_have_no_static_control_ids(self) -> None:
        for module in (
            analog_family_module,
            analog_replay_module,
            analog_trace_module,
        ):
            self.assertEqual(
                _hardcoded_control_ids(Path(module.__file__).read_bytes()),
                (),
            )

    def test_frozen_raw_metric_parity_guard_is_member_specific(self) -> None:
        observed = {
            executable_id: dict(
                FROZEN_STU0061_RAW_METRICS[
                    str(configuration.historical_reference_executable_id)
                ]
            )
            for executable_id, configuration in self.mapping.items()
        }
        assert_frozen_stu0061_raw_metric_parity(observed)
        observed[self.executable_id]["trade_count"] += 1
        with self.assertRaisesRegex(ValueError, "raw metric parity drifted"):
            assert_frozen_stu0061_raw_metric_parity(observed)

    def _request(
        self,
        root: Path,
        executable_id: str | None = None,
        *,
        trace_override: dict[str, object] | None = None,
    ) -> EvidenceValidationRequest:
        subject_id = self.executable_id if executable_id is None else executable_id
        replay_plan = build_analog_replay_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=subject_id,
        )
        trace = (
            _synthetic_trace(subject_id)
            if trace_override is None
            else trace_override
        )
        trace_bytes = canonical_bytes(trace)
        trace_hash = sha256(trace_bytes).hexdigest()
        calculation = build_analog_trace_calculation(
            trace=trace,
            trace_output_name=replay_plan.output_names["trace"],
            trace_hash=trace_hash,
        )
        calculation_bytes = canonical_bytes(calculation)
        calculation_hash = sha256(calculation_bytes).hexdigest()
        measurement = build_analog_replay_measurement(
            replay_plan=replay_plan,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            calculation=calculation,
            trace_hash=trace_hash,
            calculation_hash=calculation_hash,
        )
        measurement_bytes = canonical_bytes(measurement)
        measurement_hash = sha256(measurement_bytes).hexdigest()
        result = build_analog_replay_result(
            replay_plan=replay_plan,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            measurement_hash=measurement_hash,
        )
        payloads = {
            replay_plan.output_names["calculation"]: calculation_bytes,
            replay_plan.output_names["measurement"]: measurement_bytes,
            replay_plan.output_names["plan"]: canonical_bytes(replay_plan.plan),
            replay_plan.output_names["result"]: canonical_bytes(result),
            replay_plan.output_names["trace"]: trace_bytes,
        }
        artifacts = []
        for index, (output_name, content) in enumerate(payloads.items()):
            path = root / f"artifact-{index}.json"
            path.write_bytes(content)
            artifacts.append(
                ValidationArtifact(
                    output_name=output_name,
                    sha256=sha256(content).hexdigest(),
                    _source=path,
                )
            )
        return EvidenceValidationRequest(
            domain="scientific",
            validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            validation_plan_hash=replay_plan.plan_hash,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            mission_id=MISSION_ID,
            evidence_subject={"kind": "Executable", "id": subject_id},
            binding=replay_plan.scientific_binding(),
            result_manifest=result,
            artifacts=tuple(artifacts),
        )

    def test_validator_opens_trace_and_recomputes_metrics_and_resampling(self) -> None:
        runs = []
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for executable_id in self.mapping:
                request = self._request(root, executable_id)
                validated = ScientificAdjudicationValidatorV2().validate(
                    request
                )
                runs.append((executable_id, request, validated))
        for executable_id, request, validated in runs:
            self.assertEqual(
                request.evidence_subject,
                {"kind": "Executable", "id": executable_id},
            )
            self.assertEqual(
                validated.facts["executed_evidence_modes"],
                list(ANALOG_REPLAY_EVIDENCE_MODES),
            )
            self.assertEqual(len(request.artifacts), 5)
            self.assertTrue(
                all(artifact.was_read for artifact in request.artifacts)
            )
            self.assertEqual(
                validated_stu0061_recomputed_criterion_ids(validated.facts),
                STU0061_REPLAY_CRITERION_IDS,
            )
        validated = runs[0][2]
        adjudication = validated.facts["scientific_adjudication"]
        self.assertTrue(
            any(
                item["comparison_state"] == "failed"
                for item in adjudication["criteria"]
            )
        )
        incomplete_adjudication = dict(adjudication)
        incomplete_adjudication["criteria"] = [
            dict(item) for item in adjudication["criteria"][:-1]
        ]
        incomplete = {
            "executed_evidence_modes": list(
                validated.facts["executed_evidence_modes"]
            ),
            "scientific_adjudication": incomplete_adjudication,
        }
        with self.assertRaisesRegex(ValueError, "inventory is incomplete"):
            validated_stu0061_recomputed_criterion_ids(incomplete)

    def test_validator_accepts_first_subject_trace_as_cache_manifest(self) -> None:
        _, _, producer_trace, _, _ = self._producer_cache_capability()
        producer_id = str(
            expected_analog_family_inventory()[0]["executable_id"]
        )
        with TemporaryDirectory() as temporary:
            request = self._request(
                Path(temporary),
                producer_id,
                trace_override=producer_trace,
            )
            validated = ScientificAdjudicationValidatorV2().validate(request)
        self.assertEqual(
            validated_stu0061_recomputed_criterion_ids(validated.facts),
            STU0061_REPLAY_CRITERION_IDS,
        )

    def test_trade_cost_tamper_is_rejected_even_when_artifact_hash_is_updated(self) -> None:
        direct = _synthetic_family_trace()
        direct_row = direct["trade_observations"][0]
        direct_row["native_net_pnl_micropoints"] += 1
        direct_row["observation_id"] = analog_observation_id("trade", direct_row)
        with self.assertRaisesRegex(ValueError, "cost arithmetic"):
            bind_analog_family_trace(
                family_trace=direct,
                mission_id=MISSION_ID,
                executable_id=self.executable_id,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )
        with TemporaryDirectory() as temporary:
            request = self._request(Path(temporary))
            artifacts = list(request.artifacts)
            trace_index = next(
                index
                for index, artifact in enumerate(artifacts)
                if artifact.output_name.endswith("evaluation-trace.json")
            )
            trace = _synthetic_trace(self.executable_id)
            trace["trade_observations"][0]["native_net_pnl_micropoints"] += 1
            content = canonical_bytes(trace)
            path = Path(temporary) / "tampered-trace.json"
            path.write_bytes(content)
            artifacts[trace_index] = ValidationArtifact(
                output_name=artifacts[trace_index].output_name,
                sha256=sha256(content).hexdigest(),
                _source=path,
            )
            request = replace(request, artifacts=tuple(artifacts))
            with self.assertRaises(EvidenceValidationError):
                ScientificAdjudicationValidatorV2().validate(request)

    def test_missing_zero_day_and_historical_reference_drift_are_rejected(self) -> None:
        trace = _synthetic_family_trace()
        trace["eligible_day_observations"].pop()
        with self.assertRaisesRegex(ValueError, "calendar is incomplete"):
            bind_analog_family_trace(
                family_trace=trace,
                mission_id=MISSION_ID,
                executable_id=self.executable_id,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )
        trace = _synthetic_family_trace()
        trace["ordered_family"][0]["historical_reference_executable_id"] = (
            "executable:" + "f" * 64
        )
        with self.assertRaisesRegex(ValueError, "mapping drifted"):
            bind_analog_family_trace(
                family_trace=trace,
                mission_id=MISSION_ID,
                executable_id=self.executable_id,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )


if __name__ == "__main__":
    unittest.main()
