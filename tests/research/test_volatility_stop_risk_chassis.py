from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.volatility_stop_risk_chassis import volatility_stop_risk_baseline, volatility_stop_risk_configurations, volatility_stop_risk_executable


class VolatilityStopRiskChassisTests(unittest.TestCase):
    def test_subject_changes_only_the_risk_parameter(self) -> None:
        baseline = volatility_stop_risk_baseline()
        subject = volatility_stop_risk_executable(
            next(value for value in volatility_stop_risk_configurations() if value.risk_policy == "pre_entry_volatility_loss_stop")
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.RISK,),
            controlled_domains=(
                ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL,
                ResearchLayer.SELECTOR, ResearchLayer.TRADE, ResearchLayer.LIFECYCLE,
                ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)


if __name__ == "__main__":
    unittest.main()
