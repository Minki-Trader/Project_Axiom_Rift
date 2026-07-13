from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_DOCUMENTED_TIME_STANDARD,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
)
from axiom_rift.research.vix_source import vix_source_contract
from axiom_rift.research.vix_source_chassis import vix_source_baseline


class VIXSourceChassisTests(unittest.TestCase):
    def test_contract_fails_closed_on_roll_semantics(self) -> None:
        contract = vix_source_contract()
        self.assertEqual(contract.runtime_identifier, "VIX")
        self.assertEqual(
            contract.instrument()["roll"],
            "broker_continuous_front_future_alias_historical_roll_"
            "not_identifiable",
        )
        self.assertIn(
            MT5_ABSOLUTE_TIME_AUTHORITY,
            contract.instrument()["timezone"],
        )
        self.assertEqual(
            contract.clock()["observed_time_coordinate"],
            MT5_EPOCH_COORDINATE,
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
        self.assertIn(
            "not_identifiable_context_only",
            contract.availability()["revision_or_vintage"],
        )

    def test_baseline_is_canonical_no_trade_architecture(self) -> None:
        baseline = vix_source_baseline()
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        self.assertTrue(architecture.identity.startswith("architecture-family:"))
        self.assertEqual(baseline.parameter_values()["source_state"], "context_only")
        self.assertEqual(
            baseline.parameter_values()["roll_semantics_state"],
            "not_identifiable",
        )
        manifests = baseline.to_identity_payload()["component_manifests"]
        self.assertFalse(manifests[0]["spec"]["performance_allowed"])
        self.assertEqual(manifests[0]["spec"]["source_state"], "context_only")
        self.assertEqual(manifests[0]["spec"]["evidence_state"], "not_identifiable")
        self.assertFalse(manifests[0]["spec"]["promotion_allowed"])
        self.assertFalse(manifests[-1]["spec"]["performance_allowed"])
        self.assertFalse(manifests[-1]["spec"]["promotion_allowed"])


if __name__ == "__main__":
    unittest.main()
