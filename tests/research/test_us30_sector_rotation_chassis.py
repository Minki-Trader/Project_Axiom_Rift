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
    "architecture-family:2dc96e64b746970c75c85b33763d9c85e5e449334ec71dde6135fdfab54ea4e3"
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
            "executable:acdcbc022c4c7c4d30957fa54d381517fe1668706f414bb8a8588b84215d99ce",
        )
        self.assertEqual(
            subject.parameter_values()["source_usage_profile"],
            "relative_strength_12_joint",
        )


if __name__ == "__main__":
    unittest.main()
