"""Exact original-Study authority binding for the STU-0051 family."""

from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
    _build_stu0051_historical_family,
)


STU0051_HISTORICAL_FAMILY: HistoricalFamilySpec = (
    _build_stu0051_historical_family(original_study_id="STU-0051")
)


__all__ = ["STU0051_HISTORICAL_FAMILY"]
