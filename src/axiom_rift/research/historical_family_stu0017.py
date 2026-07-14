"""Exact original-Study authority binding for the STU-0017 family."""

from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
    _build_stu0017_historical_family,
)


STU0017_HISTORICAL_FAMILY: HistoricalFamilySpec = (
    _build_stu0017_historical_family(original_study_id="STU-0017")
)


__all__ = ["STU0017_HISTORICAL_FAMILY"]
