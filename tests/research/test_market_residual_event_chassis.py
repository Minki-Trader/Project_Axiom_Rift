from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.market_residual_event_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    fit_market_residual,
    market_residual_event_baseline,
    market_residual_event_configurations,
    market_residual_event_executable,
    project_market_residual_score,
)
from axiom_rift.research.us500_source import us500_source_contract
from axiom_rift.research.validation import require_supported_evaluation_schema


class MarketResidualEventChassisTests(unittest.TestCase):
    def test_three_fixed_profiles_have_distinct_executable_identities(self) -> None:
        values = tuple(
            market_residual_event_executable(configuration)
            for configuration in market_residual_event_configurations()
        )
        self.assertEqual(len({value.identity for value in values}), 3)
        self.assertTrue(
            all(
                value.source_contracts
                == (us500_source_contract().source_contract_id,)
                for value in values
            )
        )
        self.assertEqual(SELECTION_TOTAL_EXPOSURES, 592)

    def test_fold_train_beta_removes_linear_market_component(self) -> None:
        source = np.linspace(-0.02, 0.02, 240)
        idiosyncratic = np.sin(np.arange(240) / 7.0) * 0.001
        target = 0.0003 + 1.6 * source + idiosyncratic
        train = np.zeros(240, dtype=bool)
        train[:180] = True
        fit = fit_market_residual(target, source, train)
        score = project_market_residual_score(
            target,
            source,
            fit,
            residual_profile="fold_train_linear_market_residual",
        )
        self.assertAlmostEqual(fit.beta, 1.6, places=1)
        self.assertLess(abs(np.corrcoef(score[180:], source[180:])[0, 1]), 0.1)

    def test_target_control_does_not_use_source_values(self) -> None:
        source = np.linspace(-0.02, 0.02, 240)
        target = np.cos(np.arange(240) / 8.0) * 0.002
        train = np.zeros(240, dtype=bool)
        train[:180] = True
        fit = fit_market_residual(target, source, train)
        left = project_market_residual_score(
            target,
            source,
            fit,
            residual_profile="target_only_completed_return",
        )
        right = project_market_residual_score(
            target,
            source * -9.0,
            fit,
            residual_profile="target_only_completed_return",
        )
        np.testing.assert_array_equal(left, right)

    def test_architecture_is_typed_and_short_horizon_is_fixed(self) -> None:
        baseline = market_residual_event_baseline()
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        self.assertEqual(baseline.parameter_values()["holding_bars"], 6)
        self.assertEqual(baseline.parameter_values()["selector_quantile_bp"], 9000)
        self.assertEqual(architecture.identity[:20], "architecture-family:")

    def test_residual_subjects_change_exact_feature_trade_synthesis_domains(self) -> None:
        baseline = market_residual_event_baseline()
        self.assertEqual(
            baseline.identity,
            "executable:7d9f63e3a8f74dbd9b0b2a4877c09d6e763dbc67dffb830c6ade10d0640d3458",
        )
        controlled = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(
                ResearchLayer.EXECUTION,
                ResearchLayer.FEATURE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.MODEL,
                ResearchLayer.PORTFOLIO,
                ResearchLayer.RISK,
                ResearchLayer.TRADE,
            ),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
                ResearchLayer.DATA_SOURCE,
                ResearchLayer.LABEL,
                ResearchLayer.REGIME,
                ResearchLayer.SELECTOR,
                ResearchLayer.SYNTHESIS,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        for configuration in market_residual_event_configurations()[1:]:
            validate_controlled_executable(
                controlled.to_identity_payload(),
                market_residual_event_executable(configuration),
            )

    def test_scientific_validator_profile_is_registered(self) -> None:
        self.assertEqual(
            require_supported_evaluation_schema(
                "market_residual_event_evaluation.v1"
            ),
            "market_residual_event_evaluation.v1",
        )


if __name__ == "__main__":
    unittest.main()
