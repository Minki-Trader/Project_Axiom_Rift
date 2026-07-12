from __future__ import annotations

import unittest

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.trend_regime_chassis import (
    trend_regime_baseline, trend_regime_configurations, trend_regime_executable,
)


class TrendRegimeChassisTests(unittest.TestCase):
    def test_subject_changes_only_the_regime_parameter(self) -> None:
        baseline = trend_regime_baseline()
        subject = trend_regime_executable(next(
            value for value in trend_regime_configurations()
            if value.regime_policy == "positive_192bar_trend_gate"
        ))
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.REGIME,),
            controlled_domains=(
                ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL,
                ResearchLayer.SELECTOR, ResearchLayer.TRADE, ResearchLayer.LIFECYCLE,
                ResearchLayer.RISK, ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)


if __name__ == "__main__":
    unittest.main()
