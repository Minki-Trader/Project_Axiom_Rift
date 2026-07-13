from datetime import date, timedelta
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    P0_REPLAY_EXECUTABLE_IDS,
    P0_REPLAY_FAMILY_ID,
    P0_REPLAY_HYPOTHESES,
    SelectionFamilyPlan,
    SelectionHypothesis,
    SelectionInferenceError,
    infer_concurrent_selection_family,
    infer_p0_simultaneous_forest,
)


def _days(count: int = 40) -> tuple[str, ...]:
    start = date(2024, 1, 1)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(count))


def _hypotheses() -> tuple[SelectionHypothesis, ...]:
    return (
        SelectionHypothesis("axis:a", "registration:a"),
        SelectionHypothesis("axis:b", "registration:b"),
    )


def _plan(*, stage: str = "discovery") -> SelectionFamilyPlan:
    return SelectionFamilyPlan(
        family_id="family:two-correlated-axes",
        stage=stage,  # type: ignore[arg-type]
        hypotheses=_hypotheses(),
        alpha_ppm=100_000,
        bootstrap_samples=99,
        block_lengths=(5, 10),
        monte_carlo_confidence_ppm=990_000,
        base_seed=7,
    )


def _correlated_family() -> dict[str, dict[str, int]]:
    days = _days()
    values = tuple(3 + ((index * 7) % 5) - 2 for index in range(len(days)))
    return {
        hypothesis.hypothesis_id: dict(zip(days, values, strict=True))
        for hypothesis in _hypotheses()
    }


class ConcurrentSelectionInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _plan()
        cls.family = _correlated_family()
        cls.context = HistoricalSearchContext(
            context_id="context:legacy-ledger-at-replay",
            prior_global_exposure_count=18,
        )
        cls.result = infer_concurrent_selection_family(
            plan=cls.plan,
            daily_pnl_by_hypothesis=cls.family,
            historical_context=cls.context,
        )

    def test_manifest_is_canonical_ascii_and_inference_is_deterministic(self) -> None:
        repeated = infer_concurrent_selection_family(
            plan=self.plan,
            daily_pnl_by_hypothesis={
                hypothesis_id: dict(reversed(tuple(series.items())))
                for hypothesis_id, series in reversed(tuple(self.family.items()))
            },
            historical_context=self.context,
        )

        self.assertEqual(repeated.statistical_manifest(), self.result.statistical_manifest())
        self.assertEqual(repeated.statistical_identity, self.result.statistical_identity)
        self.assertEqual(repeated.identity, self.result.identity)
        self.assertEqual(self.result.manifest_bytes(), canonical_bytes(self.result.manifest()))
        self.result.manifest_bytes().decode("ascii")
        self.assertEqual(len({seed.seed for seed in self.result.seeds}), 2)
        self.assertTrue(
            all(
                seed.manifest()["synchronization"]
                == "same_block_starts_for_every_family_member"
                for seed in self.result.seeds
            )
        )

    def test_raw_point_and_monte_carlo_upper_are_preserved_separately(self) -> None:
        subject = self.result.hypothesis("axis:a")

        self.assertLess(subject.raw_point_pvalue_ppm, subject.raw_monte_carlo_upper_pvalue_ppm)
        self.assertEqual(
            subject.bonferroni_point_pvalue_ppm,
            min(1_000_000, subject.raw_point_pvalue_ppm * 2),
        )
        self.assertEqual(
            subject.bonferroni_monte_carlo_upper_pvalue_ppm,
            min(1_000_000, subject.raw_monte_carlo_upper_pvalue_ppm * 2),
        )
        for block in subject.block_results:
            self.assertLessEqual(
                block.raw_point_pvalue_ppm,
                block.raw_monte_carlo_upper_pvalue_ppm,
            )

    def test_synchronized_family_methods_use_dependence(self) -> None:
        first = self.result.hypothesis("axis:a")
        second = self.result.hypothesis("axis:b")

        self.assertEqual(
            first.synchronized_max_monte_carlo_upper_pvalue_ppm,
            first.raw_monte_carlo_upper_pvalue_ppm,
        )
        self.assertEqual(
            second.synchronized_max_monte_carlo_upper_pvalue_ppm,
            second.raw_monte_carlo_upper_pvalue_ppm,
        )
        self.assertLessEqual(
            first.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm,
            first.bonferroni_monte_carlo_upper_pvalue_ppm,
        )
        self.assertEqual(first.block_results[0].romano_wolf_rank, 1)
        self.assertEqual(second.block_results[0].romano_wolf_rank, 2)

    def test_historical_global_count_is_context_only(self) -> None:
        changed_context = HistoricalSearchContext(
            context_id="context:same-ledger-different-description",
            prior_global_exposure_count=999_999,
        )
        changed = infer_concurrent_selection_family(
            plan=self.plan,
            daily_pnl_by_hypothesis=self.family,
            historical_context=changed_context,
        )

        self.assertEqual(changed.hypotheses, self.result.hypotheses)
        self.assertEqual(changed.seeds, self.result.seeds)
        self.assertEqual(changed.statistical_manifest(), self.result.statistical_manifest())
        self.assertEqual(changed.statistical_identity, self.result.statistical_identity)
        self.assertNotEqual(changed.identity, self.result.identity)
        self.assertNotIn("historical_context", changed.statistical_manifest())
        self.assertEqual(
            changed.statistical_manifest()["method"]["historical_exposure_adjustment"],
            "forbidden",
        )
        self.assertEqual(
            changed.manifest()["historical_context"]["adjustment_authority"],
            "context_only_never_adjustment_factor",
        )

    def test_validator_v2_projection_uses_mc_upper_and_concurrent_family(self) -> None:
        subject = self.result.hypothesis("axis:a")
        assessment = subject.validator_v2_multiplicity()

        self.assertEqual(assessment.criterion_id, "E01-familywise-selection")
        self.assertEqual(assessment.family_id, self.plan.family_id)
        self.assertEqual(assessment.family_size, 2)
        self.assertEqual(
            assessment.raw_pvalue_ppm,
            subject.raw_monte_carlo_upper_pvalue_ppm,
        )
        self.assertEqual(
            assessment.adjusted_pvalue_ppm,
            subject.bonferroni_monte_carlo_upper_pvalue_ppm,
        )
        self.assertEqual(assessment.method, "bonferroni_concurrent_family.v1")
        self.assertEqual(
            subject.manifest()["validator_v2_multiplicity"], assessment.manifest()
        )

    def test_family_and_calendar_are_closed_not_implicitly_expanded(self) -> None:
        with_extra = {**self.family, "axis:unregistered": self.family["axis:a"]}
        with self.assertRaisesRegex(SelectionInferenceError, "exactly match"):
            infer_concurrent_selection_family(
                plan=self.plan,
                daily_pnl_by_hypothesis=with_extra,
                historical_context=self.context,
            )

        mismatched = {
            hypothesis_id: dict(series)
            for hypothesis_id, series in self.family.items()
        }
        mismatched["axis:b"].pop(_days()[-1])
        with self.assertRaisesRegex(SelectionInferenceError, "exact same explicit"):
            infer_concurrent_selection_family(
                plan=self.plan,
                daily_pnl_by_hypothesis=mismatched,
                historical_context=self.context,
            )

    def test_zero_variance_member_is_non_evaluable_and_conservative(self) -> None:
        family = _correlated_family()
        family["axis:a"] = {day: 7 for day in _days()}
        result = infer_concurrent_selection_family(
            plan=self.plan,
            daily_pnl_by_hypothesis=family,
            historical_context=self.context,
        )
        subject = result.hypothesis("axis:a")

        self.assertFalse(subject.evaluable)
        self.assertEqual(subject.raw_point_pvalue_ppm, 1_000_000)
        self.assertEqual(subject.raw_monte_carlo_upper_pvalue_ppm, 1_000_000)
        self.assertEqual(
            subject.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm,
            1_000_000,
        )

    def test_stage_authority_keeps_discovery_and_confirmation_separate(self) -> None:
        self.assertEqual(
            self.plan.candidate_authority,
            "none_discovery_screening_only",
        )
        confirmation = _plan(stage="confirmation")
        self.assertEqual(
            confirmation.candidate_authority,
            "none_confirmation_requires_scientific_validator_v2",
        )
        with self.assertRaisesRegex(SelectionInferenceError, "selection stage"):
            _plan(stage="candidate")

    def test_plan_rejects_ambiguous_order_and_non_ascii(self) -> None:
        with self.assertRaisesRegex(SelectionInferenceError, "sorted"):
            SelectionFamilyPlan(
                family_id="family:bad-order",
                stage="discovery",
                hypotheses=tuple(reversed(_hypotheses())),
                bootstrap_samples=99,
                block_lengths=(5,),
            )
        with self.assertRaisesRegex(SelectionInferenceError, "ASCII"):
            SelectionHypothesis("axis:non-ascii-\ucd95", "registration:x")


class P0SimultaneousForestTests(unittest.TestCase):
    def test_exact_six_axis_helper_returns_one_closed_forest(self) -> None:
        days = _days(35)
        family = {
            executable_id: {
                day: member_index + 2 + ((day_index * 11) % 7) - 3
                for day_index, day in enumerate(days)
            }
            for member_index, executable_id in enumerate(P0_REPLAY_EXECUTABLE_IDS)
        }
        result = infer_p0_simultaneous_forest(
            family,
            historical_context=HistoricalSearchContext(
                context_id="context:p0-replay",
                prior_global_exposure_count=18,
            ),
            bootstrap_samples=99,
            block_lengths=(5,),
            base_seed=13,
        )

        self.assertEqual(result.plan.family_id, P0_REPLAY_FAMILY_ID)
        self.assertEqual(result.plan.stage, "discovery")
        self.assertEqual(result.plan.family_size, 6)
        self.assertEqual(
            tuple(item.hypothesis_id for item in result.hypotheses),
            P0_REPLAY_EXECUTABLE_IDS,
        )
        self.assertEqual(
            {item.registration_id for item in P0_REPLAY_HYPOTHESES},
            {
                "study:STU-0062",
                "study:STU-0074",
                "study:STU-0081",
                "study:STU-0084",
                "study:STU-0089",
                "study:STU-0092",
            },
        )
        self.assertEqual(result.date_count, 35)
        self.assertEqual(len(result.hypotheses), 6)

    def test_p0_helper_rejects_missing_historical_axis(self) -> None:
        days = _days(35)
        family = {
            executable_id: {day: index % 5 for index, day in enumerate(days)}
            for executable_id in P0_REPLAY_EXECUTABLE_IDS[:-1]
        }
        with self.assertRaisesRegex(SelectionInferenceError, "exactly match"):
            infer_p0_simultaneous_forest(
                family,
                historical_context=HistoricalSearchContext(
                    context_id="context:p0-incomplete",
                    prior_global_exposure_count=18,
                ),
                bootstrap_samples=99,
                block_lengths=(5,),
            )


if __name__ == "__main__":
    unittest.main()
