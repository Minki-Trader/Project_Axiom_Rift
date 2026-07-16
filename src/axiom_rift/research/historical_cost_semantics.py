"""Typed authority for the frozen completed-period spread-cost audit.

The historical records remain immutable.  This module describes one bounded
audit of results that used ``MqlRates.spread`` as a completed-period cost
proxy.  It does not turn that proxy into a point-in-time quote and it grants no
new scientific, economic, candidate, trial, holdout, or terminal credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


AUDIT_MANIFEST_SCHEMA = "historical_spread_semantics_audit_manifest.v1"
LATCH_SCHEMA = "historical_cost_semantics_latch.v1"
AUDIT_FINDING_ID = "AX-SPREAD-COST-001"
AUDIT_INVENTORY_DOMAIN = "historical-spread-semantics-inventory"
PERMITTED_INTERPRETATION = "completed_period_bar_spread_proxy"
FORBIDDEN_INTERPRETATION = "actual_point_in_time_native_quote"
DEFAULT_SCIENTIFIC_CLASS = "execution_cost_measurement_only"
ENGINEERING_CLASS = "engineering"
AUTHORITY_DELTA_ZERO = {
    "candidate": 0,
    "economic": 0,
    "holdout": 0,
    "scientific": 0,
    "terminal": 0,
    "trial": 0,
}


class HistoricalCostSemanticsError(ValueError):
    """A historical spread-semantics authority object is malformed."""


class HistoricalSpreadSemanticClass(str, Enum):
    """Why a frozen completion depended on completed-period spread."""

    EXECUTION_COST_MEASUREMENT_ONLY = "execution_cost_measurement_only"
    COMPLETED_PERIOD_PROXY_FEATURE = "completed_period_proxy_feature"
    NATIVE_COST_OUTCOME_LABEL_ONLY = "native_cost_outcome_label_only"
    DECISION_SURFACE_COST_DEPENDENT = "decision_surface_cost_dependent"
    CAUSAL_POLICY_COST_STATE_DEPENDENT = "causal_policy_cost_state_dependent"
    ENGINEERING = "engineering"


class HistoricalCostInterpretation(str, Enum):
    """The two meanings that readers must never conflate."""

    COMPLETED_PERIOD_PROXY = PERMITTED_INTERPRETATION
    ACTUAL_POINT_IN_TIME_NATIVE_QUOTE = FORBIDDEN_INTERPRETATION


class HistoricalCostSemanticCriterion(str, Enum):
    """Normalized criteria used by the spread-semantics correction."""

    C01_POSITIVE_REPORTED_COST = "C01-positive-reported-cost"
    C02_STRESS_RESILIENCE = "C02-stress-resilience"
    C03_DECISION_TIME_CAUSALITY = "C03-decision-time-causality"
    C04_UNKNOWN_COST_RESOLUTION = "C04-unknown-cost-resolution"
    C05_FIXED_LOT_PROFIT_FACTOR = "C05-fixed-lot-profit-factor"


class HistoricalCostQualificationState(str, Enum):
    """Effective authority after separating proxy from actual-cost meaning."""

    PRESERVED_EXACT_PROXY_ONLY = "preserved_exact_proxy_only"
    PRESERVED_INDEPENDENT = "preserved_independent"
    UNRESOLVED = "unresolved"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    ENGINEERING_NOT_APPLICABLE = "engineering_not_applicable"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise HistoricalCostSemanticsError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise HistoricalCostSemanticsError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _ascii_tuple(
    name: str,
    value: object,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple or (not allow_empty and not value):
        qualifier = "a tuple" if allow_empty else "a non-empty tuple"
        raise HistoricalCostSemanticsError(f"{name} must be {qualifier}")
    resolved = tuple(sorted(_ascii(name, item) for item in value))
    if len(resolved) != len(set(resolved)):
        raise HistoricalCostSemanticsError(f"{name} must be unique")
    return resolved


def _digest_tuple(name: str, value: object) -> tuple[str, ...]:
    resolved = _ascii_tuple(name, value)
    for item in resolved:
        _digest(name, item)
    return resolved


def _study_tuple(name: str, value: object) -> tuple[str, ...]:
    resolved = _ascii_tuple(name, value)
    if any(not item.startswith("STU-") for item in resolved):
        raise HistoricalCostSemanticsError(f"{name} must contain Study ids")
    return resolved


def _zero_authority_delta(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == set(AUTHORITY_DELTA_ZERO)
        and all(type(value[name]) is int and value[name] == 0 for name in value)
    )


@dataclass(frozen=True, slots=True, order=True)
class HistoricalAuthorityCursor:
    """One exact upper Journal authority boundary for the frozen audit."""

    sequence: int
    event_id: str
    offset: int

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise HistoricalCostSemanticsError(
                "authority cursor sequence must be a positive integer"
            )
        _digest("authority cursor event id", self.event_id)
        if type(self.offset) is not int or self.offset < 0:
            raise HistoricalCostSemanticsError(
                "authority cursor offset must be a non-negative integer"
            )

    def manifest(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "offset": self.offset,
            "sequence": self.sequence,
        }

    @classmethod
    def from_mapping(cls, value: object) -> HistoricalAuthorityCursor:
        if not isinstance(value, Mapping) or set(value) != {
            "event_id",
            "offset",
            "sequence",
        }:
            raise HistoricalCostSemanticsError("authority cursor is malformed")
        try:
            return cls(
                sequence=value["sequence"],  # type: ignore[arg-type]
                event_id=value["event_id"],  # type: ignore[arg-type]
                offset=value["offset"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalCostSemanticsError(
                "authority cursor cannot be rebuilt"
            ) from exc


PRODUCTION_UPPER_CURSOR = HistoricalAuthorityCursor(
    sequence=5385,
    event_id="6b47964a60a8490e76ce921945071f282be61334e27706093bd51469ae519f65",
    offset=44173137,
)


@dataclass(frozen=True, slots=True, order=True)
class HistoricalInventorySeal:
    """Count and canonical digest of one exact sorted record-id inventory."""

    inventory_class: str
    record_count: int
    record_ids_digest: str

    def __post_init__(self) -> None:
        label = _ascii("inventory class", self.inventory_class)
        if any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in label
        ):
            raise HistoricalCostSemanticsError("inventory class is not canonical")
        if type(self.record_count) is not int or self.record_count < 0:
            raise HistoricalCostSemanticsError(
                "inventory record count must be a non-negative integer"
            )
        _digest("inventory record ids digest", self.record_ids_digest)

    def manifest(self) -> dict[str, Any]:
        return {
            "inventory_class": self.inventory_class,
            "record_count": self.record_count,
            "record_ids_digest": self.record_ids_digest,
        }

    @classmethod
    def from_mapping(cls, value: object) -> HistoricalInventorySeal:
        if not isinstance(value, Mapping) or set(value) != {
            "inventory_class",
            "record_count",
            "record_ids_digest",
        }:
            raise HistoricalCostSemanticsError("inventory seal is malformed")
        try:
            return cls(
                inventory_class=value["inventory_class"],  # type: ignore[arg-type]
                record_count=value["record_count"],  # type: ignore[arg-type]
                record_ids_digest=value["record_ids_digest"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalCostSemanticsError(
                "inventory seal cannot be rebuilt"
            ) from exc


def historical_inventory_digest(
    inventory_class: str,
    record_ids: tuple[str, ...],
) -> str:
    """Return the canonical audit digest for one sorted unique inventory."""

    label = _ascii("inventory class", inventory_class)
    ids = _ascii_tuple("record ids", record_ids, allow_empty=True)
    return canonical_digest(
        domain=AUDIT_INVENTORY_DOMAIN,
        payload={"class": label, "record_ids": list(ids)},
    )


GOLDEN_INVENTORY_SEALS = (
    HistoricalInventorySeal(
        inventory_class="adjudication",
        record_count=444,
        record_ids_digest="12fd4a6947abd880cca8f81e1ff46bea9b64b47fc93cdbb72e7be0779527c6af",
    ),
    HistoricalInventorySeal(
        inventory_class="b_only_study_operations",
        record_count=93,
        record_ids_digest="03309a5846e1df2d353247d2d1030e52a6c3fbc9f4298e74d31924850d359394",
    ),
    HistoricalInventorySeal(
        inventory_class="completion",
        record_count=501,
        record_ids_digest="6da1d79ad925b596f18d5ef2f42ecdeaa8c83fa4c0baf032968bcdc64b0b9a33",
    ),
    HistoricalInventorySeal(
        inventory_class="negative_memory",
        record_count=438,
        record_ids_digest="4e8965d5a2e1b76f16b3520d6812d8bff5b712f9fafb4d02c3cb127e811b1de4",
    ),
    HistoricalInventorySeal(
        inventory_class="scientific_completion",
        record_count=488,
        record_ids_digest="f406cd94f82581367a7f52851e63e5799c9e81c8f7343b0e307051447fb501f9",
    ),
    HistoricalInventorySeal(
        inventory_class="scientific_executable",
        record_count=487,
        record_ids_digest="68cebe34170a1a185c5ff2acd787f343c0d85c1fbcfb6e442bb183c4328b8162",
    ),
)


GOLDEN_CLASS_COMPLETION_SEALS = (
    HistoricalInventorySeal(
        inventory_class="causal_policy_cost_state_dependent",
        record_count=1,
        record_ids_digest="17b7325b0d8c5e4e6283a422f63402051e17faf7287718a3ccf6e9fd128ee047",
    ),
    HistoricalInventorySeal(
        inventory_class="completed_period_proxy_feature",
        record_count=8,
        record_ids_digest="3b3616ac0bace7fd03edaf9c517436caa94c62f90e8fafdceae33e5cb073262d",
    ),
    HistoricalInventorySeal(
        inventory_class="decision_surface_cost_dependent",
        record_count=6,
        record_ids_digest="6e2e36db78fbb90d38597ed9e82bef6ae783c02d2f805f0898eee194637dafe2",
    ),
    HistoricalInventorySeal(
        inventory_class="engineering",
        record_count=13,
        record_ids_digest="8df1375d82b2aefd99ed510fa99c106adfc05ecabd2e8e3a66ed43ea699902d6",
    ),
    HistoricalInventorySeal(
        inventory_class="execution_cost_measurement_only",
        record_count=437,
        record_ids_digest="7182be317eba0341bb540bcb9532ba384a0d4d5efeca588d122abf39778eb821",
    ),
    HistoricalInventorySeal(
        inventory_class="native_cost_outcome_label_only",
        record_count=36,
        record_ids_digest="37a5d7bb36533423e3b384052a45246b3dfde67222831701df26084dad95529c",
    ),
)


EXCEPTIONAL_STUDY_CLASSES = {
    HistoricalSpreadSemanticClass.COMPLETED_PERIOD_PROXY_FEATURE: (
        "STU-0036",
        "STU-0037",
    ),
    HistoricalSpreadSemanticClass.NATIVE_COST_OUTCOME_LABEL_ONLY: (
        "STU-0109",
        "STU-0110",
        "STU-0111",
    ),
    HistoricalSpreadSemanticClass.DECISION_SURFACE_COST_DEPENDENT: (
        "STU-0069",
        "STU-0093",
        "STU-0100",
    ),
    HistoricalSpreadSemanticClass.CAUSAL_POLICY_COST_STATE_DEPENDENT: (
        "STU-0082",
    ),
}


CAUSAL_INVALID_STUDY_CONTEXT_IDS = (
    "STU-0046",
    "STU-0047",
    "STU-0048",
    "STU-0049",
    "STU-0050",
    "STU-0051",
    "STU-0070",
    "STU-0071",
    "STU-0101",
    "STU-0107",
    "STU-0108",
)


CAUSAL_INVALID_COMPLETION_IDS = tuple(
    sorted(
        {
            "042dd7f36d8c9ce736aaed5bf60e51587fbdc9b5390cff555d98cf03c8b8cc20",
            "052b500f8c15977f81eaaf4b576f4931332bf20dc9efba0e02ca0ae8f59555f8",
            "0ba922d930f76fe9a38cb07644a488ee735608ecffc7e257e441b02883c63032",
            "0cb2d6613ff011a2261bf9d72d72b249207c295c35f255cceba5e030b7aab8eb",
            "0cdd5aa1ee1aac2ac38a37a28ccb4f7ed02293ee52f10f85f09a84435a7fe348",
            "0e396a98308e99792591ad8dd1b80b8ce26c69825bb68e00606173dda7a6d3f8",
            "1b08305e8dd61d949e0da83cd605a754497fa23d0ca31404b2d8da33b4f65987",
            "1e27ee01a1463867bb7fbc51e75207f68d0974e80b859edc1b897531de3e53ab",
            "22bb311ac594f45b09e7b415bded67e8ea538774ebc30b599ad82aec6798ee89",
            "22c2fd40ad0402e853e241c6a11de4b2b7d48dfc08f22ce3de3ba475e1e1c7df",
            "2cd40c38e0ad9b12c30e4924d5e00c83c72c38c8a557c2905f86d5647ed73e98",
            "3253b3bdb53cd8f616d518c26b4878b6a9baa19e4b1e5667658e9d2c9e0f6b07",
            "333cf1f646f57f6c22c04d8b636632895038cdce6eafe4dd5b98bf2681c435f2",
            "3808ce7007c72be7f544f1c5544703c3e3ac4fd9e0c973bd10f06c3e46fb0b7c",
            "3e9be3c9ee275086057cada682ff4972320aa696f3d980a2b7b273854aa5a86a",
            "446b9dd0ab77ab07de189219c22b8ba415017c35708fa5d6235abb33baf66937",
            "57874787f16c8bce535c5053abc0e8715657b59ff29b6a85519bedf08bb4f5d0",
            "582b58fa7e3307810f361cb4f9a1e44b7abc3a5f36c1149dc5fea77a72cdb588",
            "5c310f460fffd7c4860b314803a8d097ff701a6dcf797d8fe68849a6aca717ec",
            "5db9989132c98e59e1a50846b3e154915ba7abcc5bfb4aaf50f2dce3babd46d4",
            "731e78ec1fa83c667d0370d600de6b4ced384cde60499fa47f07f04c81047d03",
            "73bcc20c962cef7416c6103ece2fc2e15032dcf6bd4ba0525306f89396d8d463",
            "73ffa93885fbbaf01aedd50249967de8cd8bce39c78a34ac1d697b393055c949",
            "79093acbbaef954af968025dc880ef4a45551d434fa531da5a97c74e9d9b2bd2",
            "9765f44d5c872bcba69cd3838b0758e7978720e3926cadd78e91d42e020eb1d8",
            "ac28e7085040b2a2ccf322479ff7fb2489ffc35fd39841d137c4742256459e3c",
            "b818329c02cd39132c9364e9851c79bd9b5dfcd085f866fccd59153f4d7bca7c",
            "bb7a48ef9c57db1470e6666e4fe0582ac0fcfedaa2f4b3b640724375dcf9ad5e",
            "cbadcc0ef76b06b5754572c9beed8f9aae036a7fcc99f4531100ddd44ecca32b",
            "cd7e66658754e052cf0dbef8296d3fddcdd2a05ceefaeea55eea56088e5ef2ec",
            "d3f37c9f6e8c050636d65f435483f81ff12b3e83d0f33d0610c2985590bf0865",
            "e06b4c91ae469ebca10c009df0d39821f2d12ce03f25de57bce9099b99e13f8c",
            "ec5c6c588d444c227cd5771b6bdf9ac4b9a7ac96181f7037322ef25abc987d63",
            "ee301c9a3fdebbc0acb3120694437164cf677bf26eb45252db56be4e77676443",
            "f4d20c3358fc7dd535050917b6775f549f5495610f05923502cbfab993a66464",
        }
    )
)


# The set literal above deliberately catches transcription duplicates.  The
# exact audit inventory is 35 records, so fail during import if it ever drifts.
if len(CAUSAL_INVALID_COMPLETION_IDS) != 35:  # pragma: no cover - import guard
    raise RuntimeError("causal invalid completion inventory transcription drifted")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalSpreadSemanticsAuditManifest:
    """Canonical sealed description of the one frozen historical audit."""

    audit_artifact_hash: str
    upper_authority_cursor: HistoricalAuthorityCursor
    causal_invalid_completion_ids: tuple[str, ...]
    causal_invalid_study_context_ids: tuple[str, ...]
    audited_cost_contracts: tuple[str, ...]
    exceptional_study_classes: tuple[
        tuple[HistoricalSpreadSemanticClass, tuple[str, ...]], ...
    ]
    inventory_seals: tuple[HistoricalInventorySeal, ...]
    class_completion_seals: tuple[HistoricalInventorySeal, ...]
    audit_finding_id: str = AUDIT_FINDING_ID
    permitted_interpretation: str = PERMITTED_INTERPRETATION
    forbidden_interpretation: str = FORBIDDEN_INTERPRETATION
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("audit artifact hash", self.audit_artifact_hash)
        if self.upper_authority_cursor != PRODUCTION_UPPER_CURSOR:
            raise HistoricalCostSemanticsError(
                "spread audit cursor is not the frozen production boundary"
            )
        excluded = _digest_tuple(
            "causal invalid completion ids",
            self.causal_invalid_completion_ids,
        )
        if excluded != CAUSAL_INVALID_COMPLETION_IDS:
            raise HistoricalCostSemanticsError(
                "spread audit must exclude the exact 35-record causal inventory"
            )
        excluded_studies = _study_tuple(
            "causal invalid Study context ids",
            self.causal_invalid_study_context_ids,
        )
        if excluded_studies != CAUSAL_INVALID_STUDY_CONTEXT_IDS:
            raise HistoricalCostSemanticsError(
                "spread audit must exclude the exact 11-Study causal inventory"
            )
        contracts = _ascii_tuple(
            "audited cost contracts",
            self.audited_cost_contracts,
        )
        if any(
            not item.startswith("cost:") or "spread" not in item.casefold()
            for item in contracts
        ):
            raise HistoricalCostSemanticsError(
                "audited contracts must be exact spread cost contracts"
            )
        rules = self.exceptional_study_classes
        if type(rules) is not tuple or not rules:
            raise HistoricalCostSemanticsError(
                "exceptional Study classes must be a non-empty tuple"
            )
        normalized_rules: list[
            tuple[HistoricalSpreadSemanticClass, tuple[str, ...]]
        ] = []
        for item in rules:
            if (
                type(item) is not tuple
                or len(item) != 2
                or not isinstance(item[0], HistoricalSpreadSemanticClass)
                or item[0]
                in {
                    HistoricalSpreadSemanticClass.EXECUTION_COST_MEASUREMENT_ONLY,
                    HistoricalSpreadSemanticClass.ENGINEERING,
                }
            ):
                raise HistoricalCostSemanticsError(
                    "exceptional Study class rule is malformed"
                )
            normalized_rules.append(
                (item[0], _study_tuple("exceptional Study ids", item[1]))
            )
        normalized = tuple(sorted(normalized_rules, key=lambda item: item[0].value))
        if len({item[0] for item in normalized}) != len(normalized):
            raise HistoricalCostSemanticsError(
                "exceptional semantic classes must be unique"
            )
        all_studies = tuple(study for _, studies in normalized for study in studies)
        if len(all_studies) != len(set(all_studies)):
            raise HistoricalCostSemanticsError(
                "one Study cannot belong to two spread semantic classes"
            )
        expected_rules = tuple(
            sorted(EXCEPTIONAL_STUDY_CLASSES.items(), key=lambda item: item[0].value)
        )
        if normalized != expected_rules:
            raise HistoricalCostSemanticsError(
                "exceptional Study classification differs from the bound audit"
            )
        seals = tuple(sorted(self.inventory_seals))
        class_seals = tuple(sorted(self.class_completion_seals))
        if seals != GOLDEN_INVENTORY_SEALS:
            raise HistoricalCostSemanticsError(
                "spread audit aggregate inventory seals are not golden"
            )
        if class_seals != GOLDEN_CLASS_COMPLETION_SEALS:
            raise HistoricalCostSemanticsError(
                "spread audit semantic-class seals are not golden"
            )
        if self.audit_finding_id != AUDIT_FINDING_ID:
            raise HistoricalCostSemanticsError("spread audit finding id is invalid")
        if self.permitted_interpretation != PERMITTED_INTERPRETATION:
            raise HistoricalCostSemanticsError(
                "completed-period proxy interpretation is not exact"
            )
        if self.forbidden_interpretation != FORBIDDEN_INTERPRETATION:
            raise HistoricalCostSemanticsError(
                "actual native quote interpretation is not fail-closed"
            )
        object.__setattr__(self, "causal_invalid_completion_ids", excluded)
        object.__setattr__(
            self,
            "causal_invalid_study_context_ids",
            excluded_studies,
        )
        object.__setattr__(self, "audited_cost_contracts", contracts)
        object.__setattr__(self, "exceptional_study_classes", normalized)
        object.__setattr__(self, "inventory_seals", seals)
        object.__setattr__(self, "class_completion_seals", class_seals)
        object.__setattr__(
            self,
            "identity",
            "historical-spread-semantics-audit:"
            + canonical_digest(
                domain="historical-spread-semantics-audit-manifest",
                payload=self.to_payload(),
            ),
        )

    @property
    def artifact_hash(self) -> str:
        return sha256(canonical_bytes(self.to_payload())).hexdigest()

    def require_report(self, document: bytes) -> None:
        """Bind the manifest to the exact ASCII audit finding it describes.

        The content address binds every report byte.  The finding checks below
        additionally prevent a correctly hashed but semantically unrelated
        document from activating the historical-cost reader qualification.
        """

        if type(document) is not bytes:
            raise HistoricalCostSemanticsError(
                "historical spread audit report must be bytes"
            )
        if sha256(document).hexdigest() != self.audit_artifact_hash:
            raise HistoricalCostSemanticsError(
                "historical spread audit report hash does not match the manifest"
            )
        try:
            lines = document.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise HistoricalCostSemanticsError(
                "historical spread audit report must be ASCII"
            ) from exc

        heading = f"- {self.audit_finding_id}:"
        starts = [position for position, line in enumerate(lines) if line == heading]
        heading_aliases = [
            line
            for line in lines
            if line.startswith(f"- {self.audit_finding_id}")
        ]
        if len(starts) != 1 or heading_aliases != [heading]:
            raise HistoricalCostSemanticsError(
                "historical spread audit cost finding must be unique"
            )
        start = starts[0]
        end = len(lines)
        for position in range(start + 1, len(lines)):
            line = lines[position]
            if line.startswith("- AX-") and line.endswith(":"):
                end = position
                break
        finding = lines[start + 1 : end]

        inventory = {
            item.inventory_class: item for item in self.inventory_seals
        }
        classes = {
            item.inventory_class: item for item in self.class_completion_seals
        }
        required = (
            (
                "spread cost Study operation count "
                f"{inventory['b_only_study_operations'].record_count + len(self.causal_invalid_study_context_ids)}"
            ),
            (
                "causal invalid A Study context count "
                f"{len(self.causal_invalid_study_context_ids)}"
            ),
            (
                "proxy-only B Study operation count "
                f"{inventory['b_only_study_operations'].record_count}"
            ),
            (
                "proxy-only B completion count "
                f"{inventory['completion'].record_count}"
            ),
            (
                "proxy-only B scientific completion count "
                f"{inventory['scientific_completion'].record_count}"
            ),
            (
                "proxy-only B engineering completion count "
                f"{classes[ENGINEERING_CLASS].record_count}"
            ),
            (
                "proxy-only B negative memory count "
                f"{inventory['negative_memory'].record_count}"
            ),
            (
                "proxy-only B historical adjudication count "
                f"{inventory['adjudication'].record_count}"
            ),
            f"authority Journal sequence {self.upper_authority_cursor.sequence}",
            f"authority Journal event {self.upper_authority_cursor.event_id}",
            (
                "Study operation inventory digest "
                f"{inventory['b_only_study_operations'].record_ids_digest}"
            ),
            (
                "completion inventory digest "
                f"{inventory['completion'].record_ids_digest}"
            ),
            (
                "scientific completion inventory digest "
                f"{inventory['scientific_completion'].record_ids_digest}"
            ),
            (
                "scientific Executable inventory digest "
                f"{inventory['scientific_executable'].record_ids_digest}"
            ),
            (
                "adjudication inventory digest "
                f"{inventory['adjudication'].record_ids_digest}"
            ),
            (
                "negative memory inventory digest "
                f"{inventory['negative_memory'].record_ids_digest}"
            ),
            *(
                (
                    f"{semantic_class.value} scientific completion count "
                    f"{classes[semantic_class.value].record_count}"
                )
                for semantic_class in HistoricalSpreadSemanticClass
                if semantic_class is not HistoricalSpreadSemanticClass.ENGINEERING
            ),
            f"permitted historical interpretation {self.permitted_interpretation}",
            f"forbidden historical interpretation {self.forbidden_interpretation}",
        )
        expected_lines = tuple(f"  {line}" for line in required)
        for expected in expected_lines:
            prefix = expected.rsplit(" ", 1)[0] + " "
            matching = tuple(line for line in finding if line.startswith(prefix))
            if matching != (expected,):
                raise HistoricalCostSemanticsError(
                    "historical spread audit cost finding differs from the "
                    "manifest binding"
                )

    def to_payload(self) -> dict[str, Any]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            "audit_finding_id": self.audit_finding_id,
            "audited_cost_contracts": list(self.audited_cost_contracts),
            "causal_invalid_completion_ids": list(
                self.causal_invalid_completion_ids
            ),
            "causal_invalid_study_context_ids": list(
                self.causal_invalid_study_context_ids
            ),
            "class_completion_seals": [
                item.manifest() for item in self.class_completion_seals
            ],
            "default_scientific_class": DEFAULT_SCIENTIFIC_CLASS,
            "engineering_class": ENGINEERING_CLASS,
            "exceptional_study_classes": [
                {
                    "semantic_class": semantic_class.value,
                    "study_ids": list(study_ids),
                }
                for semantic_class, study_ids in self.exceptional_study_classes
            ],
            "forbidden_interpretation": self.forbidden_interpretation,
            "inventory_seals": [item.manifest() for item in self.inventory_seals],
            "permitted_interpretation": self.permitted_interpretation,
            "schema": AUDIT_MANIFEST_SCHEMA,
            "upper_authority_cursor": self.upper_authority_cursor.manifest(),
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
    ) -> HistoricalSpreadSemanticsAuditManifest:
        expected = {
            "audit_artifact_hash",
            "audit_finding_id",
            "audited_cost_contracts",
            "causal_invalid_completion_ids",
            "causal_invalid_study_context_ids",
            "class_completion_seals",
            "default_scientific_class",
            "engineering_class",
            "exceptional_study_classes",
            "forbidden_interpretation",
            "inventory_seals",
            "permitted_interpretation",
            "schema",
            "upper_authority_cursor",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected
            or value.get("schema") != AUDIT_MANIFEST_SCHEMA
            or value.get("default_scientific_class") != DEFAULT_SCIENTIFIC_CLASS
            or value.get("engineering_class") != ENGINEERING_CLASS
            or any(
                not isinstance(value.get(name), list)
                for name in (
                    "audited_cost_contracts",
                    "causal_invalid_completion_ids",
                    "causal_invalid_study_context_ids",
                    "class_completion_seals",
                    "exceptional_study_classes",
                    "inventory_seals",
                )
            )
        ):
            raise HistoricalCostSemanticsError(
                "historical spread semantics manifest is malformed"
            )
        try:
            rules = []
            for item in value["exceptional_study_classes"]:  # type: ignore[index]
                if not isinstance(item, Mapping) or set(item) != {
                    "semantic_class",
                    "study_ids",
                } or not isinstance(item.get("study_ids"), list):
                    raise HistoricalCostSemanticsError(
                        "historical spread Study rule is malformed"
                    )
                rules.append(
                    (
                        HistoricalSpreadSemanticClass(item["semantic_class"]),
                        tuple(item["study_ids"]),
                    )
                )
            manifest = cls(
                audit_artifact_hash=value["audit_artifact_hash"],  # type: ignore[arg-type]
                upper_authority_cursor=HistoricalAuthorityCursor.from_mapping(
                    value["upper_authority_cursor"]
                ),
                causal_invalid_completion_ids=tuple(
                    value["causal_invalid_completion_ids"]  # type: ignore[arg-type]
                ),
                causal_invalid_study_context_ids=tuple(
                    value["causal_invalid_study_context_ids"]  # type: ignore[arg-type]
                ),
                audited_cost_contracts=tuple(
                    value["audited_cost_contracts"]  # type: ignore[arg-type]
                ),
                exceptional_study_classes=tuple(rules),
                inventory_seals=tuple(
                    HistoricalInventorySeal.from_mapping(item)
                    for item in value["inventory_seals"]  # type: ignore[union-attr]
                ),
                class_completion_seals=tuple(
                    HistoricalInventorySeal.from_mapping(item)
                    for item in value["class_completion_seals"]  # type: ignore[union-attr]
                ),
                audit_finding_id=value["audit_finding_id"],  # type: ignore[arg-type]
                permitted_interpretation=value["permitted_interpretation"],  # type: ignore[arg-type]
                forbidden_interpretation=value["forbidden_interpretation"],  # type: ignore[arg-type]
            )
        except HistoricalCostSemanticsError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalCostSemanticsError(
                "historical spread semantics manifest cannot be rebuilt"
            ) from exc
        if manifest.to_payload() != dict(value):
            raise HistoricalCostSemanticsError(
                "historical spread semantics manifest changed on rebuild"
            )
        return manifest

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
    ) -> HistoricalSpreadSemanticsAuditManifest:
        return cls.from_mapping(parse_canonical(document))


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalCostSemanticsLatch:
    """Monotone zero-credit latch activating one exact audit manifest."""

    audit_manifest_hash: str
    audit_manifest_identity: str
    upper_authority_cursor: HistoricalAuthorityCursor
    inventory_seals: tuple[HistoricalInventorySeal, ...]
    class_completion_seals: tuple[HistoricalInventorySeal, ...]
    audit_finding_id: str = AUDIT_FINDING_ID
    permitted_interpretation: str = PERMITTED_INTERPRETATION
    forbidden_interpretation: str = FORBIDDEN_INTERPRETATION
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("audit manifest hash", self.audit_manifest_hash)
        identity = _ascii("audit manifest identity", self.audit_manifest_identity)
        prefix = "historical-spread-semantics-audit:"
        if not identity.startswith(prefix):
            raise HistoricalCostSemanticsError(
                "audit manifest identity uses another namespace"
            )
        _digest("audit manifest identity digest", identity.removeprefix(prefix))
        if self.upper_authority_cursor != PRODUCTION_UPPER_CURSOR:
            raise HistoricalCostSemanticsError(
                "historical cost latch cursor is not exact"
            )
        seals = tuple(sorted(self.inventory_seals))
        class_seals = tuple(sorted(self.class_completion_seals))
        if seals != GOLDEN_INVENTORY_SEALS or class_seals != (
            GOLDEN_CLASS_COMPLETION_SEALS
        ):
            raise HistoricalCostSemanticsError(
                "historical cost latch inventory is not golden"
            )
        if (
            self.audit_finding_id != AUDIT_FINDING_ID
            or self.permitted_interpretation != PERMITTED_INTERPRETATION
            or self.forbidden_interpretation != FORBIDDEN_INTERPRETATION
        ):
            raise HistoricalCostSemanticsError(
                "historical cost latch semantics are not exact"
            )
        object.__setattr__(self, "inventory_seals", seals)
        object.__setattr__(self, "class_completion_seals", class_seals)
        object.__setattr__(
            self,
            "identity",
            "historical-cost-semantics-latch:"
            + canonical_digest(
                domain="historical-cost-semantics-latch",
                payload=self.to_payload(),
            ),
        )

    @classmethod
    def from_audit_manifest(
        cls,
        manifest: HistoricalSpreadSemanticsAuditManifest,
    ) -> HistoricalCostSemanticsLatch:
        if not isinstance(manifest, HistoricalSpreadSemanticsAuditManifest):
            raise HistoricalCostSemanticsError("audit manifest is not typed")
        return cls(
            audit_manifest_hash=manifest.artifact_hash,
            audit_manifest_identity=manifest.identity,
            upper_authority_cursor=manifest.upper_authority_cursor,
            inventory_seals=manifest.inventory_seals,
            class_completion_seals=manifest.class_completion_seals,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "audit_finding_id": self.audit_finding_id,
            "audit_manifest_hash": self.audit_manifest_hash,
            "audit_manifest_identity": self.audit_manifest_identity,
            "authority_delta": dict(AUTHORITY_DELTA_ZERO),
            "class_completion_seals": [
                item.manifest() for item in self.class_completion_seals
            ],
            "forbidden_interpretation": self.forbidden_interpretation,
            "inventory_seals": [item.manifest() for item in self.inventory_seals],
            "permitted_interpretation": self.permitted_interpretation,
            "schema": LATCH_SCHEMA,
            "upper_authority_cursor": self.upper_authority_cursor.manifest(),
        }

    @classmethod
    def from_mapping(cls, value: object) -> HistoricalCostSemanticsLatch:
        expected = {
            "audit_finding_id",
            "audit_manifest_hash",
            "audit_manifest_identity",
            "authority_delta",
            "class_completion_seals",
            "forbidden_interpretation",
            "inventory_seals",
            "permitted_interpretation",
            "schema",
            "upper_authority_cursor",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected
            or value.get("schema") != LATCH_SCHEMA
            or not _zero_authority_delta(value.get("authority_delta"))
            or not isinstance(value.get("inventory_seals"), list)
            or not isinstance(value.get("class_completion_seals"), list)
        ):
            raise HistoricalCostSemanticsError(
                "historical cost semantics latch is malformed"
            )
        try:
            latch = cls(
                audit_manifest_hash=value["audit_manifest_hash"],  # type: ignore[arg-type]
                audit_manifest_identity=value["audit_manifest_identity"],  # type: ignore[arg-type]
                upper_authority_cursor=HistoricalAuthorityCursor.from_mapping(
                    value["upper_authority_cursor"]
                ),
                inventory_seals=tuple(
                    HistoricalInventorySeal.from_mapping(item)
                    for item in value["inventory_seals"]  # type: ignore[union-attr]
                ),
                class_completion_seals=tuple(
                    HistoricalInventorySeal.from_mapping(item)
                    for item in value["class_completion_seals"]  # type: ignore[union-attr]
                ),
                audit_finding_id=value["audit_finding_id"],  # type: ignore[arg-type]
                permitted_interpretation=value["permitted_interpretation"],  # type: ignore[arg-type]
                forbidden_interpretation=value["forbidden_interpretation"],  # type: ignore[arg-type]
            )
        except HistoricalCostSemanticsError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalCostSemanticsError(
                "historical cost semantics latch cannot be rebuilt"
            ) from exc
        if latch.to_payload() != dict(value):
            raise HistoricalCostSemanticsError(
                "historical cost semantics latch changed on rebuild"
            )
        return latch

    @classmethod
    def from_bytes(cls, document: bytes) -> HistoricalCostSemanticsLatch:
        return cls.from_mapping(parse_canonical(document))


def historical_spread_semantics_audit_manifest_from_payload(
    value: object,
) -> HistoricalSpreadSemanticsAuditManifest:
    return HistoricalSpreadSemanticsAuditManifest.from_mapping(value)


def historical_spread_semantics_audit_manifest_from_bytes(
    document: bytes,
) -> HistoricalSpreadSemanticsAuditManifest:
    return HistoricalSpreadSemanticsAuditManifest.from_bytes(document)


def historical_cost_semantics_latch_from_payload(
    value: object,
) -> HistoricalCostSemanticsLatch:
    return HistoricalCostSemanticsLatch.from_mapping(value)


def historical_cost_semantics_latch_from_bytes(
    document: bytes,
) -> HistoricalCostSemanticsLatch:
    return HistoricalCostSemanticsLatch.from_bytes(document)


__all__ = [
    "AUDIT_FINDING_ID",
    "AUDIT_INVENTORY_DOMAIN",
    "AUDIT_MANIFEST_SCHEMA",
    "AUTHORITY_DELTA_ZERO",
    "CAUSAL_INVALID_COMPLETION_IDS",
    "CAUSAL_INVALID_STUDY_CONTEXT_IDS",
    "DEFAULT_SCIENTIFIC_CLASS",
    "ENGINEERING_CLASS",
    "EXCEPTIONAL_STUDY_CLASSES",
    "FORBIDDEN_INTERPRETATION",
    "GOLDEN_CLASS_COMPLETION_SEALS",
    "GOLDEN_INVENTORY_SEALS",
    "HistoricalAuthorityCursor",
    "HistoricalCostInterpretation",
    "HistoricalCostQualificationState",
    "HistoricalCostSemanticCriterion",
    "HistoricalCostSemanticsError",
    "HistoricalCostSemanticsLatch",
    "HistoricalInventorySeal",
    "HistoricalSpreadSemanticClass",
    "HistoricalSpreadSemanticsAuditManifest",
    "LATCH_SCHEMA",
    "PERMITTED_INTERPRETATION",
    "PRODUCTION_UPPER_CURSOR",
    "historical_cost_semantics_latch_from_bytes",
    "historical_cost_semantics_latch_from_payload",
    "historical_inventory_digest",
    "historical_spread_semantics_audit_manifest_from_bytes",
    "historical_spread_semantics_audit_manifest_from_payload",
]
