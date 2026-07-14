"""Exact original-Study authority binding for the STU-0048 family."""

from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
    _build_stu0048_historical_family,
)


STU0048_HISTORICAL_FAMILY: HistoricalFamilySpec = (
    _build_stu0048_historical_family(original_study_id="STU-0048")
)


__all__ = ["STU0048_HISTORICAL_FAMILY"]
