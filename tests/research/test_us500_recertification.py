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
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
)
from axiom_rift.research.us500_recertification import (
    DRIFT_FACTS,
    RECERTIFICATION_FACTS,
    build_drift_measurement,
    build_recertification_measurement,
    source_recertification_plan_hash,
)
from axiom_rift.research.us500_recertification_validation import (
    US500_RECERTIFICATION_VALIDATOR_ID,
    US500RecertificationValidator,
)
from axiom_rift.research.us500_source import US500_COLUMNS, derive_runtime_facts, us500_source_contract


def runtime_probe() -> dict[str, object]:
    observed_at_utc = "2026-07-13T01:00:00Z"
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
        "market_closed": False,
        "closed_bar_available": True,
        "tick_mt5_epoch_seconds": tick_epoch,
        "latest_rate_mt5_epoch_seconds": tick_epoch - 300,
        "mt5_epoch_minus_observed_utc_seconds": 10_800,
        "mt5_epoch_sequence_coherent": True,
        "latest_closed_bar_mt5_epoch_coordinate": "2026-07-13T03:55:00",
        "retrieval_latency_ms": 7,
        "dtype_fields": list(US500_COLUMNS),
    }
    value["facts"] = derive_runtime_facts(value)
    return value


def runtime_state_payload() -> dict[str, object]:
    contract = us500_source_contract()
    receipt = SourceEligibilityReceipt(
        source_contract_id=contract.source_contract_id,
        evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
        producer_completion_id="a" * 64,
        observed_at_utc="2026-07-12T12:00:00Z",
        artifact_hashes=("b" * 64,),
        facts={
            "local_realtime_retrieval": True,
            "fresh": True,
            "synchronized": True,
            "complete_or_closed": True,
            "latency_ms": 5,
            "historical_runtime_field_parity": True,
        },
    )
    return {
        "contract": contract.to_identity_payload(),
        "receipt": receipt.to_identity_payload(),
        "evidence_receipt_id": receipt.identity,
    }


def suspended_state_payload() -> dict[str, object]:
    contract = us500_source_contract()
    receipt = SourceEligibilityReceipt(
        source_contract_id=contract.source_contract_id,
        evidence=SourceTransitionEvidence.DRIFT,
        producer_completion_id="c" * 64,
        observed_at_utc="2026-07-13T00:00:00Z",
        artifact_hashes=("d" * 64,),
        facts=DRIFT_FACTS,
    )
    return {
        "contract": contract.to_identity_payload(),
        "receipt": receipt.to_identity_payload(),
        "evidence_receipt_id": receipt.identity,
    }


class US500RecertificationTests(unittest.TestCase):
    def _validate(self, transition: str, measurement: dict[str, object]) -> None:
        measurement_bytes = canonical_bytes(measurement)
        measurement_hash = sha256(measurement_bytes).hexdigest()
        result = {
            "schema": "source_eligibility_evidence.v1",
            "job_id": "job:" + "e" * 64,
            "job_hash": "e" * 64,
            "mission_id": "MIS-0006",
            "source_contract_id": us500_source_contract().source_contract_id,
            "transition_evidence": transition,
            "observed_at_utc": measurement["observed_at_utc"],
            "facts": measurement["facts"],
            "measurement_artifact_hashes": [measurement_hash],
        }
        result_bytes = canonical_bytes(result)
        result_hash = sha256(result_bytes).hexdigest()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            measurement_path = root / "measurement.json"
            result_path = root / "result.json"
            measurement_path.write_bytes(measurement_bytes)
            result_path.write_bytes(result_bytes)
            request = EvidenceValidationRequest(
                domain="source",
                validator_id=US500_RECERTIFICATION_VALIDATOR_ID,
                validation_plan_hash=source_recertification_plan_hash(transition),
                job_id=result["job_id"],
                job_hash=result["job_hash"],
                mission_id="MIS-0006",
                evidence_subject={"kind": "Study", "id": "STU-0095"},
                binding={
                    "result_manifest_output": "result.json",
                    "source_contract_id": us500_source_contract().source_contract_id,
                    "transition_evidence": transition,
                    "validation_plan_hash": source_recertification_plan_hash(transition),
                    "validator_id": US500_RECERTIFICATION_VALIDATOR_ID,
                },
                result_manifest=result,
                artifacts=(
                    ValidationArtifact(
                        output_name="measurement.json",
                        sha256=measurement_hash,
                        _source=measurement_path,
                    ),
                    ValidationArtifact(
                        output_name="result.json",
                        sha256=result_hash,
                        _source=result_path,
                    ),
                ),
            )
            validated, trace = EvidenceValidatorRegistry(
                (US500RecertificationValidator(),)
            ).validate(request)
        self.assertEqual(validated.verdict, "passed")
        self.assertFalse(validated.scientific_eligible)
        self.assertEqual(trace.opened_artifact_count, 2)

    def test_stale_runtime_receipt_derives_drift(self) -> None:
        measurement = build_drift_measurement(
            source_state_record_id="f" * 64,
            source_state_status="runtime_eligible",
            source_state_payload=runtime_state_payload(),
            observed_at_utc="2026-07-13T01:00:00Z",
        )
        self.assertEqual(measurement["facts"], DRIFT_FACTS)
        self.assertGreater(measurement["receipt_age_seconds"], 21600)
        self._validate(SourceTransitionEvidence.DRIFT.value, measurement)

    def test_identical_contract_and_live_probe_derive_recertification(self) -> None:
        measurement = build_recertification_measurement(
            source_state_record_id="f" * 64,
            source_state_status="suspended",
            source_state_payload=suspended_state_payload(),
            runtime_probe=runtime_probe(),
        )
        self.assertEqual(measurement["facts"], RECERTIFICATION_FACTS)
        self._validate(
            SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value,
            measurement,
        )

    def test_recertification_plans_are_distinct(self) -> None:
        self.assertNotEqual(
            source_recertification_plan_hash(SourceTransitionEvidence.DRIFT.value),
            source_recertification_plan_hash(
                SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value
            ),
        )


if __name__ == "__main__":
    unittest.main()
