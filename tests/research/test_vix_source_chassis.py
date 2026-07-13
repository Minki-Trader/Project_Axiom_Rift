from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.vix_source import vix_source_contract
from axiom_rift.research.vix_source_chassis import vix_source_baseline


class VIXSourceChassisTests(unittest.TestCase):
    def test_contract_fails_closed_on_roll_semantics(self) -> None:
        contract = vix_source_contract()
        self.assertEqual(contract.runtime_identifier, "VIX")
        self.assertEqual(
            contract.instrument()["roll"],
            "broker_continuous_front_future_alias_requires_audit",
        )
        self.assertIn("require_audit", contract.availability()["revision_or_vintage"])

    def test_baseline_is_canonical_no_trade_architecture(self) -> None:
        baseline = vix_source_baseline()
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        self.assertTrue(architecture.identity.startswith("architecture-family:"))
        self.assertEqual(baseline.parameter_values()["source_state"], "eligibility_pending")
        manifests = baseline.to_identity_payload()["component_manifests"]
        self.assertFalse(manifests[0]["spec"]["performance_allowed"])


if __name__ == "__main__":
    unittest.main()
