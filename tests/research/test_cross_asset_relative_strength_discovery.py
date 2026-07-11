from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.research import cross_asset_relative_strength_discovery as subject
from axiom_rift.research.cross_asset_relative_strength_study import (
    EVIDENCE_DEPTH,
    EVIDENCE_MODES,
    MISSION_ID,
    PLANNED_CLAIMS,
    build_cross_asset_relative_strength_validation_plan,
    build_measurement,
    build_result_manifest,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    ScientificDiscoveryValidator,
)
from axiom_rift.research.us500_source import US500_COLUMNS, US500_RAW_RELATIVE_PATH


def _target_frame(count: int, *, start: str = "2025-01-01 00:00:00") -> pd.DataFrame:
    time = pd.date_range(start, periods=count, freq="5min")
    wave = np.sin(np.arange(count, dtype=float) / 17.0)
    close = 20_000.0 + np.cumsum(0.15 + 0.4 * wave)
    return pd.DataFrame(
        {
            "time": time,
            "open": close - 0.05,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "tick_volume": np.full(count, 100.0),
            "spread": np.full(count, 1.0),
        }
    )


def _source_frame(target: pd.DataFrame) -> pd.DataFrame:
    count = len(target)
    wave = np.cos(np.arange(count, dtype=float) / 13.0)
    close = 5_000.0 + np.cumsum(0.04 + 0.18 * wave)
    return pd.DataFrame({"time": target["time"].copy(), "close": close})


def _raw_row(stamp: str, close: str = "5000.00") -> bytes:
    return (
        f"{stamp},5000.00,5001.00,4999.00,{close},100,1,0\n"
    ).encode("ascii")


class CrossAssetRelativeStrengthDiscoveryTests(unittest.TestCase):
    def test_exact_twelve_identities_bind_dynamic_source_and_raw_bytes(self) -> None:
        configurations = subject.cross_asset_relative_strength_configurations()
        raw = "a" * 64
        executables = [
            subject.cross_asset_relative_strength_executable(configuration, raw)
            for configuration in configurations
        ]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        expected_profiles = {
            "relative_strength_12_joint",
            "us500_direction_12_source_only",
            "us100_direction_12_target_only",
        }
        self.assertEqual({item.profile for item in configurations}, expected_profiles)
        source_id = subject.us500_source_contract().source_contract_id
        self.assertTrue(all(item.source_contracts == (source_id,) for item in executables))
        self.assertTrue(
            all(item.data_contract == f"data:{subject.OBSERVED_MATERIAL_ID}" for item in executables)
        )
        self.assertTrue(
            all(item.parameter_values()["source_raw_sha256"] == raw for item in executables)
        )
        self.assertTrue(
            all(
                item.parameter_values()["source_contract_identities"]
                == subject._source_identity_payload()
                for item in executables
            )
        )
        changed = subject.cross_asset_relative_strength_executable(
            configurations[0], "b" * 64
        )
        self.assertNotEqual(executables[0].identity, changed.identity)
        payload = executables[0].to_identity_payload()
        encoded = canonical_bytes(payload)
        self.assertIn(raw.encode("ascii"), encoded)
        for value in subject._source_identity_payload().values():
            self.assertIn(value.encode("ascii"), encoded)

    def test_byte_gate_hashes_tail_but_never_sends_tail_values_to_parser(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / US500_RAW_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            content = b",".join(name.encode("ascii") for name in US500_COLUMNS) + b"\n"
            content += _raw_row("2026.04.30 23:45:00")
            content += _raw_row("2026.04.30 23:50:00")
            content += _raw_row("2026.04.30 23:55:00")
            content += _raw_row("2026.05.01 00:00:00", "TAIL_SENTINEL")
            path.write_bytes(content)
            digest = sha256(content).hexdigest()
            original = subject.pd.read_csv

            def guarded(stream, *args, **kwargs):
                parser_bytes = stream.getvalue()
                self.assertNotIn(b"TAIL_SENTINEL", parser_bytes)
                self.assertNotIn(b"2026.05.01 00:00:00", parser_bytes)
                return original(stream, *args, **kwargs)

            with patch.object(subject.pd, "read_csv", side_effect=guarded) as parser:
                loaded = subject.load_us500_observed_development(
                    root, expected_raw_sha256=digest
                )
            self.assertEqual(len(loaded.frame), 3)
            self.assertEqual(loaded.metadata.raw_sha256, digest)
            self.assertEqual(loaded.metadata.last_time, subject.DEVELOPMENT_END)
            parser.assert_called_once()

            with patch.object(subject.pd, "read_csv") as forbidden_parser:
                with self.assertRaises(subject.CrossAssetRelativeStrengthBoundaryError):
                    subject.load_us500_observed_development(
                        root, expected_raw_sha256="0" * 64
                    )
            forbidden_parser.assert_not_called()

    def test_exact_inner_join_resets_feature_run_on_either_gap(self) -> None:
        target = _target_frame(160)
        source = _source_frame(target).drop(index=60).reset_index(drop=True)
        joined = subject._join_exact(target, source)
        features = subject.compute_relative_strength_features(joined)
        after_gap = int(joined.index[joined["target_index"] == 61][0])
        self.assertEqual(features.joint_run[after_gap], 1)
        self.assertTrue(np.isnan(features.relative_strength_12_joint[after_gap]))
        rewarmed = int(joined.index[joined["target_index"] == 109][0])
        self.assertEqual(features.joint_run[rewarmed], 49)
        self.assertTrue(np.isfinite(features.relative_strength_12_joint[rewarmed]))
        self.assertEqual(len(joined), len(target) - 1)

    def test_hold_uses_original_us100_timestamps_not_joined_positions(self) -> None:
        target = _target_frame(110)
        source = _source_frame(target).drop(index=60).reset_index(drop=True)
        joined = subject._join_exact(target, source)
        scores = np.full(len(joined), np.nan)
        decision_joined = int(joined.index[joined["target_index"] == 55][0])
        scores[decision_joined] = 2.0
        volatility = np.full(len(joined), 0.01)
        run = np.full(len(joined), 49, dtype=np.int32)
        configuration = subject.CrossAssetRelativeStrengthConfiguration(
            "relative_strength_12_joint", 1, 24
        )
        result = subject.simulate_cross_asset_fixed_hold(
            target_frame=target,
            joined_frame=joined,
            score=scores,
            us100_volatility=volatility,
            joint_run=run,
            threshold=1.0,
            configuration=configuration,
            test_start=pd.Timestamp(target["time"].iloc[0]),
            test_end=pd.Timestamp(target["time"].iloc[-1]),
            fold_id="synthetic",
            regime_cutoffs=(0.005, 0.02),
            effective_spread=np.ones(len(target)),
        )
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade["entry_time"], target["time"].iloc[56])
        self.assertEqual(trade["exit_time"], target["time"].iloc[80])
        self.assertNotIn(target["time"].iloc[60], source["time"].tolist())

    def test_feature_formula_uses_r12_and_sample_sigma48(self) -> None:
        target = _target_frame(100)
        source = _source_frame(target)
        joined = subject._join_exact(target, source)
        features = subject.compute_relative_strength_features(joined)
        index = 80
        target_log = np.log(joined["us100_close"].to_numpy(dtype=float))
        source_log = np.log(joined["us500_close"].to_numpy(dtype=float))
        target_one = np.diff(target_log)
        source_one = np.diff(source_log)
        target_sigma = target_one[index - 48 : index].std(ddof=1)
        source_sigma = source_one[index - 48 : index].std(ddof=1)
        target_z = (target_log[index] - target_log[index - 12]) / (
            target_sigma * np.sqrt(12)
        )
        source_z = (source_log[index] - source_log[index - 12]) / (
            source_sigma * np.sqrt(12)
        )
        self.assertAlmostEqual(
            features.us100_direction_12_target_only[index], target_z, places=12
        )
        self.assertAlmostEqual(
            features.us500_direction_12_source_only[index], source_z, places=12
        )
        self.assertAlmostEqual(
            features.relative_strength_12_joint[index], source_z - target_z, places=12
        )

    def test_heavy_synthetic_surface_and_bound_projection(self) -> None:
        count = 26_000
        rng = np.random.default_rng(812_204)
        time = pd.date_range("2025-01-01 00:00:00", periods=count, freq="5min")
        source_returns = rng.normal(0.000002, 0.00025, count)
        target_returns = 0.75 * source_returns + rng.normal(0.000001, 0.00018, count)
        source_close = 5_000.0 * np.exp(np.cumsum(source_returns))
        target_close = 20_000.0 * np.exp(np.cumsum(target_returns))
        target = pd.DataFrame(
            {
                "time": time,
                "open": target_close,
                "high": target_close + 0.5,
                "low": target_close - 0.5,
                "close": target_close,
                "tick_volume": np.full(count, 100.0),
                "spread": np.full(count, 1.0),
            }
        )
        source = pd.DataFrame({"time": time, "close": source_close})
        folds = (
            {
                "fold_id": "syn_001",
                "train_is": {
                    "start": str(time[0]),
                    "end": str(time[14_999]),
                    "row_count": 15_000,
                },
                "test_oos": {
                    "start": str(time[15_000]),
                    "end": str(time[-1]),
                    "row_count": count - 15_000,
                },
            },
        )
        raw = "c" * 64
        prefix = "d" * 64
        with patch.object(subject, "SELECTION_BOOTSTRAP_SAMPLES", 199), patch.object(
            subject, "SELECTION_TOTAL_EXPOSURES", 12
        ):
            surface = subject._surface_from_frames(
                target_frame=target,
                source_frame=source,
                folds=folds,
                raw_sha256=raw,
                source_prefix_sha256=prefix,
            )
            self.assertEqual(surface["schema"], "cross_asset_relative_strength_surface.v1")
            self.assertEqual(len(surface["evaluations"]), 12)
            self.assertEqual(
                {item["subject_configuration_id"].split("-inverted")[0].split("-routed")[0] for item in surface["evaluations"]},
                {
                    "relative_strength_12_joint",
                    "us500_direction_12_source_only",
                    "us100_direction_12_target_only",
                },
            )
            self.assertTrue(
                all("daily_entries_p90_milli" in item["metrics"] for item in surface["evaluations"])
            )
            execution_payload = {
                "job_hash": "1" * 64,
                "job_id": "job:" + "2" * 64,
                "job_permit_id": "3" * 64,
                "start_record_id": "4" * 64,
            }
            job_execution = {
                **execution_payload,
                "identity": canonical_digest(
                    domain="running-job-execution", payload=execution_payload
                ),
            }
            surface_hash = sha256(canonical_bytes(surface)).hexdigest()
            executable_id = surface["evaluations"][0]["subject_executable_id"]
            evaluation = subject.project_cross_asset_relative_strength_evaluation(
                surface,
                job_execution=job_execution,
                subject_executable_id=executable_id,
                surface_artifact_hash=surface_hash,
                surface_manifest_hash="e" * 64,
            )
            self.assertEqual(
                evaluation["schema"], "cross_asset_relative_strength_evaluation.v1"
            )
            self.assertNotIn("source_raw_sha256", evaluation)
            self.assertNotIn("source_contract_identities", evaluation)
            self.assertNotIn("source_development_prefix_sha256", evaluation)
            with TemporaryDirectory() as evidence_temporary:
                evidence_root = Path(evidence_temporary)
                validator_evaluation = dict(evaluation)
                validator_evaluation["fold_metrics"] = [
                    {
                        **dict(evaluation["fold_metrics"][0]),
                        "fold_id": f"rw_{index:03d}",
                    }
                    for index in range(1, 10)
                ]
                validator_evaluation["selection_method"] = {
                    **dict(evaluation["selection_method"]),
                    "bootstrap_samples": 41_999,
                    "total_exposures": 234,
                }

                def artifact(output_name: str, value: object) -> ValidationArtifact:
                    content = canonical_bytes(value)
                    digest = sha256(content).hexdigest()
                    path = evidence_root / f"{digest}.json"
                    path.write_bytes(content)
                    return ValidationArtifact(
                        output_name=output_name,
                        sha256=digest,
                        _source=path,
                    )

                plan = build_cross_asset_relative_strength_validation_plan(executable_id)
                plan_artifact = artifact("evidence/plan", plan)
                evaluation_artifact = artifact(
                    "evidence/evaluation", validator_evaluation
                )
                measurement = build_measurement(
                    executable_id=executable_id,
                    job_id=execution_payload["job_id"],
                    job_hash=execution_payload["job_hash"],
                    evaluation_artifact_hash=evaluation_artifact.sha256,
                    evaluation=validator_evaluation,
                )
                measurement_artifact = artifact("evidence/measurement", measurement)
                result = build_result_manifest(
                    executable_id=executable_id,
                    job_id=execution_payload["job_id"],
                    job_hash=execution_payload["job_hash"],
                    measurement_artifact_hash=measurement_artifact.sha256,
                )
                result_artifact = artifact("evidence/result", result)
                request_result = parse_canonical(canonical_bytes(result))
                self.assertIsInstance(request_result, dict)
                request = EvidenceValidationRequest(
                    domain="scientific",
                    validator_id=SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
                    validation_plan_hash=plan_artifact.sha256,
                    job_id=execution_payload["job_id"],
                    job_hash=execution_payload["job_hash"],
                    mission_id=MISSION_ID,
                    evidence_subject={"kind": "Executable", "id": executable_id},
                    binding={
                        "evidence_depth": EVIDENCE_DEPTH,
                        "evidence_modes": list(EVIDENCE_MODES),
                        "planned_claims": list(PLANNED_CLAIMS),
                        "result_manifest_output": "evidence/result",
                        "validation_plan_hash": plan_artifact.sha256,
                        "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
                    },
                    result_manifest=request_result,
                    artifacts=(
                        result_artifact,
                        plan_artifact,
                        evaluation_artifact,
                        measurement_artifact,
                    ),
                )
                validated, trace = EvidenceValidatorRegistry(
                    (ScientificDiscoveryValidator(),)
                ).validate(request)
                self.assertIn(validated.verdict, {"passed", "failed", "not_evaluable"})
                self.assertTrue(validated.scientific_eligible)
                self.assertFalse(validated.candidate_eligible)
                self.assertEqual(trace.opened_artifact_count, 4)
            tampered = dict(surface)
            tampered["source_raw_sha256"] = "f" * 64
            with self.assertRaises(subject.CrossAssetRelativeStrengthBoundaryError):
                subject.project_cross_asset_relative_strength_evaluation(
                    tampered,
                    job_execution=job_execution,
                    subject_executable_id=executable_id,
                    surface_artifact_hash=surface_hash,
                    surface_manifest_hash="e" * 64,
                )

    def test_project_text_is_ascii(self) -> None:
        paths = (
            Path(subject.__file__),
            Path(__file__),
        )
        for path in paths:
            path.read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
