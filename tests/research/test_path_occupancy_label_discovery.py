from __future__ import annotations

import unittest

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.path_occupancy_label_discovery import (
    path_occupancy_label_baseline,
    path_occupancy_label_configurations,
    path_occupancy_label_executable,
)


class PathOccupancyLabelDiscoveryTests(unittest.TestCase):
    def test_two_exact_label_profiles_share_the_controlled_chassis(self) -> None:
        configurations = path_occupancy_label_configurations()
        executables = [path_occupancy_label_executable(value) for value in configurations]
        self.assertEqual(
            {value.profile for value in configurations},
            {"first_passage_label_control_48", "path_occupancy_label_48"},
        )
        self.assertEqual(len({value.identity for value in executables}), 2)
        self.assertEqual(
            {component.identity for component in executables[0].components},
            {component.identity for component in executables[1].components},
        )

    def test_subject_changes_only_the_declared_label_parameter(self) -> None:
        baseline = path_occupancy_label_baseline()
        subject = path_occupancy_label_executable(
            next(
                value
                for value in path_occupancy_label_configurations()
                if value.profile == "path_occupancy_label_48"
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
