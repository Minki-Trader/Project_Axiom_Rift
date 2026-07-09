from __future__ import annotations

import unittest
from dataclasses import replace
from statistics import fmean

from axiom_rift.v2.research import (
    Bar,
    BoundaryPurge,
    FeatureRow,
    FeatureSpec,
    IndexBoundary,
    LabelSpec,
    ResearchSpec,
    ResearchSpecError,
    SelectorSpec,
    Signal,
    TradeSpec,
    UnknownCostError,
    ValidationBand,
    build_feature_rows,
    build_supervised_samples,
    run_research,
    select_sequential,
    simulate_fixed_horizon,
)


def synthetic_bars(count: int = 96) -> tuple[Bar, ...]:
    bars = []
    previous_close = 10000.0
    for index in range(count):
        opening = previous_close + ((index % 3) - 1) * 0.15
        close = opening + ((index % 7) - 3) * 0.18 + 0.22
        high = max(opening, close) + 1.2 + (index % 2) * 0.1
        low = min(opening, close) - 1.1 - (index % 3) * 0.05
        bars.append(
            Bar(
                timestamp=f"T{index:04d}",
                open_bid=opening,
                high_bid=high,
                low_bid=low,
                close_bid=close,
                spread_points=float(2 + index % 2),
                tick_volume=float(100 + index % 11),
            )
        )
        previous_close = close
    return tuple(bars)


def research_spec() -> ResearchSpec:
    return ResearchSpec(
        features=FeatureSpec(("return_1", "body_fraction", "momentum_3", "volume_ratio_5")),
        label=LabelSpec(horizon_bars=2),
        selector=SelectorSpec(minimum_edge=0.0),
        trade=TradeSpec(hold_bars=2, point_size=0.1, commission_per_trade=0.0),
    )


class ResearchCoreTests(unittest.TestCase):
    def test_declarative_feature_surface_rejects_arbitrary_names(self) -> None:
        with self.assertRaises(ResearchSpecError):
            FeatureSpec(("arbitrary.module:function",))

    def test_completed_bar_features_are_prefix_invariant(self) -> None:
        bars = synthetic_bars()
        spec = FeatureSpec(("return_1", "body_fraction", "momentum_3", "volume_ratio_5"))
        purge = BoundaryPurge()
        cut = 53
        prefix_rows = build_feature_rows(bars[:cut], spec, IndexBoundary("prefix", 0, cut), purge)
        full_rows = build_feature_rows(bars, spec, IndexBoundary("full", 0, len(bars)), purge)

        self.assertEqual(prefix_rows, tuple(row for row in full_rows if row.decision_index < cut))

    def test_train_labels_are_isolated_from_future_boundary(self) -> None:
        bars = synthetic_bars()
        changed = list(bars)
        for index in range(40, len(changed)):
            bar = changed[index]
            changed[index] = replace(
                bar,
                open_bid=bar.open_bid + 500.0,
                high_bid=bar.high_bid + 500.0,
                low_bid=bar.low_bid + 500.0,
                close_bid=bar.close_bid + 500.0,
            )
        feature_spec = FeatureSpec(("return_1", "momentum_3"))
        label_spec = LabelSpec(horizon_bars=3)
        boundary = IndexBoundary("train_is", 0, 40)
        original = build_supervised_samples(bars, feature_spec, label_spec, boundary, BoundaryPurge())
        modified = build_supervised_samples(tuple(changed), feature_spec, label_spec, boundary, BoundaryPurge())

        self.assertEqual(original, modified)
        self.assertLessEqual(max(sample.decision_index for sample in original) + label_spec.horizon_bars, 39)

    def test_scaler_is_fit_on_train_only(self) -> None:
        bars = synthetic_bars()
        spec = research_spec()
        train = IndexBoundary("train_is", 0, 44)
        validation = IndexBoundary("validation_oos", 44, 68)
        evaluation = IndexBoundary("development_cv", 68, len(bars))
        result = run_research(bars, spec, train=train, validation=validation, evaluation=evaluation)
        train_samples = build_supervised_samples(bars, spec.features, spec.label, train, spec.purge)
        expected_means = tuple(
            fmean(sample.features[column] for sample in train_samples)
            for column in range(len(spec.features.names))
        )

        for observed, expected in zip(result.model.scaler_mean, expected_means, strict=True):
            self.assertAlmostEqual(observed, expected, places=15)

    def test_selector_is_sequential_one_position_and_not_top_k(self) -> None:
        rows = tuple(
            FeatureRow(index, f"T{index:04d}", (0.0,))
            for index in (10, 11, 12, 13, 14)
        )
        scores = (0.20, 10.0, 9.0, -0.20, -8.0)
        signals = select_sequential(
            zip(rows, scores, strict=True),
            ValidationBand(-0.05, 0.05, 1.0, 10),
            SelectorSpec(minimum_edge=0.05),
            TradeSpec(hold_bars=3),
            IndexBoundary("development_cv", 10, 20),
            BoundaryPurge(),
        )

        self.assertEqual([signal.decision_index for signal in signals], [10, 13])
        self.assertEqual([signal.direction for signal in signals], [1, -1])
        self.assertNotIn(11, [signal.decision_index for signal in signals])

    def test_bid_spread_accounting_and_zero_spread_rejection(self) -> None:
        bars = synthetic_bars(12)
        signals = (
            Signal(1, bars[1].timestamp, 1, 1.0, 0.5, 1.5, 2, 3),
            Signal(4, bars[4].timestamp, -1, -1.0, -1.5, -0.5, 5, 6),
        )
        trade_spec = TradeSpec(hold_bars=2, point_size=0.1)
        result = simulate_fixed_horizon(bars, signals, trade_spec)
        long_trade, short_trade = result.trades

        self.assertAlmostEqual(
            long_trade.net_pnl,
            bars[3].close_bid - bars[2].open_bid - bars[2].spread_points * 0.1,
        )
        self.assertAlmostEqual(
            short_trade.net_pnl,
            bars[5].open_bid - bars[6].close_bid - bars[6].spread_points * 0.1,
        )
        self.assertEqual(result.commission, 0.0)

        zero_spread = list(bars)
        zero_spread[2] = replace(zero_spread[2], spread_points=0.0)
        with self.assertRaises(UnknownCostError):
            simulate_fixed_horizon(tuple(zero_spread), signals, trade_spec)

    def test_non_economic_fixture_result_and_hash_are_deterministic(self) -> None:
        bars = synthetic_bars()
        spec = research_spec()
        boundaries = {
            "train": IndexBoundary("train_is", 0, 44),
            "validation": IndexBoundary("validation_oos", 44, 68),
            "evaluation": IndexBoundary("development_cv", 68, len(bars)),
        }
        first = run_research(bars, spec, **boundaries)
        second = run_research(bars, spec, **boundaries)

        self.assertEqual(first.to_payload(), second.to_payload())
        self.assertEqual(len(first.result_hash), 64)
        self.assertEqual(first.claim_ceiling, "diagnostic_observation")
        self.assertFalse(first.economic_claim_allowed)

        zero_spread = list(bars)
        zero_spread[0] = replace(zero_spread[0], spread_points=0.0)
        with self.assertRaises(UnknownCostError):
            run_research(tuple(zero_spread), spec, **boundaries)


if __name__ == "__main__":
    unittest.main()
