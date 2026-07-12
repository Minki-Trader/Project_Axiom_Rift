from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.volatility_clock_label_chassis import (
    VOLATILITY_BUDGET_BARS,
    volatility_clock_label_baseline,
    volatility_clock_label_configurations,
    volatility_clock_label_executable,
)


class VolatilityClockLabelChassisTests(unittest.TestCase):
    def test_volatility_clock_is_a_distinct_activity_time_profile(self) -> None:
        configurations = volatility_clock_label_configurations()
        self.assertEqual(VOLATILITY_BUDGET_BARS, 12)
        self.assertEqual(
            {value.profile for value in configurations},
            {"fixed_first_passage_control_48", "volatility_clock_terminal_12_of_48"},
        )

    def test_subject_changes_only_the_label_parameter(self) -> None:
        baseline = volatility_clock_label_baseline()
        subject = volatility_clock_label_executable(
            next(
                value
                for value in volatility_clock_label_configurations()
                if value.profile == "volatility_clock_terminal_12_of_48"
            )
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.LABEL,),
            controlled_domains=(
                ResearchLayer.FEATURE,
                ResearchLayer.MODEL,
                ResearchLayer.SELECTOR,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)


if __name__ == "__main__":
    unittest.main()
