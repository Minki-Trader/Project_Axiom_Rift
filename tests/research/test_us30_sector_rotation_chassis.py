from __future__ import annotations

import unittest

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.us30_sector_rotation_chassis import (
    us30_sector_rotation_registered_baseline,
    us30_sector_rotation_registered_executable,
)
from axiom_rift.research.us30_sector_rotation_discovery import (
    us30_sector_rotation_configurations,
)


RAW_SHA256 = "6d638467069a756a7a3897b587ec16a4b9ff76df8718186c2a81905d6d0488d4"
AXIS_ARCHITECTURE = (
    "architecture-family:e784a1eb1469ff0dd6ceaee9cb1c705ff8bb9357e12a3f4fc2f04015784ea120"
)


class US30SectorRotationChassisTests(unittest.TestCase):
    def test_source_usage_is_the_only_changed_domain(self) -> None:
        baseline = us30_sector_rotation_registered_baseline(RAW_SHA256)
        subject_configuration = next(
            value
            for value in us30_sector_rotation_configurations()
            if value.profile == "relative_strength_12_joint"
            and value.route_sign == 1
            and value.holding_bars == 6
        )
        subject = us30_sector_rotation_registered_executable(
            subject_configuration,
            RAW_SHA256,
        )
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        self.assertEqual(architecture.identity, AXIS_ARCHITECTURE)
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.DATA_SOURCE,),
            controlled_domains=(
                ResearchLayer.EXECUTION,
                ResearchLayer.FEATURE,
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
        self.assertEqual(
            baseline.identity,
            "executable:411fa152eb56829ea0500818d3885fc40e0ebcfa07bcf8db23833710d31fbafd",
        )
        self.assertEqual(
            subject.parameter_values()["source_usage_profile"],
            "relative_strength_12_joint",
        )


if __name__ == "__main__":
    unittest.main()
