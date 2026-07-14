"""Navigation-only catalogs over exact historical-family authority bindings."""

from axiom_rift.research.historical_family_replay import (
    historical_family_catalog,
    historical_family_catalog_digest,
)
from axiom_rift.research.historical_family_stu0016 import (
    STU0016_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0017 import (
    STU0017_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0032 import (
    STU0032_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0048 import (
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0051 import (
    STU0051_HISTORICAL_FAMILY,
)


P1_HISTORICAL_FAMILY_CATALOG = historical_family_catalog(
    (
        STU0048_HISTORICAL_FAMILY,
        STU0051_HISTORICAL_FAMILY,
        STU0032_HISTORICAL_FAMILY,
    )
)
P1_HISTORICAL_FAMILY_CATALOG_DIGEST = historical_family_catalog_digest(
    P1_HISTORICAL_FAMILY_CATALOG
)
P1_ROUTED_HISTORICAL_FAMILY_CATALOG = historical_family_catalog(
    (
        STU0016_HISTORICAL_FAMILY,
        STU0017_HISTORICAL_FAMILY,
    )
)
P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST = (
    historical_family_catalog_digest(P1_ROUTED_HISTORICAL_FAMILY_CATALOG)
)
ALL_P1_HISTORICAL_FAMILY_CATALOG = historical_family_catalog(
    (
        *P1_HISTORICAL_FAMILY_CATALOG,
        *P1_ROUTED_HISTORICAL_FAMILY_CATALOG,
    )
)
ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST = historical_family_catalog_digest(
    ALL_P1_HISTORICAL_FAMILY_CATALOG
)


__all__ = [
    "ALL_P1_HISTORICAL_FAMILY_CATALOG",
    "ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "P1_HISTORICAL_FAMILY_CATALOG",
    "P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG",
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST",
]
