from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_DOCUMENTED_TIME_STANDARD,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
    SourceContractError,
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
    build_mt5_time_coordinate_probe_manifest,
)
from axiom_rift.research.us500_source_eligibility_validation import (
    SOURCE_ELIGIBILITY_VALIDATOR_ID,
    SourceEligibilityValidator,
)
from axiom_rift.research.us500_source import (
    US500_COLUMNS,
    US500SourceError,
    _completed_rate_epochs,
    audit_us500_historical_bytes,
    derive_runtime_facts,
    source_validation_plan_hash,
    us500_source_contract,
)


def runtime_probe() -> dict[str, object]:
    observed_at_utc = "2026-07-11T00:00:00Z"
    observed_epoch = int(
        datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00")).timestamp()
    )
    tick_epoch = observed_epoch + 10_800
    value = {
        "schema": "us500_runtime_probe_measurement.v2",
        "source_contract_id": us500_source_contract().source_contract_id,
        "observed_at_utc": observed_at_utc,
        "observed_utc_epoch_seconds": observed_epoch,
        "evidence_scope": "local_terminal_runtime_observation",
        "freshness_scope": "live_retrieval_latency_at_observed_at_utc",
        "time_coordinate": MT5_EPOCH_COORDINATE,
        "documented_time_standard": MT5_DOCUMENTED_TIME_STANDARD,
        "absolute_time_authority": MT5_ABSOLUTE_TIME_AUTHORITY,
        "offset_policy": MT5_OFFSET_POLICY,
        "broker_session_timezone_dst_authority": MT5_SESSION_TIME_AUTHORITY,
        "mt5_package_version": "5.0.fixture",
        "terminal_build": 5833,
        "connected": True,
        "server": "FPMarketsSC-Live",
        "symbol": "US500",
        "description": "US 500 Index Cash",
        "digits": 2,
        "point": "0.01",
        "tick_size": "0.01",
        "contract_size": "1.0",
        "rates_count": 8,
        "consecutive_closed_bars": True,
        "finite_tick": True,
        "market_closed": True,
        "closed_bar_available": True,
        "tick_mt5_epoch_seconds": tick_epoch,
        "latest_rate_mt5_epoch_seconds": tick_epoch - 300,
        "mt5_epoch_minus_observed_utc_seconds": 10_800,
        "mt5_epoch_sequence_coherent": True,
        "latest_closed_bar_mt5_epoch_coordinate": "2026-07-11T02:55:00",
        "retrieval_latency_ms": 5,
        "dtype_fields": list(US500_COLUMNS),
    }
    value["facts"] = derive_runtime_facts(value)
    return value


class US500SourceTests(unittest.TestCase):
    def test_runtime_integer_fields_reject_bool_without_coercion(self) -> None:
        integer_fields = (
            "digits",
            "latest_rate_mt5_epoch_seconds",
            "mt5_epoch_minus_observed_utc_seconds",
            "observed_utc_epoch_seconds",
            "rates_count",
            "retrieval_latency_ms",
            "terminal_build",
            "tick_mt5_epoch_seconds",
        )
        for field in integer_fields:
            for value in (False, True):
                with self.subTest(field=field, value=value):
                    probe = runtime_probe()
                    probe[field] = value
                    with self.assertRaisesRegex(
                        US500SourceError,
                        "integer fields",
                    ):
                        derive_runtime_facts(probe)

    def test_coordinate_probe_manifest_preserves_documented_and_observed_time(self) -> None:
        manifest = build_mt5_time_coordinate_probe_manifest(
            probes=(runtime_probe(),),
            independent_utc_observation={
                "source": "independent_UTC_clock_fixture",
                "observed_at_utc": "2026-07-11T00:00:01Z",
            },
        )
        content = canonical_bytes(manifest)
        self.assertTrue(content.isascii())
        entry = manifest["probes"][0]
        self.assertEqual(
            entry["documented_time_standard"], MT5_DOCUMENTED_TIME_STANDARD
        )
        self.assertEqual(
            entry["absolute_time_authority"], MT5_ABSOLUTE_TIME_AUTHORITY
        )
        self.assertEqual(entry["mt5_epoch_minus_observed_utc_seconds"], 10_800)
        self.assertEqual(
            entry["tick_mt5_epoch_seconds"]
            - entry["observed_utc_epoch_seconds"],
            10_800,
        )
        self.assertEqual(
            manifest["independent_utc_observation"]["observed_utc_epoch_seconds"],
            entry["observed_utc_epoch_seconds"] + 1,
        )
        self.assertEqual(
            manifest["independent_utc_observation_policy"],
            "asynchronous_sanity_check_no_latency_or_offset_inference",
        )
        with self.assertRaises(SourceContractError):
            build_mt5_time_coordinate_probe_manifest(
                probes=(runtime_probe(), runtime_probe())
            )

    def test_completed_bars_use_only_the_observed_mt5_coordinate(self) -> None:
        import numpy as np

        epochs = np.asarray([10800, 11100, 11400, 11700], dtype=np.int64)
        completed = _completed_rate_epochs(
            epochs,
            tick_mt5_epoch_seconds=12001,
        )
        self.assertEqual(completed.tolist(), [10800, 11100, 11400, 11700])

    def test_contract_binds_exact_broker_surface_and_plans(self) -> None:
        contract = us500_source_contract()
        self.assertEqual(contract.runtime_identifier, "US500")
        self.assertEqual(contract.mapping()["runtime_symbol"], "US500")
        self.assertEqual(contract.instrument()["asset_type"], "cash_index_cfd")
        self.assertIn(
            MT5_ABSOLUTE_TIME_AUTHORITY,
            contract.instrument()["timezone"],
        )
        self.assertEqual(
            contract.clock()["timezone_conversion"],
            "none_absolute_timezone_authority_unknown",
        )
        self.assertEqual(
            contract.clock()["broker_session_label_timezone_dst_authority"],
            MT5_SESSION_TIME_AUTHORITY,
        )
        self.assertEqual(
            contract.clock()["documented_time_standard"],
            MT5_DOCUMENTED_TIME_STANDARD,
        )
        self.assertEqual(contract.clock()["offset_policy"], MT5_OFFSET_POLICY)
        self.assertEqual(contract.schema()["columns"], list(US500_COLUMNS))
        self.assertNotEqual(
            source_validation_plan_hash("historical_audit"),
            source_validation_plan_hash("runtime_availability_proof"),
        )
        EvidenceValidatorRegistry((SourceEligibilityValidator(),))

    def test_small_historical_fixture_is_audited_but_not_eligible(self) -> None:
        raw = (
            ",".join(US500_COLUMNS)
            + "\n2018.05.07 01:00:00,1.00,1.10,0.90,1.05,10,1,0"
            + "\n2026.06.26 23:50:00,1.05,1.20,1.00,1.10,12,1,0\n"
        ).encode("ascii")
        measurement = audit_us500_historical_bytes(
            raw, observed_at_utc="2026-07-11T00:00:00Z"
        )
        self.assertEqual(measurement["row_count"], 2)
        self.assertFalse(measurement["facts"]["acquisition_observed"])
        self.assertEqual(
            measurement["evidence_scope"],
            "current_mt5_epoch_coordinate_history_reconstruction",
        )
        self.assertFalse(
            measurement["facts"]["information_complete_at_audited"]
        )
        self.assertFalse(measurement["facts"]["first_availability_audited"])
        self.assertFalse(
            measurement["facts"]["revision_or_vintage_audited"]
        )
        self.assertEqual(
            measurement["first_time_mt5_epoch_coordinate"],
            "2018-05-07T01:00:00",
        )
        self.assertEqual(
            measurement["timestamp_provenance"],
            "UTC_formatter_applied_to_MT5_epoch_absolute_timezone_unverified",
        )
        self.assertGreater(measurement["timestamp_gap_count"], 0)
        with self.assertRaisesRegex(SourceContractError, "point-in-time"):
            SourceEligibilityReceipt(
                source_contract_id=measurement["source_contract_id"],
                evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
                producer_completion_id="a" * 64,
                observed_at_utc=measurement["observed_at_utc"],
                artifact_hashes=(measurement["raw_sha256"],),
                facts=measurement["facts"],
            )

    def test_runtime_validator_derives_every_fact_and_reads_every_artifact(self) -> None:
        probe = runtime_probe()
        inconsistent_probe = dict(probe)
        inconsistent_probe["mt5_epoch_minus_observed_utc_seconds"] = 0
        self.assertFalse(
            derive_runtime_facts(inconsistent_probe)["local_realtime_retrieval"]
        )
        self.assertNotEqual(
            probe["freshness_scope"],
            "retrieval_observed_at_utc_not_historical_bar_availability",
        )
        reconstruction_labeled_probe = dict(probe)
        reconstruction_labeled_probe.update(
            {
                "evidence_scope": (
                    "current_mt5_epoch_coordinate_history_reconstruction"
                ),
                "freshness_scope": (
                    "retrieval_observed_at_utc_not_historical_bar_availability"
                ),
            }
        )
        reconstruction_facts = derive_runtime_facts(reconstruction_labeled_probe)
        self.assertFalse(reconstruction_facts["local_realtime_retrieval"])
        self.assertFalse(reconstruction_facts["fresh"])
        probe_bytes = canonical_bytes(probe)
        probe_hash = sha256(probe_bytes).hexdigest()
        result = {
            "schema": "source_eligibility_evidence.v1",
            "job_id": "job:" + "a" * 64,
            "job_hash": "a" * 64,
            "mission_id": "MIS-0006",
            "source_contract_id": us500_source_contract().source_contract_id,
            "transition_evidence": "runtime_availability_proof",
            "observed_at_utc": probe["observed_at_utc"],
            "facts": probe["facts"],
            "measurement_artifact_hashes": [probe_hash],
        }
        result_bytes = canonical_bytes(result)
        result_hash = sha256(result_bytes).hexdigest()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe_path = root / "probe.json"
            result_path = root / "result.json"
            probe_path.write_bytes(probe_bytes)
            result_path.write_bytes(result_bytes)
            request = EvidenceValidationRequest(
                domain="source",
                validator_id=SOURCE_ELIGIBILITY_VALIDATOR_ID,
                validation_plan_hash=source_validation_plan_hash(
                    "runtime_availability_proof"
                ),
                job_id=result["job_id"],
                job_hash=result["job_hash"],
                mission_id="MIS-0006",
                evidence_subject={"kind": "Study", "id": "STU-0085"},
                binding={
                    "result_manifest_output": "result.json",
                    "source_contract_id": us500_source_contract().source_contract_id,
                    "transition_evidence": "runtime_availability_proof",
                    "validation_plan_hash": source_validation_plan_hash(
                        "runtime_availability_proof"
                    ),
                    "validator_id": SOURCE_ELIGIBILITY_VALIDATOR_ID,
                },
                result_manifest=result,
                artifacts=(
                    ValidationArtifact(
                        output_name="probe.json",
                        sha256=probe_hash,
                        _source=probe_path,
                    ),
                    ValidationArtifact(
                        output_name="result.json",
                        sha256=result_hash,
                        _source=result_path,
                    ),
                ),
            )
            validated, trace = EvidenceValidatorRegistry(
                (SourceEligibilityValidator(),)
            ).validate(request)
        self.assertEqual(validated.verdict, "passed")
        self.assertFalse(validated.scientific_eligible)
        self.assertEqual(trace.opened_artifact_count, 2)
        self.assertEqual(dict(validated.facts)["latency_ms"], 5)


if __name__ == "__main__":
    unittest.main()
