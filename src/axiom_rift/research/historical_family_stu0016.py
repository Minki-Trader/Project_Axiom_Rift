"""Exact original-Study authority binding for the STU-0016 family."""

from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
    _build_stu0016_historical_family,
)


STU0016_HISTORICAL_FAMILY: HistoricalFamilySpec = (
    _build_stu0016_historical_family(original_study_id="STU-0016")
)


__all__ = ["STU0016_HISTORICAL_FAMILY"]
