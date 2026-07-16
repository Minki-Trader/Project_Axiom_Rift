from __future__ import annotations

import unittest

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.us30_downside_spillover_discovery import (
    us30_downside_spillover_configurations,
    us30_downside_spillover_executable,
)


RAW_SHA256 = "6d638467069a756a7a3897b587ec16a4b9ff76df8718186c2a81905d6d0488d4"
AXIS_ARCHITECTURE = (
    "architecture-family:29aab15a805c200956836f9b67d4b27fe3245b8f8478ead36b4616dc0c79c551"
)


class US30DownsideSpilloverChassisTests(unittest.TestCase):
    def test_downside_profile_is_the_only_changed_domain(self) -> None:
        configurations = us30_downside_spillover_configurations()
        baseline_configuration = next(
            value
            for value in configurations
            if value.profile == "target_only_downside"
            and value.route_sign == 1
            and value.holding_bars == 3
        )
        subject_configuration = next(
            value
            for value in configurations
            if value.profile == "source_downside_expansion"
            and value.route_sign == 1
            and value.holding_bars == 3
        )
        baseline = us30_downside_spillover_executable(
            baseline_configuration,
            RAW_SHA256,
        )
        subject = us30_downside_spillover_executable(
            subject_configuration,
            RAW_SHA256,
        )
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        self.assertEqual(architecture.identity, AXIS_ARCHITECTURE)
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.FEATURE,),
            controlled_domains=(
                ResearchLayer.DATA_SOURCE,
                ResearchLayer.EXECUTION,
                ResearchLayer.LABEL,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.MODEL,
                ResearchLayer.REGIME,
                ResearchLayer.RISK,
                ResearchLayer.SELECTOR,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.TRADE,
            ),
            architecture=architecture,
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)
        self.assertNotEqual(
            baseline.parameter_values()["score_profile"],
            subject.parameter_values()["score_profile"],
        )


if __name__ == "__main__":
    unittest.main()
