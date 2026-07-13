"""External-source eligibility and inference dependency boundaries."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping

from axiom_rift.core.canonical import CanonicalValue, canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


MT5_EPOCH_COORDINATE = "MT5_epoch_coordinate"
MT5_DOCUMENTED_TIME_STANDARD = "MetaTrader5_Python_API_documented_UTC"
MT5_DOCUMENTED_TIME_REFERENCE = (
    "https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py"
)
MT5_ABSOLUTE_TIME_AUTHORITY = "unknown_documentation_runtime_conflict"
MT5_OFFSET_POLICY = "diagnostic_only_no_shift_or_timezone_inference"
MT5_SESSION_TIME_AUTHORITY = "unknown_no_broker_timezone_or_DST_inference"


def mt5_epoch_coordinate_observation_is_valid(
    probe: Mapping[str, object],
) -> bool:
    """Recompute the raw MT5-coordinate observation without interpreting it."""

    required = {
        "absolute_time_authority",
        "broker_session_timezone_dst_authority",
        "documented_time_standard",
        "latest_rate_mt5_epoch_seconds",
        "mt5_epoch_minus_observed_utc_seconds",
        "mt5_epoch_sequence_coherent",
        "mt5_package_version",
        "observed_at_utc",
        "observed_utc_epoch_seconds",
        "offset_policy",
        "terminal_build",
        "tick_mt5_epoch_seconds",
        "time_coordinate",
    }
    if not required.issubset(probe):
        return False
    if (
        probe["time_coordinate"] != MT5_EPOCH_COORDINATE
        or probe["documented_time_standard"] != MT5_DOCUMENTED_TIME_STANDARD
        or probe["absolute_time_authority"] != MT5_ABSOLUTE_TIME_AUTHORITY
        or probe["offset_policy"] != MT5_OFFSET_POLICY
        or probe["broker_session_timezone_dst_authority"]
        != MT5_SESSION_TIME_AUTHORITY
        or type(probe["mt5_package_version"]) is not str
        or not probe["mt5_package_version"]
        or not probe["mt5_package_version"].isascii()
        or type(probe["terminal_build"]) is not int
        or probe["terminal_build"] <= 0
        or type(probe["tick_mt5_epoch_seconds"]) is not int
        or type(probe["latest_rate_mt5_epoch_seconds"]) is not int
        or type(probe["mt5_epoch_minus_observed_utc_seconds"]) is not int
        or type(probe["mt5_epoch_sequence_coherent"]) is not bool
        or type(probe["observed_at_utc"]) is not str
        or type(probe["observed_utc_epoch_seconds"]) is not int
    ):
        return False
    try:
        observed = datetime.fromisoformat(
            probe["observed_at_utc"].replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if (
        observed.tzinfo is None
        or observed.utcoffset() != timezone.utc.utcoffset(observed)
    ):
        return False
    tick_epoch = probe["tick_mt5_epoch_seconds"]
    latest_rate_epoch = probe["latest_rate_mt5_epoch_seconds"]
    observed_epoch = int(observed.timestamp())
    expected_sequence = 0 <= tick_epoch - latest_rate_epoch <= 600
    return bool(
        probe["observed_utc_epoch_seconds"] == observed_epoch
        and probe["mt5_epoch_minus_observed_utc_seconds"]
        == tick_epoch - observed_epoch
        and probe["mt5_epoch_sequence_coherent"] is expected_sequence
        and expected_sequence
    )


def build_mt5_time_coordinate_probe_manifest(
    *,
    probes: Iterable[Mapping[str, object]],
    independent_utc_observation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build canonical evidence without converting the observed MT5 coordinate."""

    manifest_fields = (
        "absolute_time_authority",
        "broker_session_timezone_dst_authority",
        "documented_time_standard",
        "facts",
        "latest_closed_bar_mt5_epoch_coordinate",
        "latest_rate_mt5_epoch_seconds",
        "mt5_epoch_minus_observed_utc_seconds",
        "mt5_epoch_sequence_coherent",
        "mt5_package_version",
        "observed_at_utc",
        "observed_utc_epoch_seconds",
        "offset_policy",
        "retrieval_latency_ms",
        "server",
        "source_contract_id",
        "symbol",
        "terminal_build",
        "tick_mt5_epoch_seconds",
        "time_coordinate",
    )
    normalized: list[dict[str, object]] = []
    symbols: set[str] = set()
    source_ids: set[str] = set()
    for probe in probes:
        if not mt5_epoch_coordinate_observation_is_valid(probe):
            raise SourceContractError("MT5 coordinate probe observation is invalid")
        if any(name not in probe for name in manifest_fields):
            raise SourceContractError("MT5 coordinate probe manifest is incomplete")
        symbol = probe["symbol"]
        server = probe["server"]
        source_id = probe["source_contract_id"]
        latency = probe["retrieval_latency_ms"]
        latest_closed = probe["latest_closed_bar_mt5_epoch_coordinate"]
        facts = probe["facts"]
        if (
            type(symbol) is not str
            or not symbol
            or not symbol.isascii()
            or type(server) is not str
            or not server
            or not server.isascii()
            or type(source_id) is not str
            or not source_id.startswith("source:")
            or not source_id.isascii()
            or type(latency) is not int
            or latency < 0
            or (
                latest_closed is not None
                and (
                    type(latest_closed) is not str
                    or not latest_closed
                    or not latest_closed.isascii()
                )
            )
            or not isinstance(facts, Mapping)
        ):
            raise SourceContractError("MT5 coordinate probe manifest field is invalid")
        if symbol in symbols or source_id in source_ids:
            raise SourceContractError("MT5 coordinate probe manifest identity is duplicated")
        symbols.add(symbol)
        source_ids.add(source_id)
        entry = {name: probe[name] for name in manifest_fields}
        canonical_bytes(entry)
        normalized.append(entry)
    if not normalized:
        raise SourceContractError("MT5 coordinate probe manifest is empty")

    utc_reference: dict[str, object] | None = None
    if independent_utc_observation is not None:
        source = independent_utc_observation.get("source")
        observed_at = independent_utc_observation.get("observed_at_utc")
        if (
            type(source) is not str
            or not source
            or not source.isascii()
            or type(observed_at) is not str
        ):
            raise SourceContractError("independent UTC observation is invalid")
        try:
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceContractError("independent UTC observation is invalid") from exc
        if (
            parsed.tzinfo is None
            or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        ):
            raise SourceContractError("independent UTC observation is not UTC")
        utc_reference = {
            "observed_at_utc": observed_at,
            "observed_utc_epoch_seconds": int(parsed.timestamp()),
            "source": source,
        }

    manifest: dict[str, object] = {
        "documented_time_reference": MT5_DOCUMENTED_TIME_REFERENCE,
        "independent_utc_observation": utc_reference,
        "independent_utc_observation_policy": (
            "asynchronous_sanity_check_no_latency_or_offset_inference"
        ),
        "probes": sorted(normalized, key=lambda item: str(item["symbol"])),
        "schema": "mt5_time_coordinate_probe_manifest.v1",
    }
    canonical_bytes(manifest)
    return manifest


class SourceContractError(ValueError):
    """Raised when a source contract or its transition is invalid."""


class SourceEligibilityError(PermissionError):
    """Raised when an ineligible source is requested for a forbidden action."""

    failure_kind = "runtime_source_ineligibility"
    alpha_failure = False


class SourceEligibilityState(str, Enum):
    CONTEXT_ONLY = "context_only"
    HISTORICAL_AUDITED = "historical_audited"
    RUNTIME_ELIGIBLE = "runtime_eligible"
    SUSPENDED = "suspended"


class SourceType(str, Enum):
    BAR = "bar"
    MACRO = "macro"
    EVENT = "event"
    OTHER = "other"


class SourceAction(str, Enum):
    QUALITATIVE_CONTEXT = "qualitative_context"
    FEASIBILITY = "feasibility"
    HISTORICAL_AUDIT = "historical_audit"
    HISTORICAL_MECHANICS = "historical_mechanics"
    RUNTIME_AVAILABILITY_PROOF = "runtime_availability_proof"
    PERFORMANCE_BATCH = "performance_batch"
    PERFORMANCE_SEARCH = "performance_batch"
    ISSUE_SOURCE_PERMIT = "issue_source_permit"
    SOURCE_PERMIT = "issue_source_permit"
    SCHEDULER_PRIORITY = "scheduler_priority"
    PRUNING = "pruning"
    SCIENTIFIC_EVIDENCE = "scientific_evidence"
    NEGATIVE_MEMORY = "negative_memory"
    CANDIDATE_BINDING = "candidate_binding"
    DIAGNOSIS = "diagnosis"
    RECERTIFICATION = "recertification"


class SourceTransitionEvidence(str, Enum):
    HISTORICAL_AUDIT = "historical_audit"
    RUNTIME_AVAILABILITY_PROOF = "runtime_availability_proof"
    DRIFT = "drift"
    SAME_SEMANTICS_RECERTIFICATION = "same_semantics_recertification"


class RuntimeObservationState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    SOURCE_MARKET_CLOSED = "source_market_closed"
    CLOSED = "source_market_closed"
    MISSING = "missing"
    LATE = "late"
    UNSYNCHRONIZED = "unsynchronized"
    MAPPING_INVALID = "mapping_invalid"
    NONFINITE = "nonfinite"


class InferenceDependencyKind(str, Enum):
    FEATURE = "feature"
    REGIME = "regime"
    SELECTOR = "selector"
    ROUTER = "router"
    RISK = "risk"
    SIZING = "sizing"
    TRADE = "trade"
    LIFECYCLE = "lifecycle"
    OTHER_POSITION_INTENT = "other_position_intent"


class SourceFailureKind(str, Enum):
    RUNTIME_SOURCE_INELIGIBILITY = "runtime_source_ineligibility"
    ALPHA_FAILURE = "alpha_failure"


_ALLOWED_ACTIONS: dict[SourceEligibilityState, frozenset[SourceAction]] = {
    SourceEligibilityState.CONTEXT_ONLY: frozenset(
        {
            SourceAction.QUALITATIVE_CONTEXT,
            SourceAction.FEASIBILITY,
            SourceAction.HISTORICAL_AUDIT,
        }
    ),
    SourceEligibilityState.HISTORICAL_AUDITED: frozenset(
        {
            SourceAction.QUALITATIVE_CONTEXT,
            SourceAction.FEASIBILITY,
            SourceAction.HISTORICAL_MECHANICS,
            SourceAction.RUNTIME_AVAILABILITY_PROOF,
            SourceAction.DIAGNOSIS,
        }
    ),
    SourceEligibilityState.RUNTIME_ELIGIBLE: frozenset(
        {
            SourceAction.QUALITATIVE_CONTEXT,
            SourceAction.HISTORICAL_MECHANICS,
            SourceAction.PERFORMANCE_BATCH,
            SourceAction.ISSUE_SOURCE_PERMIT,
            SourceAction.SCHEDULER_PRIORITY,
            SourceAction.PRUNING,
            SourceAction.SCIENTIFIC_EVIDENCE,
            SourceAction.NEGATIVE_MEMORY,
            SourceAction.CANDIDATE_BINDING,
            SourceAction.DIAGNOSIS,
        }
    ),
    SourceEligibilityState.SUSPENDED: frozenset(
        {SourceAction.DIAGNOSIS, SourceAction.RECERTIFICATION}
    ),
}


_LEGAL_TRANSITIONS: dict[
    tuple[SourceEligibilityState, SourceEligibilityState],
    SourceTransitionEvidence,
] = {
    (
        SourceEligibilityState.CONTEXT_ONLY,
        SourceEligibilityState.HISTORICAL_AUDITED,
    ): SourceTransitionEvidence.HISTORICAL_AUDIT,
    (
        SourceEligibilityState.HISTORICAL_AUDITED,
        SourceEligibilityState.RUNTIME_ELIGIBLE,
    ): SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
    (
        SourceEligibilityState.RUNTIME_ELIGIBLE,
        SourceEligibilityState.SUSPENDED,
    ): SourceTransitionEvidence.DRIFT,
    (
        SourceEligibilityState.SUSPENDED,
        SourceEligibilityState.RUNTIME_ELIGIBLE,
    ): SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
}


def require_source_state_transition(
    *,
    previous: SourceEligibilityState | None,
    target: SourceEligibilityState,
    evidence: SourceTransitionEvidence | None,
) -> None:
    """Validate a durable source-state edge, including first registration."""

    if previous is None:
        if target is not SourceEligibilityState.CONTEXT_ONLY or evidence is not None:
            raise SourceContractError(
                "a source must first register at context_only without transition evidence"
            )
        return
    expected = _LEGAL_TRANSITIONS.get((previous, target))
    if expected is None:
        raise SourceContractError(
            f"illegal source transition: {previous.value} -> {target.value}"
        )
    if evidence is not expected:
        actual = "none" if evidence is None else evidence.value
        raise SourceContractError(
            f"transition requires {expected.value}, got {actual}"
        )


def _ascii(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be str")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if not value.isascii():
        raise ValueError(f"{name} must be ASCII")
    return value


def _snapshot(value: object) -> bytes:
    return canonical_bytes(value)


def _semantic_mapping(
    name: str,
    value: object,
    *,
    required: frozenset[str],
) -> dict[str, CanonicalValue]:
    if type(value) is not dict or not value:
        raise SourceContractError(f"{name} semantics must be a non-empty mapping")
    missing = required - set(value)
    if missing:
        raise SourceContractError(
            f"{name} semantics are missing: {sorted(missing)!r}"
        )
    canonical_bytes(value)
    return value


_BAR_INSTRUMENT_FIELDS = frozenset(
    {
        "asset_type",
        "quote_basis",
        "contract_size",
        "currency",
        "digits",
        "point",
        "session",
        "timezone",
        "adjustment",
        "roll",
    }
)
_MAPPING_FIELDS = frozenset({"runtime_symbol", "mapping_rule"})
_SCHEMA_FIELDS = frozenset({"columns", "schema_revision"})
_BAR_FIELD_FIELDS = frozenset(
    {"bar_open", "bar_close", "event_time", "information_complete_at", "first_available_at"}
)
_CLOCK_FIELDS = frozenset({"decision_alignment", "timezone_conversion"})
_AVAILABILITY_FIELDS = frozenset(
    {
        "acquisition",
        "content_hash",
        "coverage",
        "gap_policy",
        "revision_or_vintage",
        "causal_ttl_seconds",
        "runtime_retrieval_method",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceContract:
    """Stable semantics used by dependent scientific executable identities."""

    display_name: str = field(compare=False)
    canonical_instrument: str = field(compare=False)
    runtime_identifier: str = field(compare=False)
    source_type: SourceType = field(compare=False)
    instrument_semantics: InitVar[object]
    mapping_semantics: InitVar[object]
    schema_semantics: InitVar[object]
    field_semantics: InitVar[object]
    clock_semantics: InitVar[object]
    availability_semantics: InitVar[object]
    _instrument_bytes: bytes = field(init=False, repr=False, compare=False)
    _mapping_bytes: bytes = field(init=False, repr=False, compare=False)
    _schema_bytes: bytes = field(init=False, repr=False, compare=False)
    _field_bytes: bytes = field(init=False, repr=False, compare=False)
    _clock_bytes: bytes = field(init=False, repr=False, compare=False)
    _availability_bytes: bytes = field(init=False, repr=False, compare=False)
    mapping_identity: str = field(init=False)
    schema_identity: str = field(init=False)
    field_identity: str = field(init=False)
    clock_identity: str = field(init=False)
    availability_identity: str = field(init=False)
    identity: str = field(init=False)

    def __post_init__(
        self,
        instrument_semantics: object,
        mapping_semantics: object,
        schema_semantics: object,
        field_semantics: object,
        clock_semantics: object,
        availability_semantics: object,
    ) -> None:
        _ascii("display_name", self.display_name)
        _ascii("canonical_instrument", self.canonical_instrument)
        _ascii("runtime_identifier", self.runtime_identifier)
        if not isinstance(self.source_type, SourceType):
            raise TypeError("source_type must be SourceType")
        if self.source_type is SourceType.BAR:
            _semantic_mapping(
                "instrument", instrument_semantics, required=_BAR_INSTRUMENT_FIELDS
            )
            _semantic_mapping("field", field_semantics, required=_BAR_FIELD_FIELDS)
        else:
            _semantic_mapping(
                "instrument",
                instrument_semantics,
                required=frozenset({"asset_type", "session", "timezone"}),
            )
            _semantic_mapping(
                "field",
                field_semantics,
                required=frozenset(
                    {"event_time", "information_complete_at", "first_available_at"}
                ),
            )
        _semantic_mapping("mapping", mapping_semantics, required=_MAPPING_FIELDS)
        _semantic_mapping("schema", schema_semantics, required=_SCHEMA_FIELDS)
        _semantic_mapping("clock", clock_semantics, required=_CLOCK_FIELDS)
        _semantic_mapping(
            "availability", availability_semantics, required=_AVAILABILITY_FIELDS
        )

        snapshots = {
            "_instrument_bytes": _snapshot(instrument_semantics),
            "_mapping_bytes": _snapshot(mapping_semantics),
            "_schema_bytes": _snapshot(schema_semantics),
            "_field_bytes": _snapshot(field_semantics),
            "_clock_bytes": _snapshot(clock_semantics),
            "_availability_bytes": _snapshot(availability_semantics),
        }
        for name, value in snapshots.items():
            object.__setattr__(self, name, value)

        identity_inputs = {
            "mapping_identity": ("source-mapping", self.mapping()),
            "schema_identity": ("source-schema", self.schema()),
            "field_identity": ("source-fields", self.fields()),
            "clock_identity": ("source-clock", self.clock()),
            "availability_identity": (
                "source-availability",
                self.availability(),
            ),
        }
        for name, (domain, payload) in identity_inputs.items():
            object.__setattr__(
                self,
                name,
                canonical_digest(domain=domain, payload=payload),
            )

        source_digest = canonical_digest(
            domain="source-contract",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(self, "identity", f"source:{source_digest}")

    @property
    def source_contract_id(self) -> str:
        return self.identity

    def instrument(self) -> CanonicalValue:
        return parse_canonical(self._instrument_bytes)

    def mapping(self) -> CanonicalValue:
        return parse_canonical(self._mapping_bytes)

    def schema(self) -> CanonicalValue:
        return parse_canonical(self._schema_bytes)

    def fields(self) -> CanonicalValue:
        return parse_canonical(self._field_bytes)

    def clock(self) -> CanonicalValue:
        return parse_canonical(self._clock_bytes)

    def availability(self) -> CanonicalValue:
        return parse_canonical(self._availability_bytes)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "availability_semantics": self.availability(),
            "canonical_instrument": self.canonical_instrument,
            "clock_semantics": self.clock(),
            "field_semantics": self.fields(),
            "instrument_semantics": self.instrument(),
            "mapping_semantics": self.mapping(),
            "runtime_identifier": self.runtime_identifier,
            "schema": "source_contract.v1",
            "schema_semantics": self.schema(),
            "source_type": self.source_type.value,
        }

    def renamed(self, display_name: str) -> SourceContract:
        return SourceContract(
            display_name=display_name,
            canonical_instrument=self.canonical_instrument,
            runtime_identifier=self.runtime_identifier,
            source_type=self.source_type,
            instrument_semantics=self.instrument(),
            mapping_semantics=self.mapping(),
            schema_semantics=self.schema(),
            field_semantics=self.fields(),
            clock_semantics=self.clock(),
            availability_semantics=self.availability(),
        )


CURRENT_RECONSTRUCTION_FACT_FIELDS = frozenset(
    {
        "acquisition_observed",
        "content_hash_verified",
        "event_time_audited",
        "coverage_audited",
        "gaps_audited",
    }
)
INDEPENDENT_POINT_IN_TIME_FACT_FIELDS = frozenset(
    {
        "information_complete_at_audited",
        "first_availability_audited",
        "revision_or_vintage_audited",
    }
)


_RECEIPT_FACT_FIELDS: dict[SourceTransitionEvidence, frozenset[str]] = {
    SourceTransitionEvidence.HISTORICAL_AUDIT: frozenset(
        CURRENT_RECONSTRUCTION_FACT_FIELDS
        | INDEPENDENT_POINT_IN_TIME_FACT_FIELDS
    ),
    SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF: frozenset(
        {
            "local_realtime_retrieval",
            "fresh",
            "synchronized",
            "complete_or_closed",
            "latency_ms",
            "historical_runtime_field_parity",
        }
    ),
    SourceTransitionEvidence.DRIFT: frozenset(
        {"changed_surface", "observed_change", "dependent_action"}
    ),
    SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION: frozenset(
        {"semantic_equivalence", "mapping_parity", "schema_field_clock_parity"}
    ),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEligibilityReceipt:
    source_contract_id: str
    evidence: SourceTransitionEvidence
    producer_completion_id: str
    observed_at_utc: str
    artifact_hashes: tuple[str, ...]
    facts: InitVar[object]
    _facts_bytes: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(self, facts: object) -> None:
        _ascii("source_contract_id", self.source_contract_id)
        if not isinstance(self.evidence, SourceTransitionEvidence):
            raise TypeError("evidence must be SourceTransitionEvidence")
        _ascii("producer_completion_id", self.producer_completion_id)
        observed = _ascii("observed_at_utc", self.observed_at_utc)
        try:
            parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceContractError("observed_at_utc must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise SourceContractError("observed_at_utc must include a timezone")
        artifacts = tuple(sorted(self.artifact_hashes))
        if not artifacts or len(set(artifacts)) != len(artifacts):
            raise SourceContractError("source receipt requires unique artifact hashes")
        for identity in artifacts:
            if (
                type(identity) is not str
                or len(identity) != 64
                or any(character not in "0123456789abcdef" for character in identity)
            ):
                raise SourceContractError("source receipt artifact hash is invalid")
        required = _RECEIPT_FACT_FIELDS[self.evidence]
        value = _semantic_mapping("receipt facts", facts, required=required)
        if self.evidence is SourceTransitionEvidence.HISTORICAL_AUDIT:
            missing_authority = sorted(
                name
                for name in INDEPENDENT_POINT_IN_TIME_FACT_FIELDS
                if value[name] is not True
            )
            if missing_authority:
                raise SourceContractError(
                    "historical source audit requires independent point-in-time "
                    f"authority for {missing_authority!r}"
                )
            if any(value[name] is not True for name in required):
                raise SourceContractError(
                    "historical source audit requires every reconstruction fact=true"
                )
        if self.evidence is SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF:
            for name in (
                "local_realtime_retrieval",
                "fresh",
                "synchronized",
                "complete_or_closed",
                "historical_runtime_field_parity",
            ):
                if value[name] is not True:
                    raise SourceContractError(f"runtime source proof requires {name}=true")
            latency = value["latency_ms"]
            if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
                raise SourceContractError("runtime source latency_ms must be non-negative")
        if self.evidence is SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION:
            if any(
                value[name] is not True
                for name in (
                    "semantic_equivalence",
                    "mapping_parity",
                    "schema_field_clock_parity",
                )
            ):
                raise SourceContractError("recertification requires exact semantic parity")
        facts_bytes = canonical_bytes(value)
        object.__setattr__(self, "artifact_hashes", artifacts)
        object.__setattr__(self, "_facts_bytes", facts_bytes)
        receipt_digest = canonical_digest(
            domain="source-eligibility-receipt",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(self, "identity", f"source-receipt:{receipt_digest}")

    def fact_values(self) -> CanonicalValue:
        return parse_canonical(self._facts_bytes)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "artifact_hashes": list(self.artifact_hashes),
            "evidence": self.evidence.value,
            "facts": self.fact_values(),
            "observed_at_utc": self.observed_at_utc,
            "producer_completion_id": self.producer_completion_id,
            "schema": "source_eligibility_receipt.v1",
            "source_contract_id": self.source_contract_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEligibility:
    contract: SourceContract
    state: SourceEligibilityState = SourceEligibilityState.CONTEXT_ONLY
    evidence_receipt_id: str | None = None
    suspension_reason: str | None = None

    @classmethod
    def register(cls, contract: SourceContract) -> SourceEligibility:
        return cls(contract=contract)

    @property
    def scientific_trial_delta(self) -> int:
        return 0

    @property
    def alpha_failure(self) -> bool:
        return False

    @property
    def failure_kind(self) -> SourceFailureKind:
        return SourceFailureKind.RUNTIME_SOURCE_INELIGIBILITY

    def allows(self, action: SourceAction) -> bool:
        return action in _ALLOWED_ACTIONS[self.state]

    def require(self, action: SourceAction) -> None:
        if not self.allows(action):
            raise SourceEligibilityError(
                f"source state {self.state.value} forbids {action.value}"
            )

    def transition(
        self,
        *,
        target: SourceEligibilityState,
        evidence: SourceTransitionEvidence,
        receipt_id: str,
        reason: str | None = None,
    ) -> SourceEligibility:
        _ascii("receipt_id", receipt_id)
        expected = _LEGAL_TRANSITIONS.get((self.state, target))
        if expected is None:
            raise SourceContractError(
                f"illegal source transition: {self.state.value} -> {target.value}"
            )
        if evidence is not expected:
            raise SourceContractError(
                f"transition requires {expected.value}, got {evidence.value}"
            )
        if target is SourceEligibilityState.SUSPENDED:
            if reason is None:
                raise SourceContractError("suspension requires a reason")
            _ascii("reason", reason)
        elif reason is not None:
            _ascii("reason", reason)

        return SourceEligibility(
            contract=self.contract,
            state=target,
            evidence_receipt_id=receipt_id,
            suspension_reason=(
                reason if target is SourceEligibilityState.SUSPENDED else None
            ),
        )

    def complete_historical_audit(self, receipt_id: str) -> SourceEligibility:
        return self.transition(
            target=SourceEligibilityState.HISTORICAL_AUDITED,
            evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            receipt_id=receipt_id,
        )

    def prove_runtime_availability(self, receipt_id: str) -> SourceEligibility:
        return self.transition(
            target=SourceEligibilityState.RUNTIME_ELIGIBLE,
            evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            receipt_id=receipt_id,
        )

    def suspend(self, *, receipt_id: str, reason: str) -> SourceEligibility:
        return self.transition(
            target=SourceEligibilityState.SUSPENDED,
            evidence=SourceTransitionEvidence.DRIFT,
            receipt_id=receipt_id,
            reason=reason,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecertificationResult:
    eligibility: SourceEligibility
    previous_source_contract_id: str
    source_contract_id: str
    identity_preserved: bool
    scientific_trial_delta: int = 0
    next_performance_experiment_counts: bool = False


def recertify_source(
    eligibility: SourceEligibility,
    *,
    proposed_contract: SourceContract,
    receipt_id: str,
) -> RecertificationResult:
    """Restore equal semantics, or register changed semantics as a new source."""

    if eligibility.state is not SourceEligibilityState.SUSPENDED:
        raise SourceContractError("recertification requires a suspended source")
    _ascii("receipt_id", receipt_id)

    previous = eligibility.contract.source_contract_id
    current = proposed_contract.source_contract_id
    if previous == current:
        restored = eligibility.transition(
            target=SourceEligibilityState.RUNTIME_ELIGIBLE,
            evidence=SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            receipt_id=receipt_id,
        )
        return RecertificationResult(
            eligibility=restored,
            previous_source_contract_id=previous,
            source_contract_id=current,
            identity_preserved=True,
        )

    # Changed semantics are not smuggled through recertification. They start a
    # new source contract at context_only and must pass both eligibility gates.
    replacement = SourceEligibility.register(proposed_contract)
    return RecertificationResult(
        eligibility=replacement,
        previous_source_contract_id=previous,
        source_contract_id=current,
        identity_preserved=False,
        next_performance_experiment_counts=True,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBinding:
    """Candidate-only runtime binding, separate from source eligibility state."""

    executable_id: str
    source_contract_id: str
    mapping_identity: str
    eligibility_receipt_id: str
    runtime_identity: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        payload = {
            "eligibility_receipt_id": _ascii(
                "eligibility_receipt_id", self.eligibility_receipt_id
            ),
            "executable_id": _ascii("executable_id", self.executable_id),
            "mapping_identity": _ascii("mapping_identity", self.mapping_identity),
            "runtime_identity": _ascii("runtime_identity", self.runtime_identity),
            "schema": "candidate_source_binding.v1",
            "source_contract_id": _ascii(
                "source_contract_id", self.source_contract_id
            ),
        }
        binding_digest = canonical_digest(
            domain="candidate-source-binding",
            payload=payload,
        )
        object.__setattr__(self, "identity", f"candidate-source:{binding_digest}")


def bind_candidate_source(
    *,
    executable_id: str,
    eligibility: SourceEligibility,
    eligibility_receipt_id: str,
    runtime_identity: str,
) -> CandidateBinding:
    eligibility.require(SourceAction.CANDIDATE_BINDING)
    if eligibility.evidence_receipt_id != eligibility_receipt_id:
        raise SourceEligibilityError("candidate binding receipt is not current")
    return CandidateBinding(
        executable_id=executable_id,
        source_contract_id=eligibility.contract.source_contract_id,
        mapping_identity=eligibility.contract.mapping_identity,
        eligibility_receipt_id=eligibility_receipt_id,
        runtime_identity=runtime_identity,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class InferenceDependency:
    dependency_id: str
    kind: InferenceDependencyKind
    source_contract_id: str

    def __post_init__(self) -> None:
        _ascii("dependency_id", self.dependency_id)
        _ascii("source_contract_id", self.source_contract_id)
        if not isinstance(self.kind, InferenceDependencyKind):
            raise TypeError("kind must be InferenceDependencyKind")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeObservation:
    dependency_id: str
    source_contract_id: str
    state: RuntimeObservationState
    information_complete_at: datetime
    first_available_at: datetime
    observed_at: datetime
    ttl_seconds: int
    mapping_identity: str
    schema_identity: str
    field_identity: str
    clock_identity: str
    finite: bool = True
    forward_filled: bool = False
    missing_to_zero: bool = False

    def __post_init__(self) -> None:
        _ascii("dependency_id", self.dependency_id)
        _ascii("source_contract_id", self.source_contract_id)
        if not isinstance(self.state, RuntimeObservationState):
            raise TypeError("state must be RuntimeObservationState")
        for name in (
            "information_complete_at",
            "first_available_at",
            "observed_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if type(self.ttl_seconds) is not int or self.ttl_seconds < 0:
            raise ValueError("ttl_seconds must be a non-negative int")
        for name in (
            "mapping_identity",
            "schema_identity",
            "field_identity",
            "clock_identity",
        ):
            _ascii(name, getattr(self, name))


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationAssessment:
    dependency_id: str
    operable: bool
    reason_codes: tuple[str, ...]
    requires_suspension: bool
    failure_kind: SourceFailureKind = (
        SourceFailureKind.RUNTIME_SOURCE_INELIGIBILITY
    )
    alpha_failure: bool = False
    scientific_trial_delta: int = 0


def assess_observation(
    *,
    dependency: InferenceDependency,
    eligibility: SourceEligibility,
    observation: RuntimeObservation,
    decision_time: datetime,
) -> ObservationAssessment:
    """Apply eligibility, causal, freshness, mapping, and field parity gates."""

    if (
        not isinstance(decision_time, datetime)
        or decision_time.tzinfo is None
        or decision_time.utcoffset() is None
    ):
        raise ValueError("decision_time must be timezone-aware")

    reasons: list[str] = []
    suspension_reasons: list[str] = []
    contract = eligibility.contract

    if eligibility.state is not SourceEligibilityState.RUNTIME_ELIGIBLE:
        reasons.append(f"eligibility:{eligibility.state.value}")
    if dependency.source_contract_id != contract.source_contract_id:
        reasons.append("dependency_contract_mismatch")
        suspension_reasons.append("dependency_contract_mismatch")
    if observation.dependency_id != dependency.dependency_id:
        reasons.append("dependency_observation_mismatch")
    if observation.source_contract_id != contract.source_contract_id:
        reasons.append("observation_contract_mismatch")
        suspension_reasons.append("observation_contract_mismatch")
    if observation.state is not RuntimeObservationState.FRESH:
        reasons.append(f"runtime_state:{observation.state.value}")
        if observation.state is RuntimeObservationState.MAPPING_INVALID:
            suspension_reasons.append("mapping_invalid")

    try:
        causal = (
            observation.information_complete_at
            <= observation.first_available_at
            <= observation.observed_at
            <= decision_time
        )
        age_seconds = (decision_time - observation.observed_at).total_seconds()
    except (TypeError, OverflowError):
        causal = False
        age_seconds = -1
    if not causal:
        reasons.append("causal_availability_invalid")
    if age_seconds < 0 or age_seconds > observation.ttl_seconds:
        reasons.append("freshness_ttl_invalid")

    parity = (
        ("mapping", observation.mapping_identity, contract.mapping_identity),
        ("schema", observation.schema_identity, contract.schema_identity),
        ("field", observation.field_identity, contract.field_identity),
        ("clock", observation.clock_identity, contract.clock_identity),
    )
    for name, actual, expected in parity:
        if actual != expected:
            code = f"{name}_parity_invalid"
            reasons.append(code)
            suspension_reasons.append(code)

    if observation.forward_filled:
        reasons.append("silent_forward_fill_forbidden")
    if observation.missing_to_zero:
        reasons.append("missing_to_zero_forbidden")
    if not observation.finite:
        reasons.append("nonfinite_value")

    return ObservationAssessment(
        dependency_id=dependency.dependency_id,
        operable=not reasons,
        reason_codes=tuple(dict.fromkeys(reasons)),
        requires_suspension=bool(suspension_reasons),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SleeveDependencySpec:
    sleeve_id: str
    dependency_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ascii("sleeve_id", self.sleeve_id)
        normalized = tuple(
            _ascii(f"dependency_ids[{index}]", value)
            for index, value in enumerate(self.dependency_ids)
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("dependency_ids must be unique")
        object.__setattr__(self, "dependency_ids", normalized)


@dataclass(frozen=True, slots=True, kw_only=True)
class SleeveRuntimeDecision:
    sleeve_id: str
    operable: bool
    failed_dependency_ids: tuple[str, ...]
    assessments: tuple[ObservationAssessment, ...]


def evaluate_sleeves(
    *,
    sleeves: Iterable[SleeveDependencySpec],
    dependencies: Mapping[str, InferenceDependency],
    eligibilities: Mapping[str, SourceEligibility],
    observations: Mapping[str, RuntimeObservation],
    decision_time: datetime,
) -> dict[str, SleeveRuntimeDecision]:
    """Fail dependent sleeves closed without stopping independent sleeves."""

    result: dict[str, SleeveRuntimeDecision] = {}
    for sleeve in sleeves:
        if sleeve.sleeve_id in result:
            raise ValueError(f"duplicate sleeve_id: {sleeve.sleeve_id}")
        assessments: list[ObservationAssessment] = []
        failed: list[str] = []
        for dependency_id in sleeve.dependency_ids:
            dependency = dependencies.get(dependency_id)
            observation = observations.get(dependency_id)
            if dependency is None or observation is None:
                assessment = ObservationAssessment(
                    dependency_id=dependency_id,
                    operable=False,
                    reason_codes=("dependency_or_observation_missing",),
                    requires_suspension=False,
                )
            else:
                eligibility = eligibilities.get(dependency.source_contract_id)
                if eligibility is None:
                    assessment = ObservationAssessment(
                        dependency_id=dependency_id,
                        operable=False,
                        reason_codes=("eligibility_missing",),
                        requires_suspension=False,
                    )
                else:
                    assessment = assess_observation(
                        dependency=dependency,
                        eligibility=eligibility,
                        observation=observation,
                        decision_time=decision_time,
                    )
            assessments.append(assessment)
            if not assessment.operable:
                failed.append(dependency_id)

        result[sleeve.sleeve_id] = SleeveRuntimeDecision(
            sleeve_id=sleeve.sleeve_id,
            operable=not failed,
            failed_dependency_ids=tuple(failed),
            assessments=tuple(assessments),
        )
    return result


CandidateSourceBinding = CandidateBinding
SleeveSpec = SleeveDependencySpec


__all__ = [
    "CandidateBinding",
    "CandidateSourceBinding",
    "CURRENT_RECONSTRUCTION_FACT_FIELDS",
    "INDEPENDENT_POINT_IN_TIME_FACT_FIELDS",
    "InferenceDependency",
    "InferenceDependencyKind",
    "MT5_ABSOLUTE_TIME_AUTHORITY",
    "MT5_DOCUMENTED_TIME_STANDARD",
    "MT5_DOCUMENTED_TIME_REFERENCE",
    "MT5_EPOCH_COORDINATE",
    "MT5_OFFSET_POLICY",
    "MT5_SESSION_TIME_AUTHORITY",
    "ObservationAssessment",
    "RecertificationResult",
    "RuntimeObservation",
    "RuntimeObservationState",
    "SleeveDependencySpec",
    "SleeveRuntimeDecision",
    "SleeveSpec",
    "SourceAction",
    "SourceContract",
    "SourceContractError",
    "SourceEligibility",
    "SourceEligibilityError",
    "SourceEligibilityReceipt",
    "SourceEligibilityState",
    "SourceFailureKind",
    "SourceTransitionEvidence",
    "SourceType",
    "assess_observation",
    "bind_candidate_source",
    "build_mt5_time_coordinate_probe_manifest",
    "evaluate_sleeves",
    "mt5_epoch_coordinate_observation_is_valid",
    "recertify_source",
    "require_source_state_transition",
]
