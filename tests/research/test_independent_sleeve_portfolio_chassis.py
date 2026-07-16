from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.independent_sleeve_portfolio_chassis import (
    independent_sleeve_portfolio_baseline,
    independent_sleeve_portfolio_configurations,
    independent_sleeve_portfolio_executable,
)


class IndependentSleevePortfolioChassisTests(unittest.TestCase):
    def test_three_exact_profiles_have_distinct_identities(self) -> None:
        values = independent_sleeve_portfolio_configurations()
        self.assertEqual(len(values), 3)
        self.assertEqual(len({independent_sleeve_portfolio_executable(value).identity for value in values}), 3)

    def test_baseline_builds_architecture_chassis(self) -> None:
        architecture = ArchitectureChassisSpec.from_executable(independent_sleeve_portfolio_baseline())
        self.assertTrue(architecture.identity.startswith("architecture-family:"))

    def test_subject_changes_portfolio_and_risk_without_changing_baseline(self) -> None:
        values = independent_sleeve_portfolio_configurations()
        baseline = independent_sleeve_portfolio_executable(values[0])
        subject = independent_sleeve_portfolio_executable(values[2])
        self.assertEqual(
            baseline.identity,
            "executable:d21f632de63a9f54edc1e31b5302f316949aef6b4538062bebc0b47e6eedaef1",
        )
        self.assertNotEqual(baseline.identity, subject.identity)


if __name__ == "__main__":
    unittest.main()
