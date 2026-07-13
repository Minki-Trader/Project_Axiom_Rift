from __future__ import annotations

import unittest

from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.research.us500_source import source_validation_plan_hash
from axiom_rift.research.us500_source_study import (
    HISTORICAL_CALLABLE_IDENTITY,
    RUNTIME_CALLABLE_IDENTITY,
    _build_result,
    output_names,
)


class US500SourceStudyTests(unittest.TestCase):
    def test_two_jobs_have_distinct_callables_outputs_and_plans(self) -> None:
        self.assertNotEqual(HISTORICAL_CALLABLE_IDENTITY, RUNTIME_CALLABLE_IDENTITY)
        historical = output_names("historical_audit")
        runtime = output_names("runtime_availability_proof")
        self.assertEqual(set(historical), {"raw", "measurement", "result"})
        self.assertEqual(set(runtime), {"measurement", "result"})
        self.assertTrue(all(name.startswith("source/us500/") for name in historical.values()))
        self.assertTrue(all(name.startswith("source/us500/") for name in runtime.values()))
        self.assertNotEqual(
            source_validation_plan_hash("historical_audit"),
            source_validation_plan_hash("runtime_availability_proof"),
        )

    def test_result_binds_job_source_transition_and_measurements(self) -> None:
        execution = RunningJobExecution(
            job_id="job:" + "a" * 64,
            job_hash="a" * 64,
            job_permit_id="b" * 64,
            start_record_id="c" * 64,
        )
        result = _build_result(
            execution=execution,
            transition_evidence="runtime_availability_proof",
            observed_at_utc="2026-07-11T00:00:00Z",
            facts={
                "local_realtime_retrieval": True,
                "fresh": True,
                "synchronized": True,
                "complete_or_closed": True,
                "latency_ms": 5,
                "historical_runtime_field_parity": True,
            },
            measurement_hashes=("d" * 64,),
            mission_id="MIS-fixture",
        )
        self.assertEqual(result["job_id"], execution.job_id)
        self.assertEqual(result["transition_evidence"], "runtime_availability_proof")
        self.assertEqual(result["measurement_artifact_hashes"], ["d" * 64])


if __name__ == "__main__":
    unittest.main()
