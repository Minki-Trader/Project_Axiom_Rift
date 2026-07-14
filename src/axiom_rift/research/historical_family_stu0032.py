"""Exact original-Study authority binding for the STU-0032 family."""

from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
    _build_stu0032_historical_family,
)


STU0032_HISTORICAL_FAMILY: HistoricalFamilySpec = (
    _build_stu0032_historical_family(original_study_id="STU-0032")
)


__all__ = ["STU0032_HISTORICAL_FAMILY"]
