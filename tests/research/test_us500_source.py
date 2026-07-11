from __future__ import annotations

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
from axiom_rift.research.source_eligibility_validation import (
    SOURCE_ELIGIBILITY_VALIDATOR_ID,
    SourceEligibilityValidator,
)
from axiom_rift.research.us500_source import (
    US500_COLUMNS,
    audit_us500_historical_bytes,
    derive_runtime_facts,
    source_validation_plan_hash,
    us500_source_contract,
)


def runtime_probe() -> dict[str, object]:
    value = {
        "schema": "us500_runtime_probe_measurement.v1",
        "source_contract_id": us500_source_contract().source_contract_id,
        "observed_at_utc": "2026-07-11T00:00:00Z",
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
        "latest_closed_bar_utc": "2026-07-10T23:55:00Z",
        "retrieval_latency_ms": 5,
        "dtype_fields": list(US500_COLUMNS),
    }
    value["facts"] = derive_runtime_facts(value)
    return value


class US500SourceTests(unittest.TestCase):
    def test_contract_binds_exact_broker_surface_and_plans(self) -> None:
        contract = us500_source_contract()
        self.assertEqual(contract.runtime_identifier, "US500")
        self.assertEqual(contract.mapping()["runtime_symbol"], "US500")
        self.assertEqual(contract.instrument()["asset_type"], "cash_index_cfd")
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
        self.assertGreater(measurement["timestamp_gap_count"], 0)

    def test_runtime_validator_derives_every_fact_and_reads_every_artifact(self) -> None:
        probe = runtime_probe()
        probe_bytes = canonical_bytes(probe)
        probe_hash = sha256(probe_bytes).hexdigest()
        result = {
            "schema": "source_eligibility_evidence.v1",
            "job_id": "job:" + "a" * 64,
            "job_hash": "a" * 64,
            "mission_id": "MIS-0001",
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
                mission_id="MIS-0001",
                evidence_subject={"kind": "Study", "id": "STU-0018"},
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
