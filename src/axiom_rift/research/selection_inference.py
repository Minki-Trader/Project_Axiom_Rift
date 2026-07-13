"""Prospective concurrent-family selection inference.

Legacy discovery modules multiplied bootstrap p-values by a project-wide
cumulative exposure count.  This module is the authoritative prospective v2
boundary instead: only the hypotheses preregistered in one concurrent family
are adjusted.  Historical search exposure is retained as audit context and is
never read by the statistical calculation.

The bootstrap is one-sided, studentized, and non-circular moving-block.  Every
hypothesis uses the same sampled block starts so contemporaneous cross-axis
dependence is preserved.  The result retains the raw Monte Carlo point
estimate and its one-sided Clopper-Pearson upper separately, then reports
concurrent-family Bonferroni, synchronized single-step max-statistic, and
Romano-Wolf-style stepdown familywise values.

This output never grants candidate authority.  Discovery remains screening;
confirmation still requires an explicit scientific validator v2 promotion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from math import ceil, isfinite, sqrt
from pathlib import Path
import re
import sys
from typing import Any, Literal

import numpy as np
import scipy
from scipy.stats import beta

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.adjudication import (
    PER_MILLION,
    MultiplicityAssessment,
    bonferroni_concurrent_family,
)
from axiom_rift.research.p0_replay_inventory import load_p0_replay_inventory


SELECTION_INFERENCE_PLAN_SCHEMA = "selection_inference_plan.v2"
SELECTION_DAILY_PNL_SCHEMA = "selection_daily_pnl.v1"
SELECTION_INFERENCE_STATISTICAL_SCHEMA = "selection_inference_statistical.v2"
SELECTION_INFERENCE_RESULT_SCHEMA = "selection_inference_result.v2"
SELECTION_BOOTSTRAP_METHOD = (
    "one_sided_studentized_non_circular_moving_block.v2"
)
SELECTION_RAW_POINT_METHOD = "plus_one_monte_carlo_tail.v1"
SELECTION_MONTE_CARLO_UPPER_METHOD = (
    "one_sided_clopper_pearson_binomial_upper.v1"
)
SELECTION_BONFERRONI_METHOD = "bonferroni_concurrent_family.v1"
SELECTION_MAX_STATISTIC_METHOD = "synchronized_single_step_max_statistic.v1"
SELECTION_ROMANO_WOLF_METHOD = "synchronized_romano_wolf_stepdown.v1"
SELECTION_BLOCK_AGGREGATION = (
    "worst_pvalue_across_preregistered_block_lengths"
)
SELECTION_STATISTIC_SCALE = 1_000_000_000
DEFAULT_BOOTSTRAP_SAMPLES = 41_999
DEFAULT_BLOCK_LENGTHS = (5, 10, 20)
DEFAULT_ALPHA_PPM = 100_000
DEFAULT_MONTE_CARLO_CONFIDENCE_PPM = 990_000
DEFAULT_BASE_SEED = 20_260_713
MINIMUM_DAYS = 30
MINIMUM_BOOTSTRAP_SAMPLES = 99

SelectionStage = Literal["discovery", "confirmation"]
DailyPnlSeries = Mapping[str, int]
DailyPnlFamily = Mapping[str, DailyPnlSeries]

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_METHOD_REFERENCES = (
    "doi:10.1214/aos/1176347265",
    "doi:10.1093/biomet/82.3.561",
    "doi:10.1198/016214504000000539",
)


class SelectionInferenceError(ValueError):
    """Raised when a prospective family or its evidence is not exact."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise SelectionInferenceError(f"{name} must be non-empty ASCII")
    return value


def _ppm(name: str, value: object, *, allow_zero: bool = True) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= PER_MILLION:
        raise SelectionInferenceError(
            f"{name} must be an integer in [{minimum}, {PER_MILLION}]"
        )
    return value


def _positive_integer(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise SelectionInferenceError(f"{name} must be a positive integer")
    return value


def _strict_date(value: object) -> str:
    text = _ascii("daily PnL date", value)
    if _DATE_PATTERN.fullmatch(text) is None:
        raise SelectionInferenceError("daily PnL dates must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise SelectionInferenceError("daily PnL date is invalid") from exc
    if parsed.isoformat() != text:
        raise SelectionInferenceError("daily PnL dates must be canonical")
    return text


def selection_inference_implementation_sha256() -> str:
    """Return the exact implementation hash bound into result manifests."""

    return sha256(Path(__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SelectionHypothesis:
    """One exact hypothesis registered before concurrent comparison."""

    hypothesis_id: str
    registration_id: str

    def __post_init__(self) -> None:
        _ascii("hypothesis_id", self.hypothesis_id)
        _ascii("registration_id", self.registration_id)

    def manifest(self) -> dict[str, str]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "registration_id": self.registration_id,
        }


@dataclass(frozen=True, slots=True)
class SelectionFamilyPlan:
    """One preregistered concurrent family and its exact bootstrap plan."""

    family_id: str
    stage: SelectionStage
    hypotheses: tuple[SelectionHypothesis, ...]
    alpha_ppm: int = DEFAULT_ALPHA_PPM
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    block_lengths: tuple[int, ...] = DEFAULT_BLOCK_LENGTHS
    monte_carlo_confidence_ppm: int = DEFAULT_MONTE_CARLO_CONFIDENCE_PPM
    base_seed: int = DEFAULT_BASE_SEED

    def __post_init__(self) -> None:
        _ascii("family_id", self.family_id)
        if self.stage not in {"discovery", "confirmation"}:
            raise SelectionInferenceError(
                "selection stage must be discovery or confirmation"
            )
        if type(self.hypotheses) is not tuple or not self.hypotheses:
            raise SelectionInferenceError(
                "hypotheses must be a non-empty tuple of SelectionHypothesis"
            )
        if any(
            not isinstance(hypothesis, SelectionHypothesis)
            for hypothesis in self.hypotheses
        ):
            raise SelectionInferenceError(
                "hypotheses must contain only SelectionHypothesis values"
            )
        identifiers = tuple(
            hypothesis.hypothesis_id for hypothesis in self.hypotheses
        )
        if identifiers != tuple(sorted(identifiers)):
            raise SelectionInferenceError(
                "hypotheses must be sorted by hypothesis_id"
            )
        if len(set(identifiers)) != len(identifiers):
            raise SelectionInferenceError("hypothesis_id values must be unique")
        _ppm("alpha_ppm", self.alpha_ppm, allow_zero=False)
        if (
            type(self.bootstrap_samples) is not int
            or self.bootstrap_samples < MINIMUM_BOOTSTRAP_SAMPLES
        ):
            raise SelectionInferenceError(
                f"bootstrap_samples must be at least {MINIMUM_BOOTSTRAP_SAMPLES}"
            )
        if type(self.block_lengths) is not tuple or not self.block_lengths:
            raise SelectionInferenceError(
                "block_lengths must be a non-empty tuple"
            )
        if any(type(length) is not int or length < 1 for length in self.block_lengths):
            raise SelectionInferenceError(
                "block_lengths must contain positive integers"
            )
        if self.block_lengths != tuple(sorted(set(self.block_lengths))):
            raise SelectionInferenceError(
                "block_lengths must be strictly increasing and unique"
            )
        if (
            type(self.monte_carlo_confidence_ppm) is not int
            or not 500_000 < self.monte_carlo_confidence_ppm < PER_MILLION
        ):
            raise SelectionInferenceError(
                "monte_carlo_confidence_ppm must be in (500000, 1000000)"
            )
        if (
            type(self.base_seed) is not int
            or not 0 <= self.base_seed <= (2**63 - 1)
        ):
            raise SelectionInferenceError(
                "base_seed must be an integer in [0, 2**63 - 1]"
            )
        canonical_bytes(self.manifest())

    @property
    def hypothesis_ids(self) -> tuple[str, ...]:
        return tuple(hypothesis.hypothesis_id for hypothesis in self.hypotheses)

    @property
    def family_size(self) -> int:
        return len(self.hypotheses)

    @property
    def candidate_authority(self) -> str:
        if self.stage == "discovery":
            return "none_discovery_screening_only"
        return "none_confirmation_requires_scientific_validator_v2"

    def manifest(self) -> dict[str, Any]:
        return {
            "alpha_ppm": self.alpha_ppm,
            "base_seed": self.base_seed,
            "block_lengths": list(self.block_lengths),
            "bootstrap_samples": self.bootstrap_samples,
            "candidate_authority": self.candidate_authority,
            "family_id": self.family_id,
            "family_size": self.family_size,
            "hypotheses": [
                hypothesis.manifest() for hypothesis in self.hypotheses
            ],
            "monte_carlo_confidence_ppm": self.monte_carlo_confidence_ppm,
            "schema": SELECTION_INFERENCE_PLAN_SCHEMA,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSearchContext:
    """Descriptive search-history context with no statistical authority."""

    context_id: str
    prior_global_exposure_count: int

    def __post_init__(self) -> None:
        _ascii("historical context_id", self.context_id)
        if (
            type(self.prior_global_exposure_count) is not int
            or self.prior_global_exposure_count < 0
        ):
            raise SelectionInferenceError(
                "prior_global_exposure_count must be a non-negative integer"
            )
        canonical_bytes(self.manifest())

    def manifest(self) -> dict[str, str | int]:
        return {
            "adjustment_authority": "context_only_never_adjustment_factor",
            "context_id": self.context_id,
            "prior_global_exposure_count": self.prior_global_exposure_count,
        }


@dataclass(frozen=True, slots=True)
class BootstrapSeedRecord:
    """One deterministic family-level seed shared across all hypotheses."""

    block_length: int
    seed: int
    seed_material_sha256: str

    def __post_init__(self) -> None:
        _positive_integer("seed block_length", self.block_length)
        if type(self.seed) is not int or not 0 <= self.seed <= (2**64 - 1):
            raise SelectionInferenceError("bootstrap seed must be uint64")
        digest = _ascii("seed_material_sha256", self.seed_material_sha256)
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise SelectionInferenceError("seed_material_sha256 must be SHA-256")

    def manifest(self) -> dict[str, int | str]:
        return {
            "block_length": self.block_length,
            "seed": self.seed,
            "seed_material_sha256": self.seed_material_sha256,
            "synchronization": "same_block_starts_for_every_family_member",
        }


@dataclass(frozen=True, slots=True)
class HypothesisBlockResult:
    """Raw and simultaneous tail estimates for one registered block length."""

    hypothesis_id: str
    block_length: int
    romano_wolf_rank: int | None
    raw_exceedance_count: int
    raw_point_pvalue_ppm: int
    raw_monte_carlo_upper_pvalue_ppm: int
    synchronized_max_exceedance_count: int
    synchronized_max_point_pvalue_ppm: int
    synchronized_max_monte_carlo_upper_pvalue_ppm: int
    romano_wolf_intersection_exceedance_count: int
    romano_wolf_intersection_point_pvalue_ppm: int
    romano_wolf_intersection_monte_carlo_upper_pvalue_ppm: int
    romano_wolf_stepdown_point_pvalue_ppm: int
    romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm: int

    def __post_init__(self) -> None:
        _ascii("block result hypothesis_id", self.hypothesis_id)
        _positive_integer("block result block_length", self.block_length)
        if self.romano_wolf_rank is not None:
            _positive_integer("romano_wolf_rank", self.romano_wolf_rank)
        for name in (
            "raw_exceedance_count",
            "synchronized_max_exceedance_count",
            "romano_wolf_intersection_exceedance_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SelectionInferenceError(f"{name} must be non-negative")
        for name in (
            "raw_point_pvalue_ppm",
            "raw_monte_carlo_upper_pvalue_ppm",
            "synchronized_max_point_pvalue_ppm",
            "synchronized_max_monte_carlo_upper_pvalue_ppm",
            "romano_wolf_intersection_point_pvalue_ppm",
            "romano_wolf_intersection_monte_carlo_upper_pvalue_ppm",
            "romano_wolf_stepdown_point_pvalue_ppm",
            "romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm",
        ):
            _ppm(name, getattr(self, name))
        if (
            self.raw_monte_carlo_upper_pvalue_ppm
            < self.raw_point_pvalue_ppm
        ):
            raise SelectionInferenceError("raw MC upper cannot be below raw point")
        if (
            self.synchronized_max_monte_carlo_upper_pvalue_ppm
            < self.synchronized_max_point_pvalue_ppm
        ):
            raise SelectionInferenceError(
                "synchronized max MC upper cannot be below point"
            )
        if (
            self.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
            < self.romano_wolf_stepdown_point_pvalue_ppm
        ):
            raise SelectionInferenceError(
                "Romano-Wolf MC upper cannot be below point"
            )

    def manifest(self) -> dict[str, Any]:
        return {
            "block_length": self.block_length,
            "hypothesis_id": self.hypothesis_id,
            "raw": {
                "exceedance_count": self.raw_exceedance_count,
                "monte_carlo_upper_pvalue_ppm": (
                    self.raw_monte_carlo_upper_pvalue_ppm
                ),
                "point_pvalue_ppm": self.raw_point_pvalue_ppm,
            },
            "romano_wolf": {
                "intersection_exceedance_count": (
                    self.romano_wolf_intersection_exceedance_count
                ),
                "intersection_monte_carlo_upper_pvalue_ppm": (
                    self.romano_wolf_intersection_monte_carlo_upper_pvalue_ppm
                ),
                "intersection_point_pvalue_ppm": (
                    self.romano_wolf_intersection_point_pvalue_ppm
                ),
                "rank": self.romano_wolf_rank,
                "stepdown_monte_carlo_upper_pvalue_ppm": (
                    self.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
                ),
                "stepdown_point_pvalue_ppm": (
                    self.romano_wolf_stepdown_point_pvalue_ppm
                ),
            },
            "synchronized_max": {
                "exceedance_count": self.synchronized_max_exceedance_count,
                "monte_carlo_upper_pvalue_ppm": (
                    self.synchronized_max_monte_carlo_upper_pvalue_ppm
                ),
                "point_pvalue_ppm": self.synchronized_max_point_pvalue_ppm,
            },
        }


@dataclass(frozen=True, slots=True)
class HypothesisInferenceResult:
    """Worst-block raw and concurrent-family inference for one hypothesis."""

    hypothesis_id: str
    family_id: str
    family_size: int
    alpha_ppm: int
    evaluable: bool
    observed_sum_micropoints: int
    observed_mean_denominator_days: int
    observed_studentized_statistic_ppb: int
    raw_point_pvalue_ppm: int
    raw_monte_carlo_upper_pvalue_ppm: int
    bonferroni_point_pvalue_ppm: int
    bonferroni_monte_carlo_upper_pvalue_ppm: int
    synchronized_max_point_pvalue_ppm: int
    synchronized_max_monte_carlo_upper_pvalue_ppm: int
    romano_wolf_stepdown_point_pvalue_ppm: int
    romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm: int
    block_results: tuple[HypothesisBlockResult, ...]

    def __post_init__(self) -> None:
        _ascii("hypothesis result hypothesis_id", self.hypothesis_id)
        _ascii("hypothesis result family_id", self.family_id)
        _positive_integer("hypothesis result family_size", self.family_size)
        _ppm("hypothesis result alpha_ppm", self.alpha_ppm, allow_zero=False)
        if type(self.evaluable) is not bool:
            raise SelectionInferenceError("evaluable must be bool")
        if type(self.observed_sum_micropoints) is not int:
            raise SelectionInferenceError("observed sum must be int")
        _positive_integer(
            "observed_mean_denominator_days", self.observed_mean_denominator_days
        )
        if type(self.observed_studentized_statistic_ppb) is not int:
            raise SelectionInferenceError("observed statistic must be int")
        for name in (
            "raw_point_pvalue_ppm",
            "raw_monte_carlo_upper_pvalue_ppm",
            "bonferroni_point_pvalue_ppm",
            "bonferroni_monte_carlo_upper_pvalue_ppm",
            "synchronized_max_point_pvalue_ppm",
            "synchronized_max_monte_carlo_upper_pvalue_ppm",
            "romano_wolf_stepdown_point_pvalue_ppm",
            "romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm",
        ):
            _ppm(name, getattr(self, name))
        if type(self.block_results) is not tuple or not self.block_results:
            raise SelectionInferenceError("block_results must be non-empty tuple")
        if any(
            not isinstance(result, HypothesisBlockResult)
            or result.hypothesis_id != self.hypothesis_id
            for result in self.block_results
        ):
            raise SelectionInferenceError("block_results have wrong hypothesis")
        if self.raw_monte_carlo_upper_pvalue_ppm < self.raw_point_pvalue_ppm:
            raise SelectionInferenceError("raw MC upper cannot be below raw point")
        if (
            self.bonferroni_monte_carlo_upper_pvalue_ppm
            < self.bonferroni_point_pvalue_ppm
        ):
            raise SelectionInferenceError("Bonferroni MC upper cannot be below point")
        if not self.evaluable and any(
            value != PER_MILLION
            for value in (
                self.raw_point_pvalue_ppm,
                self.raw_monte_carlo_upper_pvalue_ppm,
                self.bonferroni_point_pvalue_ppm,
                self.bonferroni_monte_carlo_upper_pvalue_ppm,
                self.synchronized_max_point_pvalue_ppm,
                self.synchronized_max_monte_carlo_upper_pvalue_ppm,
                self.romano_wolf_stepdown_point_pvalue_ppm,
                self.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm,
            )
        ):
            raise SelectionInferenceError(
                "non-evaluable hypotheses must remain conservative"
            )

    def validator_v2_multiplicity(
        self,
        *,
        criterion_id: str = "E01-familywise-selection",
    ) -> MultiplicityAssessment:
        """Return the exact conservative fields accepted by validator v2."""

        assessment = bonferroni_concurrent_family(
            criterion_id=criterion_id,
            family_id=self.family_id,
            family_size=self.family_size,
            raw_pvalue_ppm=self.raw_monte_carlo_upper_pvalue_ppm,
            alpha_ppm=self.alpha_ppm,
        )
        if (
            assessment.adjusted_pvalue_ppm
            != self.bonferroni_monte_carlo_upper_pvalue_ppm
        ):
            raise RuntimeError("validator v2 multiplicity projection drifted")
        return assessment

    def manifest(self) -> dict[str, Any]:
        return {
            "block_results": [result.manifest() for result in self.block_results],
            "evaluable": self.evaluable,
            "family_id": self.family_id,
            "family_size": self.family_size,
            "familywise": {
                "bonferroni": {
                    "monte_carlo_upper_pvalue_ppm": (
                        self.bonferroni_monte_carlo_upper_pvalue_ppm
                    ),
                    "point_pvalue_ppm": self.bonferroni_point_pvalue_ppm,
                    "reject_at_alpha": (
                        self.evaluable
                        and self.bonferroni_monte_carlo_upper_pvalue_ppm
                        <= self.alpha_ppm
                    ),
                },
                "romano_wolf_stepdown": {
                    "monte_carlo_upper_pvalue_ppm": (
                        self.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
                    ),
                    "point_pvalue_ppm": (
                        self.romano_wolf_stepdown_point_pvalue_ppm
                    ),
                    "reject_at_alpha": (
                        self.evaluable
                        and self.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
                        <= self.alpha_ppm
                    ),
                },
                "synchronized_max": {
                    "monte_carlo_upper_pvalue_ppm": (
                        self.synchronized_max_monte_carlo_upper_pvalue_ppm
                    ),
                    "point_pvalue_ppm": (
                        self.synchronized_max_point_pvalue_ppm
                    ),
                    "reject_at_alpha": (
                        self.evaluable
                        and self.synchronized_max_monte_carlo_upper_pvalue_ppm
                        <= self.alpha_ppm
                    ),
                },
            },
            "hypothesis_id": self.hypothesis_id,
            "observed": {
                "mean_denominator_days": self.observed_mean_denominator_days,
                "studentized_statistic_ppb": (
                    self.observed_studentized_statistic_ppb
                ),
                "studentized_statistic_scale": SELECTION_STATISTIC_SCALE,
                "sum_micropoints": self.observed_sum_micropoints,
            },
            "raw": {
                "monte_carlo_upper_pvalue_ppm": (
                    self.raw_monte_carlo_upper_pvalue_ppm
                ),
                "point_pvalue_ppm": self.raw_point_pvalue_ppm,
            },
            "validator_v2_multiplicity": (
                self.validator_v2_multiplicity().manifest()
            ),
        }


@dataclass(frozen=True, slots=True)
class SelectionInferenceResult:
    """Exact simultaneous forest result bound to one input and one plan."""

    plan: SelectionFamilyPlan
    historical_context: HistoricalSearchContext
    date_count: int
    first_date: str
    last_date: str
    calendar_identity: str
    daily_pnl_identity: str
    implementation_sha256: str
    python_version: str
    numpy_version: str
    scipy_version: str
    seeds: tuple[BootstrapSeedRecord, ...]
    hypotheses: tuple[HypothesisInferenceResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, SelectionFamilyPlan):
            raise SelectionInferenceError("plan must be SelectionFamilyPlan")
        if not isinstance(self.historical_context, HistoricalSearchContext):
            raise SelectionInferenceError(
                "historical_context must be HistoricalSearchContext"
            )
        if self.date_count < MINIMUM_DAYS:
            raise SelectionInferenceError("selection result has too few days")
        _strict_date(self.first_date)
        _strict_date(self.last_date)
        if self.first_date > self.last_date:
            raise SelectionInferenceError("selection result dates are reversed")
        for name in ("calendar_identity", "daily_pnl_identity"):
            identity = _ascii(name, getattr(self, name))
            prefix, separator, digest = identity.partition(":")
            if (
                not separator
                or not prefix
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise SelectionInferenceError(f"{name} must contain SHA-256")
        implementation = _ascii(
            "implementation_sha256", self.implementation_sha256
        )
        if len(implementation) != 64 or any(
            character not in "0123456789abcdef" for character in implementation
        ):
            raise SelectionInferenceError("implementation_sha256 must be SHA-256")
        for name in ("python_version", "numpy_version", "scipy_version"):
            _ascii(name, getattr(self, name))
        if type(self.seeds) is not tuple or tuple(
            seed.block_length for seed in self.seeds
        ) != self.plan.block_lengths:
            raise SelectionInferenceError("seed records do not match block plan")
        if tuple(result.hypothesis_id for result in self.hypotheses) != (
            self.plan.hypothesis_ids
        ):
            raise SelectionInferenceError(
                "hypothesis results do not match registered family"
            )
        canonical_bytes(self.manifest())

    def hypothesis(self, hypothesis_id: str) -> HypothesisInferenceResult:
        _ascii("hypothesis lookup", hypothesis_id)
        for result in self.hypotheses:
            if result.hypothesis_id == hypothesis_id:
                return result
        raise KeyError(hypothesis_id)

    def statistical_manifest(self) -> dict[str, Any]:
        """Return the exact inference payload, excluding descriptive history."""

        return {
            "engine_environment": {
                "numpy": self.numpy_version,
                "python": self.python_version,
                "scipy": self.scipy_version,
            },
            "hypotheses": [result.manifest() for result in self.hypotheses],
            "implementation_sha256": self.implementation_sha256,
            "input_binding": {
                "calendar_identity": self.calendar_identity,
                "daily_pnl_identity": self.daily_pnl_identity,
                "date_count": self.date_count,
                "first_date": self.first_date,
                "last_date": self.last_date,
                "missing_day_policy": "exact_shared_calendar_no_implicit_zero_fill",
            },
            "method": {
                "block_aggregation": SELECTION_BLOCK_AGGREGATION,
                "bootstrap": SELECTION_BOOTSTRAP_METHOD,
                "familywise": [
                    SELECTION_BONFERRONI_METHOD,
                    SELECTION_MAX_STATISTIC_METHOD,
                    SELECTION_ROMANO_WOLF_METHOD,
                ],
                "historical_exposure_adjustment": "forbidden",
                "monte_carlo_upper": SELECTION_MONTE_CARLO_UPPER_METHOD,
                "raw_point": SELECTION_RAW_POINT_METHOD,
                "references": list(_METHOD_REFERENCES),
                "resampling_familywise_scope": (
                    "approximate_dependence_aware_fwer_not_finite_sample_guarantee"
                ),
            },
            "plan": self.plan.manifest(),
            "schema": SELECTION_INFERENCE_STATISTICAL_SCHEMA,
            "seeds": [seed.manifest() for seed in self.seeds],
        }

    @property
    def statistical_identity(self) -> str:
        digest = canonical_digest(
            domain="selection-inference-statistical",
            payload=self.statistical_manifest(),
        )
        return f"selection-statistical:{digest}"

    def _result_identity_payload(self) -> dict[str, Any]:
        return {
            "historical_context": self.historical_context.manifest(),
            "schema": SELECTION_INFERENCE_RESULT_SCHEMA,
            "statistical_identity": self.statistical_identity,
            "statistical_manifest": self.statistical_manifest(),
        }

    @property
    def identity(self) -> str:
        digest = canonical_digest(
            domain="selection-inference-result",
            payload=self._result_identity_payload(),
        )
        return f"selection-result:{digest}"

    def manifest(self) -> dict[str, Any]:
        payload = self._result_identity_payload()
        return {
            "historical_context": payload["historical_context"],
            "identity": self.identity,
            "schema": payload["schema"],
            "statistical_identity": payload["statistical_identity"],
            "statistical_manifest": payload["statistical_manifest"],
        }

    def manifest_bytes(self) -> bytes:
        return canonical_bytes(self.manifest())


def _bootstrap_seed(
    *, plan: SelectionFamilyPlan, block_length: int
) -> BootstrapSeedRecord:
    material = (
        f"selection-inference.v2:{plan.base_seed}:{plan.family_id}:"
        f"{plan.stage}:{block_length}"
    ).encode("ascii")
    digest = sha256(material).digest()
    return BootstrapSeedRecord(
        block_length=block_length,
        seed=int.from_bytes(digest[:8], "big"),
        seed_material_sha256=digest.hex(),
    )


def _point_pvalue_ppm(*, exceedances: int, bootstrap_samples: int) -> int:
    numerator = (exceedances + 1) * PER_MILLION
    denominator = bootstrap_samples + 1
    return min(PER_MILLION, (numerator + denominator - 1) // denominator)


def _monte_carlo_upper_pvalue_ppm(
    *,
    exceedances: int,
    bootstrap_samples: int,
    confidence_ppm: int,
) -> int:
    if exceedances >= bootstrap_samples:
        return PER_MILLION
    upper = float(
        beta.ppf(
            confidence_ppm / PER_MILLION,
            exceedances + 1,
            bootstrap_samples - exceedances,
        )
    )
    if not isfinite(upper) or not 0.0 <= upper <= 1.0:
        raise RuntimeError("Monte Carlo upper calculation failed")
    return min(PER_MILLION, int(ceil(upper * PER_MILLION)))


def _tail_values(
    *,
    exceedances: int,
    plan: SelectionFamilyPlan,
) -> tuple[int, int]:
    point = _point_pvalue_ppm(
        exceedances=exceedances,
        bootstrap_samples=plan.bootstrap_samples,
    )
    upper = _monte_carlo_upper_pvalue_ppm(
        exceedances=exceedances,
        bootstrap_samples=plan.bootstrap_samples,
        confidence_ppm=plan.monte_carlo_confidence_ppm,
    )
    if upper < point:
        raise RuntimeError("Monte Carlo upper unexpectedly fell below point")
    return point, upper


def _overlapping_block_sums(values: np.ndarray, length: int) -> np.ndarray:
    zero = np.zeros((1, values.shape[1]), dtype=np.float64)
    cumulative = np.vstack((zero, np.cumsum(values, axis=0, dtype=np.float64)))
    return cumulative[length:] - cumulative[:-length]


def _normalize_daily_pnl(
    *,
    plan: SelectionFamilyPlan,
    daily_pnl_by_hypothesis: DailyPnlFamily,
) -> tuple[np.ndarray, tuple[str, ...], tuple[tuple[int, ...], ...], str, str]:
    if not isinstance(daily_pnl_by_hypothesis, Mapping):
        raise SelectionInferenceError("daily_pnl_by_hypothesis must be a mapping")
    provided_ids: list[str] = []
    for hypothesis_id in daily_pnl_by_hypothesis:
        provided_ids.append(_ascii("daily PnL hypothesis_id", hypothesis_id))
    if set(provided_ids) != set(plan.hypothesis_ids):
        raise SelectionInferenceError(
            "daily PnL keys must exactly match the preregistered family"
        )

    first_series = daily_pnl_by_hypothesis[plan.hypothesis_ids[0]]
    if not isinstance(first_series, Mapping):
        raise SelectionInferenceError("each daily PnL series must be a mapping")
    calendar = tuple(sorted(_strict_date(day) for day in first_series))
    if len(calendar) < MINIMUM_DAYS:
        raise SelectionInferenceError(
            f"selection family requires at least {MINIMUM_DAYS} shared days"
        )
    if len(set(calendar)) != len(calendar):
        raise SelectionInferenceError("daily PnL calendar contains duplicates")

    rows: list[tuple[int, ...]] = []
    series_payload: list[dict[str, Any]] = []
    expected_days = set(calendar)
    for hypothesis_id in plan.hypothesis_ids:
        series = daily_pnl_by_hypothesis[hypothesis_id]
        if not isinstance(series, Mapping):
            raise SelectionInferenceError("each daily PnL series must be a mapping")
        normalized_days = {_strict_date(day) for day in series}
        if normalized_days != expected_days:
            raise SelectionInferenceError(
                "all hypotheses must use the exact same explicit calendar"
            )
        values: list[int] = []
        for day in calendar:
            value = series[day]
            if type(value) is not int:
                raise SelectionInferenceError(
                    "daily PnL values must be integer micropoints"
                )
            values.append(value)
        row = tuple(values)
        rows.append(row)
        series_payload.append(
            {
                "daily_pnl_micropoints": list(row),
                "hypothesis_id": hypothesis_id,
            }
        )

    matrix = np.asarray(rows, dtype=np.float64).T
    if np.any(~np.isfinite(matrix)):
        raise SelectionInferenceError("daily PnL cannot be represented finitely")
    calendar_digest = canonical_digest(
        domain="selection-calendar",
        payload={"dates": list(calendar), "schema": "selection_calendar.v1"},
    )
    pnl_digest = canonical_digest(
        domain="selection-daily-pnl",
        payload={
            "calendar": list(calendar),
            "schema": SELECTION_DAILY_PNL_SCHEMA,
            "series": series_payload,
        },
    )
    return (
        matrix,
        calendar,
        tuple(rows),
        f"calendar:{calendar_digest}",
        f"daily-pnl:{pnl_digest}",
    )


def _observed_statistics(
    *, rows: tuple[tuple[int, ...], ...], date_count: int
) -> tuple[np.ndarray, tuple[bool, ...], tuple[int, ...], tuple[int, ...]]:
    statistics: list[float] = []
    evaluable: list[bool] = []
    sums: list[int] = []
    scaled_statistics: list[int] = []
    for values in rows:
        total = sum(values)
        square_total = sum(value * value for value in values)
        variance_numerator = date_count * square_total - total * total
        is_evaluable = variance_numerator > 0
        statistic = (
            total * sqrt(date_count - 1) / sqrt(variance_numerator)
            if is_evaluable
            else 0.0
        )
        if not isfinite(statistic):
            raise SelectionInferenceError("studentized statistic is non-finite")
        statistics.append(statistic)
        evaluable.append(is_evaluable)
        sums.append(total)
        scaled_statistics.append(round(statistic * SELECTION_STATISTIC_SCALE))
    return (
        np.asarray(statistics, dtype=np.float64),
        tuple(evaluable),
        tuple(sums),
        tuple(scaled_statistics),
    )


def _infer_one_block(
    *,
    plan: SelectionFamilyPlan,
    centered: np.ndarray,
    observed: np.ndarray,
    evaluable: tuple[bool, ...],
    seed_record: BootstrapSeedRecord,
) -> tuple[HypothesisBlockResult, ...]:
    sample_count, hypothesis_count = centered.shape
    block_length = seed_record.block_length
    if block_length >= sample_count:
        raise SelectionInferenceError(
            "each registered block length must be shorter than the calendar"
        )
    active = np.flatnonzero(np.asarray(evaluable, dtype=bool))
    order = tuple(
        sorted(
            (int(index) for index in active),
            key=lambda index: (
                -float(observed[index]),
                plan.hypothesis_ids[index],
            ),
        )
    )
    rank_by_index = {index: rank + 1 for rank, index in enumerate(order)}

    raw_counts = np.zeros(hypothesis_count, dtype=np.int64)
    max_counts = np.zeros(hypothesis_count, dtype=np.int64)
    intersection_counts = np.zeros(hypothesis_count, dtype=np.int64)
    if len(active) == 0:
        raw_counts.fill(plan.bootstrap_samples)
        max_counts.fill(plan.bootstrap_samples)
        intersection_counts.fill(plan.bootstrap_samples)
    else:
        squares = centered * centered
        full_sums = _overlapping_block_sums(centered, block_length)
        full_squares = _overlapping_block_sums(squares, block_length)
        full_count, remainder = divmod(sample_count, block_length)
        partial_sums = (
            None
            if remainder == 0
            else _overlapping_block_sums(centered, remainder)
        )
        partial_squares = (
            None
            if remainder == 0
            else _overlapping_block_sums(squares, remainder)
        )
        rng = np.random.default_rng(seed_record.seed)
        generated = 0
        scale = sqrt(sample_count - 1)
        while generated < plan.bootstrap_samples:
            count = min(256, plan.bootstrap_samples - generated)
            starts = rng.integers(
                0,
                len(full_sums),
                size=(count, full_count),
            )
            draw_sum = full_sums[starts].sum(axis=1)
            draw_square = full_squares[starts].sum(axis=1)
            if partial_sums is not None and partial_squares is not None:
                partial_starts = rng.integers(0, len(partial_sums), size=count)
                draw_sum += partial_sums[partial_starts]
                draw_square += partial_squares[partial_starts]
            variance_numerator = np.maximum(
                0.0,
                sample_count * draw_square - draw_sum * draw_sum,
            )
            bootstrap_statistics = np.divide(
                draw_sum * scale,
                np.sqrt(variance_numerator),
                out=np.zeros_like(draw_sum),
                where=variance_numerator > 0,
            )
            raw_counts += np.sum(
                bootstrap_statistics >= observed[None, :], axis=0
            )
            maximum = np.max(bootstrap_statistics[:, active], axis=1)
            max_counts[active] += np.sum(
                maximum[:, None] >= observed[None, active], axis=0
            )
            for rank, index in enumerate(order):
                remaining = np.asarray(order[rank:], dtype=np.int64)
                remaining_maximum = np.max(
                    bootstrap_statistics[:, remaining], axis=1
                )
                intersection_counts[index] += int(
                    np.sum(remaining_maximum >= observed[index])
                )
            generated += count
        inactive = np.flatnonzero(~np.asarray(evaluable, dtype=bool))
        raw_counts[inactive] = plan.bootstrap_samples
        max_counts[inactive] = plan.bootstrap_samples
        intersection_counts[inactive] = plan.bootstrap_samples

    raw_tail = [
        _tail_values(exceedances=int(count), plan=plan) for count in raw_counts
    ]
    max_tail = [
        _tail_values(exceedances=int(count), plan=plan) for count in max_counts
    ]
    intersection_tail = [
        _tail_values(exceedances=int(count), plan=plan)
        for count in intersection_counts
    ]
    stepdown_point = [PER_MILLION] * hypothesis_count
    stepdown_upper = [PER_MILLION] * hypothesis_count
    prior_point = 0
    prior_upper = 0
    for index in order:
        prior_point = max(prior_point, intersection_tail[index][0])
        prior_upper = max(prior_upper, intersection_tail[index][1])
        stepdown_point[index] = prior_point
        stepdown_upper[index] = prior_upper

    return tuple(
        HypothesisBlockResult(
            hypothesis_id=plan.hypothesis_ids[index],
            block_length=block_length,
            romano_wolf_rank=rank_by_index.get(index),
            raw_exceedance_count=int(raw_counts[index]),
            raw_point_pvalue_ppm=raw_tail[index][0],
            raw_monte_carlo_upper_pvalue_ppm=raw_tail[index][1],
            synchronized_max_exceedance_count=int(max_counts[index]),
            synchronized_max_point_pvalue_ppm=max_tail[index][0],
            synchronized_max_monte_carlo_upper_pvalue_ppm=max_tail[index][1],
            romano_wolf_intersection_exceedance_count=int(
                intersection_counts[index]
            ),
            romano_wolf_intersection_point_pvalue_ppm=(
                intersection_tail[index][0]
            ),
            romano_wolf_intersection_monte_carlo_upper_pvalue_ppm=(
                intersection_tail[index][1]
            ),
            romano_wolf_stepdown_point_pvalue_ppm=stepdown_point[index],
            romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm=(
                stepdown_upper[index]
            ),
        )
        for index in range(hypothesis_count)
    )


def infer_concurrent_selection_family(
    *,
    plan: SelectionFamilyPlan,
    daily_pnl_by_hypothesis: DailyPnlFamily,
    historical_context: HistoricalSearchContext,
) -> SelectionInferenceResult:
    """Infer one exact concurrent family without cumulative-history adjustment."""

    if not isinstance(plan, SelectionFamilyPlan):
        raise SelectionInferenceError("plan must be SelectionFamilyPlan")
    if not isinstance(historical_context, HistoricalSearchContext):
        raise SelectionInferenceError(
            "historical_context must be HistoricalSearchContext"
        )
    matrix, calendar, rows, calendar_identity, pnl_identity = _normalize_daily_pnl(
        plan=plan,
        daily_pnl_by_hypothesis=daily_pnl_by_hypothesis,
    )
    if any(length >= len(calendar) for length in plan.block_lengths):
        raise SelectionInferenceError(
            "each registered block length must be shorter than the calendar"
        )
    observed, evaluable, sums, scaled_statistics = _observed_statistics(
        rows=rows,
        date_count=len(calendar),
    )
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    seeds = tuple(
        _bootstrap_seed(plan=plan, block_length=block_length)
        for block_length in plan.block_lengths
    )
    by_block = tuple(
        _infer_one_block(
            plan=plan,
            centered=centered,
            observed=observed,
            evaluable=evaluable,
            seed_record=seed,
        )
        for seed in seeds
    )
    hypothesis_results: list[HypothesisInferenceResult] = []
    for index, hypothesis_id in enumerate(plan.hypothesis_ids):
        block_results = tuple(result[index] for result in by_block)
        raw_point = max(result.raw_point_pvalue_ppm for result in block_results)
        raw_upper = max(
            result.raw_monte_carlo_upper_pvalue_ppm for result in block_results
        )
        bonferroni_point = min(PER_MILLION, raw_point * plan.family_size)
        bonferroni_upper = min(PER_MILLION, raw_upper * plan.family_size)
        max_point = max(
            result.synchronized_max_point_pvalue_ppm
            for result in block_results
        )
        max_upper = max(
            result.synchronized_max_monte_carlo_upper_pvalue_ppm
            for result in block_results
        )
        stepdown_point = max(
            result.romano_wolf_stepdown_point_pvalue_ppm
            for result in block_results
        )
        stepdown_upper = max(
            result.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
            for result in block_results
        )
        hypothesis_results.append(
            HypothesisInferenceResult(
                hypothesis_id=hypothesis_id,
                family_id=plan.family_id,
                family_size=plan.family_size,
                alpha_ppm=plan.alpha_ppm,
                evaluable=evaluable[index],
                observed_sum_micropoints=sums[index],
                observed_mean_denominator_days=len(calendar),
                observed_studentized_statistic_ppb=scaled_statistics[index],
                raw_point_pvalue_ppm=raw_point,
                raw_monte_carlo_upper_pvalue_ppm=raw_upper,
                bonferroni_point_pvalue_ppm=bonferroni_point,
                bonferroni_monte_carlo_upper_pvalue_ppm=bonferroni_upper,
                synchronized_max_point_pvalue_ppm=max_point,
                synchronized_max_monte_carlo_upper_pvalue_ppm=max_upper,
                romano_wolf_stepdown_point_pvalue_ppm=stepdown_point,
                romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm=(
                    stepdown_upper
                ),
                block_results=block_results,
            )
        )
    return SelectionInferenceResult(
        plan=plan,
        historical_context=historical_context,
        date_count=len(calendar),
        first_date=calendar[0],
        last_date=calendar[-1],
        calendar_identity=calendar_identity,
        daily_pnl_identity=pnl_identity,
        implementation_sha256=selection_inference_implementation_sha256(),
        python_version=".".join(str(value) for value in sys.version_info[:3]),
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
        seeds=seeds,
        hypotheses=tuple(hypothesis_results),
    )


P0_REPLAY_HYPOTHESES = tuple(
    SelectionHypothesis(
        hypothesis_id=member["executable_id"],
        registration_id=f"study:{member['study_id']}",
    )
    for member in load_p0_replay_inventory()
)
P0_REPLAY_EXECUTABLE_IDS = tuple(
    hypothesis.hypothesis_id for hypothesis in P0_REPLAY_HYPOTHESES
)
P0_REPLAY_FAMILY_ID = "family:p0-audit-replay-v1"


def infer_p0_simultaneous_forest(
    daily_pnl_by_executable: DailyPnlFamily,
    *,
    historical_context: HistoricalSearchContext,
    alpha_ppm: int = DEFAULT_ALPHA_PPM,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    block_lengths: tuple[int, ...] = DEFAULT_BLOCK_LENGTHS,
    monte_carlo_confidence_ppm: int = DEFAULT_MONTE_CARLO_CONFIDENCE_PPM,
    base_seed: int = DEFAULT_BASE_SEED,
) -> SelectionInferenceResult:
    """Replay the exact six P0 historical axes as one simultaneous forest."""

    plan = SelectionFamilyPlan(
        family_id=P0_REPLAY_FAMILY_ID,
        stage="discovery",
        hypotheses=P0_REPLAY_HYPOTHESES,
        alpha_ppm=alpha_ppm,
        bootstrap_samples=bootstrap_samples,
        block_lengths=block_lengths,
        monte_carlo_confidence_ppm=monte_carlo_confidence_ppm,
        base_seed=base_seed,
    )
    return infer_concurrent_selection_family(
        plan=plan,
        daily_pnl_by_hypothesis=daily_pnl_by_executable,
        historical_context=historical_context,
    )


__all__ = [
    "BootstrapSeedRecord",
    "DailyPnlFamily",
    "DailyPnlSeries",
    "HistoricalSearchContext",
    "HypothesisBlockResult",
    "HypothesisInferenceResult",
    "P0_REPLAY_EXECUTABLE_IDS",
    "P0_REPLAY_FAMILY_ID",
    "P0_REPLAY_HYPOTHESES",
    "SELECTION_BONFERRONI_METHOD",
    "SELECTION_INFERENCE_PLAN_SCHEMA",
    "SELECTION_INFERENCE_RESULT_SCHEMA",
    "SelectionFamilyPlan",
    "SelectionHypothesis",
    "SelectionInferenceError",
    "SelectionInferenceResult",
    "infer_concurrent_selection_family",
    "infer_p0_simultaneous_forest",
    "selection_inference_implementation_sha256",
]
