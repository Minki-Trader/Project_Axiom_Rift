"""Atomic proof for preregistered prospective two-policy comparisons.

The protocol is deliberately mechanism-neutral but evidence-strict.  A Job
must emit the complete registered pair: trade outcomes, every evaluated
intent, eligible days, fold windows, and causal invariance observations.  The
validator recomputes all scientific metrics and concurrent-family inference
from those atomic rows.  Durable payloads never select executable code.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from hashlib import sha256
from math import ceil
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    SelectionFamilyPlan,
    SelectionHypothesis,
    infer_concurrent_selection_family,
    selection_inference_implementation_sha256,
)


PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID = "prospective_policy.concurrent_pair.v1"
PROSPECTIVE_PAIR_PROTOCOL_DEFINITION_SCHEMA = (
    "prospective_pair_protocol_definition.v1"
)
PROSPECTIVE_PAIR_MEMBER_SCHEMA = "prospective_pair_member.v1"
PROSPECTIVE_PAIR_WINDOW_SCHEMA = "prospective_pair_window.v1"
PROSPECTIVE_PAIR_TRADE_SCHEMA = "prospective_pair_trade.v1"
PROSPECTIVE_PAIR_INTENT_SCHEMA = "prospective_pair_intent.v1"
PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA = "prospective_pair_eligible_day.v1"
PROSPECTIVE_PAIR_INVARIANCE_SCHEMA = "prospective_pair_invariance.v1"

PROSPECTIVE_PAIR_EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
)
PROSPECTIVE_PAIR_CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)

_THIS_FILE = Path(__file__).resolve()
_DEFINITION_FIELDS = {
    "allowed_regimes",
    "clock_contract",
    "control_executable_id",
    "cost_contract",
    "dataset_sha256",
    "family_id",
    "folds",
    "historical_context",
    "inference",
    "invariance_keys",
    "material_identity",
    "members",
    "producer_implementation_identities",
    "prospective_executable_ids",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
}
_INFERENCE_FIELDS = {
    "alpha_ppm",
    "base_seed",
    "block_lengths",
    "bootstrap_samples",
    "monte_carlo_confidence_ppm",
}
_HISTORICAL_CONTEXT_FIELDS = {
    "adjustment_authority",
    "context_id",
    "prior_global_exposure_count",
}
_MEMBER_FIELDS = {"configuration_id", "executable_id", "ordinal", "schema"}
_WINDOW_FIELDS = {
    "eligible_dates",
    "fold_id",
    "schema",
    "test_end",
    "test_start",
}
_TRADE_FIELDS = {
    "configuration_id",
    "decision_time",
    "decision_bar_index",
    "decision_bar_open_time",
    "direction",
    "entry_bar_index",
    "entry_bid_micropoints",
    "entry_spread_cost_micropoints",
    "entry_spread_source_bar_index",
    "entry_spread_source_bar_open_time",
    "entry_time",
    "executable_id",
    "exit_time",
    "exit_bar_index",
    "exit_bid_micropoints",
    "exit_spread_cost_micropoints",
    "exit_spread_source_bar_index",
    "exit_spread_source_bar_open_time",
    "fold_id",
    "gross_pnl_micropoints",
    "native_cost_micropoints",
    "native_net_pnl_micropoints",
    "observation_id",
    "regime",
    "schema",
    "slot",
    "stress_cost_micropoints",
    "stress_net_pnl_micropoints",
}
_INTENT_FIELDS = {
    "configuration_id",
    "decision_time",
    "direction",
    "entry_time",
    "executable_id",
    "exit_time",
    "fold_id",
    "observation_id",
    "schema",
    "slot",
    "status",
}
_ELIGIBLE_FIELDS = {
    "configuration_id",
    "date",
    "executable_id",
    "fold_id",
    "schema",
}
_INVARIANCE_FIELDS = {
    "compared_row_count",
    "executable_id",
    "fold_id",
    "full_values_sha256",
    "invariance_key",
    "mismatch_count",
    "prefix_values_sha256",
    "schema",
}
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_definition",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}
_STATISTIC_FIELDS = {
    "control_inference",
    "diagnostics",
    "historical_context",
    "selection_inference",
    "subject_controls",
}
_ALLOWED_INTENT_STATUSES = frozenset(
    {
        "causality_violation",
        "entry_cancelled_unknown_cost",
        "executed",
        "gap_excluded",
        "risk_policy_skipped",
        "unknown_cost",
    }
)


def prospective_pair_trace_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(f"{prefix}:")
    if digest == text:
        raise ScientificTraceError(f"{name} must be a {prefix} identity")
    _digest(name, digest)
    return text


def _integer(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ScientificTraceError(f"{name} must be an integer")
    return value


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be an object")
    return value


def _sequence(name: str, value: object, *, allow_empty: bool = False) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        raise ScientificTraceError(f"{name} must be a sequence")
    return value


def _timestamp(name: str, value: object) -> datetime:
    text = _ascii(name, value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is not None or parsed.isoformat() != text:
        raise ScientificTraceError(f"{name} must be a canonical naive timestamp")
    return parsed


def _date(name: str, value: object) -> date:
    text = _ascii(name, value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} must be an ISO date") from exc
    if parsed.isoformat() != text:
        raise ScientificTraceError(f"{name} must be a canonical date")
    return parsed


@dataclass(frozen=True, slots=True)
class ProspectivePairMember:
    configuration_id: str
    executable_id: str
    ordinal: int

    def __post_init__(self) -> None:
        _ascii("pair member configuration_id", self.configuration_id)
        _identity("pair member executable_id", self.executable_id, "executable")
        if self.ordinal not in {1, 2}:
            raise ScientificTraceError("pair member ordinal must be 1 or 2")

    def manifest(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "executable_id": self.executable_id,
            "ordinal": self.ordinal,
            "schema": PROSPECTIVE_PAIR_MEMBER_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class ProspectivePairWindow:
    fold_id: str
    test_start: str
    test_end: str
    eligible_dates: tuple[str, ...]

    def __post_init__(self) -> None:
        _ascii("pair window fold_id", self.fold_id)
        start = _timestamp("pair window test_start", self.test_start)
        end = _timestamp("pair window test_end", self.test_end)
        if start > end:
            raise ScientificTraceError("pair window starts after it ends")
        if type(self.eligible_dates) is not tuple or not self.eligible_dates:
            raise ScientificTraceError("pair window eligible dates are absent")
        normalized = tuple(
            _date("pair window eligible date", value).isoformat()
            for value in self.eligible_dates
        )
        if normalized != tuple(sorted(set(normalized))):
            raise ScientificTraceError(
                "pair window eligible dates must be sorted and unique"
            )
        if any(not start.date() <= _date("eligible date", value) <= end.date() for value in normalized):
            raise ScientificTraceError("pair window eligible date is out of bounds")

    def manifest(self) -> dict[str, object]:
        return {
            "eligible_dates": list(self.eligible_dates),
            "fold_id": self.fold_id,
            "schema": PROSPECTIVE_PAIR_WINDOW_SCHEMA,
            "test_end": self.test_end,
            "test_start": self.test_start,
        }


@dataclass(frozen=True, slots=True)
class ProspectivePairProtocolDefinition:
    members: tuple[ProspectivePairMember, ...]
    control_executable_id: str
    folds: tuple[ProspectivePairWindow, ...]
    allowed_regimes: tuple[str, ...]
    invariance_keys: tuple[str, ...]
    dataset_sha256: str
    material_identity: str
    split_artifact_sha256: str
    clock_contract: str
    cost_contract: str
    producer_implementation_identities: tuple[tuple[str, str], ...]
    historical_context_id: str
    historical_prior_global_exposure_count: int
    alpha_ppm: int
    bootstrap_samples: int
    block_lengths: tuple[int, ...]
    monte_carlo_confidence_ppm: int
    base_seed: int
    protocol_id: str = PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID
    family_id: str = field(init=False)
    inference_family_id: str = field(init=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.members) is not tuple
            or len(self.members) != 2
            or any(not isinstance(item, ProspectivePairMember) for item in self.members)
            or tuple(item.ordinal for item in self.members) != (1, 2)
        ):
            raise ScientificTraceError("prospective pair must have ordered members 1 and 2")
        executable_ids = self.prospective_executable_ids
        if len(set(executable_ids)) != 2:
            raise ScientificTraceError("prospective pair Executable ids must be unique")
        if self.control_executable_id not in executable_ids:
            raise ScientificTraceError("prospective pair control is not a member")
        if type(self.folds) is not tuple or not self.folds:
            raise ScientificTraceError("prospective pair folds are absent")
        if any(not isinstance(item, ProspectivePairWindow) for item in self.folds):
            raise ScientificTraceError("prospective pair folds are invalid")
        fold_ids = tuple(item.fold_id for item in self.folds)
        if fold_ids != tuple(sorted(set(fold_ids))):
            raise ScientificTraceError("prospective pair folds must be sorted and unique")
        all_days = tuple(day for item in self.folds for day in item.eligible_dates)
        calendar = tuple(sorted(set(all_days)))
        if len(all_days) != len(calendar):
            raise ScientificTraceError(
                "prospective pair fold calendars must be disjoint"
            )
        if len(calendar) < 30:
            raise ScientificTraceError("prospective pair needs at least 30 eligible days")
        ordered_windows = tuple(
            (
                _timestamp("pair fold start", item.test_start),
                _timestamp("pair fold end", item.test_end),
            )
            for item in self.folds
        )
        if any(
            left[1] >= right[0]
            for left, right in zip(
                ordered_windows, ordered_windows[1:], strict=False
            )
        ):
            raise ScientificTraceError(
                "prospective pair fold windows must be chronological and disjoint"
            )
        for name, values in (
            ("allowed_regimes", self.allowed_regimes),
            ("invariance_keys", self.invariance_keys),
        ):
            if type(values) is not tuple or not values:
                raise ScientificTraceError(f"{name} must be a non-empty tuple")
            normalized = tuple(_ascii(name, value) for value in values)
            if normalized != tuple(sorted(set(normalized))):
                raise ScientificTraceError(f"{name} must be sorted and unique")
        if not {"decision_append", "feature_prefix"}.issubset(
            self.invariance_keys
        ):
            raise ScientificTraceError(
                "prospective pair requires append and prefix invariance"
            )
        _digest("pair dataset_sha256", self.dataset_sha256)
        _ascii("pair material_identity", self.material_identity)
        _digest("pair split_artifact_sha256", self.split_artifact_sha256)
        _ascii("pair clock_contract", self.clock_contract)
        _ascii("pair cost_contract", self.cost_contract)
        _ascii("pair historical_context_id", self.historical_context_id)
        _integer(
            "pair historical_prior_global_exposure_count",
            self.historical_prior_global_exposure_count,
            minimum=0,
        )
        if type(self.producer_implementation_identities) is not tuple or not self.producer_implementation_identities:
            raise ScientificTraceError("pair producer identities are absent")
        implementations: list[tuple[str, str]] = []
        for item in self.producer_implementation_identities:
            if type(item) is not tuple or len(item) != 2:
                raise ScientificTraceError("pair producer identity entry is invalid")
            implementations.append(
                (_ascii("pair producer key", item[0]), _digest("pair producer digest", item[1]))
            )
        if tuple(implementations) != tuple(sorted(set(implementations))):
            raise ScientificTraceError("pair producer identities must be sorted and unique")
        plan = SelectionFamilyPlan(
            family_id="family:pending",
            stage="discovery",
            hypotheses=tuple(
                SelectionHypothesis(
                    hypothesis_id=item.executable_id,
                    registration_id=f"prospective-member:{item.configuration_id}",
                )
                for item in sorted(self.members, key=lambda value: value.executable_id)
            ),
            alpha_ppm=self.alpha_ppm,
            bootstrap_samples=self.bootstrap_samples,
            block_lengths=self.block_lengths,
            monte_carlo_confidence_ppm=self.monte_carlo_confidence_ppm,
            base_seed=self.base_seed,
        )
        del plan
        family_digest = canonical_digest(
            domain="prospective-pair-family",
            payload={
                "control_executable_id": self.control_executable_id,
                "ordered_members": [item.manifest() for item in self.members],
                "protocol_id": self.protocol_id,
            },
        )
        object.__setattr__(self, "family_id", f"family:{family_digest}")
        inference_digest = canonical_digest(
            domain="prospective-pair-selection-family",
            payload={"family_id": self.family_id, "protocol_id": self.protocol_id},
        )
        object.__setattr__(self, "inference_family_id", f"family:{inference_digest}")
        definition_digest = canonical_digest(
            domain="prospective-pair-protocol-definition",
            payload=self.manifest(),
        )
        object.__setattr__(self, "identity", f"prospective-pair-definition:{definition_digest}")

    @property
    def prospective_executable_ids(self) -> tuple[str, ...]:
        return tuple(item.executable_id for item in self.members)

    def member_by_executable(self) -> dict[str, ProspectivePairMember]:
        return {item.executable_id: item for item in self.members}

    def manifest(self) -> dict[str, object]:
        return {
            "allowed_regimes": list(self.allowed_regimes),
            "clock_contract": self.clock_contract,
            "control_executable_id": self.control_executable_id,
            "cost_contract": self.cost_contract,
            "dataset_sha256": self.dataset_sha256,
            "family_id": self.family_id,
            "folds": [item.manifest() for item in self.folds],
            "historical_context": {
                "adjustment_authority": "context_only_never_adjustment_factor",
                "context_id": self.historical_context_id,
                "prior_global_exposure_count": self.historical_prior_global_exposure_count,
            },
            "inference": {
                "alpha_ppm": self.alpha_ppm,
                "base_seed": self.base_seed,
                "block_lengths": list(self.block_lengths),
                "bootstrap_samples": self.bootstrap_samples,
                "monte_carlo_confidence_ppm": self.monte_carlo_confidence_ppm,
            },
            "invariance_keys": list(self.invariance_keys),
            "material_identity": self.material_identity,
            "members": [item.manifest() for item in self.members],
            "producer_implementation_identities": dict(self.producer_implementation_identities),
            "prospective_executable_ids": list(self.prospective_executable_ids),
            "protocol_id": self.protocol_id,
            "schema": PROSPECTIVE_PAIR_PROTOCOL_DEFINITION_SCHEMA,
            "split_artifact_sha256": self.split_artifact_sha256,
        }


def prospective_pair_protocol_definition_from_manifest(
    value: object,
) -> ProspectivePairProtocolDefinition:
    try:
        normalized = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError("prospective pair definition is not canonical") from exc
    if (
        type(normalized) is not dict
        or set(normalized) != _DEFINITION_FIELDS
        or normalized.get("schema") != PROSPECTIVE_PAIR_PROTOCOL_DEFINITION_SCHEMA
        or normalized.get("protocol_id") != PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID
    ):
        raise ScientificTraceError("prospective pair definition schema is invalid")
    inference = _mapping("pair inference", normalized.get("inference"))
    context = _mapping("pair historical context", normalized.get("historical_context"))
    implementations = _mapping(
        "pair producer identities", normalized.get("producer_implementation_identities")
    )
    if set(inference) != _INFERENCE_FIELDS or set(context) != _HISTORICAL_CONTEXT_FIELDS:
        raise ScientificTraceError("prospective pair definition internals are invalid")
    members: list[ProspectivePairMember] = []
    for raw in _sequence("pair members", normalized.get("members")):
        item = _mapping("pair member", raw)
        if set(item) != _MEMBER_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_MEMBER_SCHEMA:
            raise ScientificTraceError("prospective pair member schema is invalid")
        members.append(
            ProspectivePairMember(
                configuration_id=_ascii("pair configuration_id", item.get("configuration_id")),
                executable_id=_identity("pair executable_id", item.get("executable_id"), "executable"),
                ordinal=_integer("pair ordinal", item.get("ordinal")),
            )
        )
    folds: list[ProspectivePairWindow] = []
    for raw in _sequence("pair folds", normalized.get("folds")):
        item = _mapping("pair fold", raw)
        if set(item) != _WINDOW_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_WINDOW_SCHEMA:
            raise ScientificTraceError("prospective pair window schema is invalid")
        folds.append(
            ProspectivePairWindow(
                fold_id=_ascii("pair fold_id", item.get("fold_id")),
                test_start=_ascii("pair test_start", item.get("test_start")),
                test_end=_ascii("pair test_end", item.get("test_end")),
                eligible_dates=tuple(_sequence("pair eligible dates", item.get("eligible_dates"))),
            )
        )
    try:
        definition = ProspectivePairProtocolDefinition(
            members=tuple(members),
            control_executable_id=_identity(
                "pair control_executable_id", normalized.get("control_executable_id"), "executable"
            ),
            folds=tuple(folds),
            allowed_regimes=tuple(_sequence("pair regimes", normalized.get("allowed_regimes"))),
            invariance_keys=tuple(_sequence("pair invariance keys", normalized.get("invariance_keys"))),
            dataset_sha256=_digest("pair dataset", normalized.get("dataset_sha256")),
            material_identity=_ascii("pair material", normalized.get("material_identity")),
            split_artifact_sha256=_digest("pair split", normalized.get("split_artifact_sha256")),
            clock_contract=_ascii("pair clock", normalized.get("clock_contract")),
            cost_contract=_ascii("pair cost", normalized.get("cost_contract")),
            producer_implementation_identities=tuple(
                sorted(
                    (_ascii("pair producer key", key), _digest("pair producer digest", digest))
                    for key, digest in implementations.items()
                )
            ),
            historical_context_id=_ascii("pair context_id", context.get("context_id")),
            historical_prior_global_exposure_count=_integer(
                "pair prior exposure", context.get("prior_global_exposure_count"), minimum=0
            ),
            alpha_ppm=_integer("pair alpha_ppm", inference.get("alpha_ppm"), minimum=1),
            bootstrap_samples=_integer("pair bootstrap_samples", inference.get("bootstrap_samples"), minimum=99),
            block_lengths=tuple(_sequence("pair block_lengths", inference.get("block_lengths"))),
            monte_carlo_confidence_ppm=_integer(
                "pair monte_carlo_confidence_ppm",
                inference.get("monte_carlo_confidence_ppm"),
                minimum=1,
            ),
            base_seed=_integer("pair base_seed", inference.get("base_seed"), minimum=0),
            protocol_id=_ascii("pair protocol_id", normalized.get("protocol_id")),
        )
    except ScientificTraceError:
        raise
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError("prospective pair definition is invalid") from exc
    if (
        definition.manifest() != normalized
        or normalized.get("family_id") != definition.family_id
        or normalized.get("prospective_executable_ids") != list(definition.prospective_executable_ids)
        or context.get("adjustment_authority") != "context_only_never_adjustment_factor"
    ):
        raise ScientificTraceError("prospective pair definition identity drifted")
    return definition


def prospective_pair_observation_id(
    *,
    executable_id: str,
    fold_id: str,
    slot: str,
    decision_time: str,
    entry_time: str,
    exit_time: str,
    direction: int,
) -> str:
    digest = canonical_digest(
        domain="prospective-pair-observation",
        payload={
            "decision_time": decision_time,
            "direction": direction,
            "entry_time": entry_time,
            "executable_id": executable_id,
            "exit_time": exit_time,
            "fold_id": fold_id,
            "slot": slot,
        },
    )
    return f"observation:{digest}"


def _validate_common_trace(
    trace: Mapping[str, Any], definition: ProspectivePairProtocolDefinition
) -> None:
    if (
        trace.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or trace.get("protocol_id") != definition.protocol_id
        or trace.get("protocol_definition") != definition.manifest()
        or trace.get("family_id") != definition.family_id
        or trace.get("ordered_family") != list(definition.prospective_executable_ids)
        or trace.get("dataset_sha256") != definition.dataset_sha256
        or trace.get("material_identity") != definition.material_identity
        or trace.get("split_artifact_sha256") != definition.split_artifact_sha256
        or trace.get("windows") != [item.manifest() for item in definition.folds]
        or trace.get("controls") != {"control_executable_id": definition.control_executable_id}
        or trace.get("attribution")
        != {
            "definition_identity": definition.identity,
            "implementation_identities": dict(definition.producer_implementation_identities),
            "selection_inference_sha256": selection_inference_implementation_sha256(),
            "trace_validator_sha256": prospective_pair_trace_implementation_sha256(),
        }
    ):
        raise ScientificTraceError("prospective pair trace binding drifted")
    _digest("pair adapter implementation", trace.get("adapter_implementation_sha256"))
    if trace.get("adapter_implementation_sha256") not in dict(
        definition.producer_implementation_identities
    ).values():
        raise ScientificTraceError("prospective pair adapter is not preregistered")
    _ascii("pair mission_id", trace.get("mission_id"))
    _identity("pair subject executable", trace.get("subject_executable_id"), "executable")
    if trace.get("subject_executable_id") not in definition.prospective_executable_ids:
        raise ScientificTraceError("prospective pair subject is not registered")
    _identity("pair job_id", trace.get("job_id"), "job")
    _digest("pair job_hash", trace.get("job_hash"))


def _observation_identity(item: Mapping[str, Any]) -> str:
    return prospective_pair_observation_id(
        executable_id=str(item["executable_id"]),
        fold_id=str(item["fold_id"]),
        slot=str(item["slot"]),
        decision_time=str(item["decision_time"]),
        entry_time=str(item["entry_time"]),
        exit_time=str(item["exit_time"]),
        direction=int(item["direction"]),
    )


def _validate_trade_rows(
    trace: Mapping[str, Any], definition: ProspectivePairProtocolDefinition
) -> tuple[dict[str, Any], ...]:
    members = definition.member_by_executable()
    folds = {item.fold_id: item for item in definition.folds}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _sequence("pair trade observations", trace.get("trade_observations"), allow_empty=True):
        item = _mapping("pair trade", raw)
        if set(item) != _TRADE_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_TRADE_SCHEMA:
            raise ScientificTraceError("prospective pair trade schema is invalid")
        executable_id = _identity("pair trade executable", item.get("executable_id"), "executable")
        member = members.get(executable_id)
        fold = folds.get(_ascii("pair trade fold", item.get("fold_id")))
        if member is None or fold is None or item.get("configuration_id") != member.configuration_id:
            raise ScientificTraceError("prospective pair trade family binding drifted")
        slot = _ascii("pair trade slot", item.get("slot"))
        decision = _timestamp("pair trade decision_time", item.get("decision_time"))
        decision_open = _timestamp(
            "pair trade decision_bar_open_time",
            item.get("decision_bar_open_time"),
        )
        entry = _timestamp("pair trade entry_time", item.get("entry_time"))
        exit_time = _timestamp("pair trade exit_time", item.get("exit_time"))
        if not (
            decision_open + timedelta(minutes=5) == decision == entry
            and entry < exit_time
        ) or not (
            _timestamp("fold start", fold.test_start)
            <= decision
            <= exit_time
            <= _timestamp("fold end", fold.test_end)
        ):
            raise ScientificTraceError("prospective pair trade clock is invalid")
        if decision.date().isoformat() not in fold.eligible_dates:
            raise ScientificTraceError(
                "prospective pair trade day is not eligible"
            )
        direction = _integer("pair trade direction", item.get("direction"))
        if direction not in {-1, 1}:
            raise ScientificTraceError("prospective pair trade direction is invalid")
        regime = _ascii("pair trade regime", item.get("regime"))
        if regime not in definition.allowed_regimes:
            raise ScientificTraceError("prospective pair trade regime is invalid")
        decision_index = _integer(
            "pair trade decision_bar_index",
            item.get("decision_bar_index"),
            minimum=0,
        )
        entry_index = _integer(
            "pair trade entry_bar_index",
            item.get("entry_bar_index"),
            minimum=1,
        )
        exit_index = _integer(
            "pair trade exit_bar_index",
            item.get("exit_bar_index"),
            minimum=2,
        )
        entry_source_index = _integer(
            "pair trade entry_spread_source_bar_index",
            item.get("entry_spread_source_bar_index"),
            minimum=0,
        )
        exit_source_index = _integer(
            "pair trade exit_spread_source_bar_index",
            item.get("exit_spread_source_bar_index"),
            minimum=1,
        )
        entry_source_time = _timestamp(
            "pair trade entry_spread_source_bar_open_time",
            item.get("entry_spread_source_bar_open_time"),
        )
        exit_source_time = _timestamp(
            "pair trade exit_spread_source_bar_open_time",
            item.get("exit_spread_source_bar_open_time"),
        )
        if (
            entry_index != decision_index + 1
            or entry_source_index != decision_index
            or exit_source_index != exit_index - 1
            or exit_index <= entry_index
            or entry_source_time != decision_open
            or entry_source_time + timedelta(minutes=5) > entry
            or exit_source_time + timedelta(minutes=5) > exit_time
        ):
            raise ScientificTraceError(
                "prospective pair completed-period source clock drifted"
            )
        entry_bid = _integer(
            "pair trade entry bid", item.get("entry_bid_micropoints")
        )
        exit_bid = _integer(
            "pair trade exit bid", item.get("exit_bid_micropoints")
        )
        entry_spread = _integer(
            "pair trade entry spread cost",
            item.get("entry_spread_cost_micropoints"),
            minimum=0,
        )
        exit_spread = _integer(
            "pair trade exit spread cost",
            item.get("exit_spread_cost_micropoints"),
            minimum=0,
        )
        gross = _integer("pair gross pnl", item.get("gross_pnl_micropoints"))
        native_cost = _integer("pair native cost", item.get("native_cost_micropoints"), minimum=0)
        stress_cost = _integer("pair stress cost", item.get("stress_cost_micropoints"), minimum=0)
        native_net = _integer("pair native net", item.get("native_net_pnl_micropoints"))
        stress_net = _integer("pair stress net", item.get("stress_net_pnl_micropoints"))
        expected_gross = direction * (exit_bid - entry_bid)
        expected_native_cost = entry_spread if direction == 1 else exit_spread
        spread_sum = entry_spread + exit_spread
        if spread_sum % 2:
            raise ScientificTraceError(
                "prospective pair stress spread cost is not exactly representable"
            )
        expected_stress_cost = expected_native_cost + spread_sum // 2
        if (
            gross != expected_gross
            or native_cost != expected_native_cost
            or stress_cost != expected_stress_cost
            or native_net != gross - native_cost
            or stress_net != gross - stress_cost
        ):
            raise ScientificTraceError("prospective pair trade cost arithmetic drifted")
        observation_id = _identity("pair trade observation_id", item.get("observation_id"), "observation")
        if observation_id != _observation_identity(item) or observation_id in seen:
            raise ScientificTraceError("prospective pair trade identity is invalid")
        seen.add(observation_id)
        rows.append(dict(item))
    expected_order = sorted(
        rows,
        key=lambda item: (
            str(item["executable_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["slot"]),
            str(item["observation_id"]),
        ),
    )
    if rows != expected_order:
        raise ScientificTraceError("prospective pair trades are not canonical")
    return tuple(rows)


def _validate_intent_rows(
    trace: Mapping[str, Any],
    definition: ProspectivePairProtocolDefinition,
    trades: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    members = definition.member_by_executable()
    folds = {item.fold_id: item for item in definition.folds}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _sequence("pair intent observations", trace.get("intent_observations"), allow_empty=True):
        item = _mapping("pair intent", raw)
        if set(item) != _INTENT_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_INTENT_SCHEMA:
            raise ScientificTraceError("prospective pair intent schema is invalid")
        executable_id = _identity("pair intent executable", item.get("executable_id"), "executable")
        member = members.get(executable_id)
        fold = folds.get(_ascii("pair intent fold", item.get("fold_id")))
        if member is None or fold is None or item.get("configuration_id") != member.configuration_id:
            raise ScientificTraceError("prospective pair intent family binding drifted")
        _ascii("pair intent slot", item.get("slot"))
        decision = _timestamp("pair intent decision_time", item.get("decision_time"))
        entry = _timestamp("pair intent entry_time", item.get("entry_time"))
        exit_time = _timestamp("pair intent exit_time", item.get("exit_time"))
        if not decision <= entry < exit_time or not (
            _timestamp("fold start", fold.test_start)
            <= decision
            <= exit_time
            <= _timestamp("fold end", fold.test_end)
        ):
            raise ScientificTraceError("prospective pair intent clock is invalid")
        if decision.date().isoformat() not in fold.eligible_dates:
            raise ScientificTraceError(
                "prospective pair intent day is not eligible"
            )
        direction = _integer("pair intent direction", item.get("direction"))
        if direction not in {-1, 1}:
            raise ScientificTraceError("prospective pair intent direction is invalid")
        status = _ascii("pair intent status", item.get("status"))
        if status not in _ALLOWED_INTENT_STATUSES:
            raise ScientificTraceError("prospective pair intent status is invalid")
        observation_id = _identity("pair intent observation_id", item.get("observation_id"), "observation")
        if observation_id != _observation_identity(item) or observation_id in seen:
            raise ScientificTraceError("prospective pair intent identity is invalid")
        seen.add(observation_id)
        rows.append(dict(item))
    expected_order = sorted(
        rows,
        key=lambda item: (
            str(item["executable_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["slot"]),
            str(item["observation_id"]),
        ),
    )
    if rows != expected_order:
        raise ScientificTraceError("prospective pair intents are not canonical")
    executed = {str(item["observation_id"]) for item in rows if item["status"] == "executed"}
    traded = {str(item["observation_id"]) for item in trades}
    if executed != traded:
        raise ScientificTraceError("prospective pair executed intents differ from trades")
    return tuple(rows)


def _validate_eligible_rows(
    trace: Mapping[str, Any], definition: ProspectivePairProtocolDefinition
) -> tuple[dict[str, Any], ...]:
    members = definition.member_by_executable()
    folds = {item.fold_id: item for item in definition.folds}
    expected = tuple(
        (member.executable_id, window.fold_id, day)
        for member in definition.members
        for window in definition.folds
        for day in window.eligible_dates
    )
    rows: list[dict[str, Any]] = []
    keys: list[tuple[str, str, str]] = []
    for raw in _sequence("pair eligible observations", trace.get("eligible_day_observations")):
        item = _mapping("pair eligible day", raw)
        if set(item) != _ELIGIBLE_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA:
            raise ScientificTraceError("prospective pair eligible-day schema is invalid")
        executable_id = _identity("pair eligible executable", item.get("executable_id"), "executable")
        member = members.get(executable_id)
        fold_id = _ascii("pair eligible fold", item.get("fold_id"))
        fold = folds.get(fold_id)
        day = _date("pair eligible date", item.get("date")).isoformat()
        if member is None or fold is None or item.get("configuration_id") != member.configuration_id or day not in fold.eligible_dates:
            raise ScientificTraceError("prospective pair eligible-day binding drifted")
        keys.append((executable_id, fold_id, day))
        rows.append(dict(item))
    if tuple(keys) != expected:
        raise ScientificTraceError("prospective pair eligible-day inventory drifted")
    return tuple(rows)


def _validate_invariance_rows(
    trace: Mapping[str, Any], definition: ProspectivePairProtocolDefinition
) -> tuple[dict[str, Any], ...]:
    expected = tuple(
        (member.executable_id, window.fold_id, key)
        for member in definition.members
        for window in definition.folds
        for key in definition.invariance_keys
    )
    keys: list[tuple[str, str, str]] = []
    rows: list[dict[str, Any]] = []
    for raw in _sequence("pair invariance observations", trace.get("invariance_comparisons")):
        item = _mapping("pair invariance", raw)
        if set(item) != _INVARIANCE_FIELDS or item.get("schema") != PROSPECTIVE_PAIR_INVARIANCE_SCHEMA:
            raise ScientificTraceError("prospective pair invariance schema is invalid")
        executable_id = _identity("pair invariance executable", item.get("executable_id"), "executable")
        fold_id = _ascii("pair invariance fold", item.get("fold_id"))
        key = _ascii("pair invariance key", item.get("invariance_key"))
        _integer("pair invariance mismatch_count", item.get("mismatch_count"), minimum=0)
        _integer(
            "pair invariance compared_row_count",
            item.get("compared_row_count"),
            minimum=1,
        )
        full_hash = _digest(
            "pair invariance full hash", item.get("full_values_sha256")
        )
        prefix_hash = _digest(
            "pair invariance prefix hash", item.get("prefix_values_sha256")
        )
        if (item.get("mismatch_count") == 0) != (full_hash == prefix_hash):
            raise ScientificTraceError(
                "prospective pair invariance hash and mismatch count differ"
            )
        keys.append((executable_id, fold_id, key))
        rows.append(dict(item))
    if tuple(keys) != expected:
        raise ScientificTraceError("prospective pair invariance inventory drifted")
    return tuple(rows)


def _validated_parts(
    trace: Mapping[str, Any], definition: ProspectivePairProtocolDefinition
) -> dict[str, object]:
    _validate_common_trace(trace, definition)
    trades = _validate_trade_rows(trace, definition)
    intents = _validate_intent_rows(trace, definition, trades)
    eligible = _validate_eligible_rows(trace, definition)
    invariance = _validate_invariance_rows(trace, definition)
    return {
        "eligible": eligible,
        "intents": intents,
        "invariance": invariance,
        "trades": trades,
    }


def prospective_pair_calculation_parameters(
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, object]:
    return {
        "alpha_ppm": definition.alpha_ppm,
        "base_seed": definition.base_seed,
        "block_lengths": list(definition.block_lengths),
        "bootstrap_samples": definition.bootstrap_samples,
        "monte_carlo_confidence_ppm": definition.monte_carlo_confidence_ppm,
        "selection_inference_sha256": selection_inference_implementation_sha256(),
        "trace_validator_sha256": prospective_pair_trace_implementation_sha256(),
    }


def _selection_plan(
    *,
    family_id: str,
    hypothesis_ids: tuple[str, ...],
    registration_prefix: str,
    definition: ProspectivePairProtocolDefinition,
) -> SelectionFamilyPlan:
    return SelectionFamilyPlan(
        family_id=family_id,
        stage="discovery",
        hypotheses=tuple(
            SelectionHypothesis(
                hypothesis_id=value,
                registration_id=f"{registration_prefix}:{value}",
            )
            for value in sorted(hypothesis_ids)
        ),
        alpha_ppm=definition.alpha_ppm,
        bootstrap_samples=definition.bootstrap_samples,
        block_lengths=definition.block_lengths,
        monte_carlo_confidence_ppm=definition.monte_carlo_confidence_ppm,
        base_seed=definition.base_seed,
    )


def prospective_pair_control_contrast_id(
    definition: ProspectivePairProtocolDefinition,
    subject_executable_id: str,
) -> str:
    if subject_executable_id not in definition.prospective_executable_ids:
        raise ScientificTraceError("prospective pair contrast subject is not registered")
    domain = (
        "prospective-pair-self-control"
        if subject_executable_id == definition.control_executable_id
        else "prospective-pair-control-contrast"
    )
    payload = {
        "family_id": definition.family_id,
        "subject_id": subject_executable_id,
    }
    if subject_executable_id != definition.control_executable_id:
        payload["control_id"] = definition.control_executable_id
    return "contrast:" + canonical_digest(domain=domain, payload=payload)


def prospective_pair_control_family_id(
    definition: ProspectivePairProtocolDefinition,
    subject_executable_id: str,
) -> str:
    if subject_executable_id not in definition.prospective_executable_ids:
        raise ScientificTraceError(
            "prospective pair control family subject is not registered"
        )
    digest = canonical_digest(
        domain="prospective-pair-control-family",
        payload={
            "control_executable_id": definition.control_executable_id,
            "family_id": definition.family_id,
            "subject_executable_id": subject_executable_id,
        },
    )
    return f"family:{digest}"


def _profit_factor(values: Sequence[int]) -> int:
    gain = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, round(1000 * gain / loss))


def _monthly_drawdown_share(trades: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    by_month: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in sorted(trades, key=lambda value: (str(value["exit_time"]), str(value["observation_id"]))):
        by_month[str(item["exit_time"])[:7]].append(item)
    worst = 0
    worst_share = 0
    for values in by_month.values():
        equity = 0
        peak = 0
        drawdown = 0
        gross_profit = 0
        for item in values:
            pnl = int(item["native_net_pnl_micropoints"])
            equity += pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            gross_profit += max(0, pnl)
        share = 0 if drawdown <= 0 else 1_000_000_000 if gross_profit <= 0 else min(1_000_000_000, ceil(1_000_000 * drawdown / gross_profit))
        worst = max(worst, drawdown)
        worst_share = max(worst_share, share)
    return worst, worst_share


def _derive_metrics_and_statistics(
    *,
    trace: Mapping[str, Any],
    definition: ProspectivePairProtocolDefinition,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, dict[str, int]], dict[str, object]]:
    if dict(parameters) != prospective_pair_calculation_parameters(definition):
        raise ScientificTraceError("prospective pair calculation parameters drifted")
    parts = _validated_parts(trace, definition)
    trades = tuple(parts["trades"])
    intents = tuple(parts["intents"])
    invariance = tuple(parts["invariance"])
    subject_id = str(trace["subject_executable_id"])
    control_id = definition.control_executable_id
    member = definition.member_by_executable()[subject_id]
    calendar = tuple(sorted({day for fold in definition.folds for day in fold.eligible_dates}))
    daily: dict[str, dict[str, int]] = {
        executable_id: {day: 0 for day in calendar}
        for executable_id in definition.prospective_executable_ids
    }
    for item in trades:
        daily[str(item["executable_id"])][str(item["decision_time"])[:10]] += int(
            item["native_net_pnl_micropoints"]
        )
    historical_context = HistoricalSearchContext(
        context_id=definition.historical_context_id,
        prior_global_exposure_count=definition.historical_prior_global_exposure_count,
    )
    selection = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=definition.inference_family_id,
            hypothesis_ids=definition.prospective_executable_ids,
            registration_prefix="prospective-member",
            definition=definition,
        ),
        daily_pnl_by_hypothesis=daily,
        historical_context=historical_context,
    )
    contrast_id = prospective_pair_control_contrast_id(definition, subject_id)
    if subject_id == control_id:
        contrast_daily = {day: 0 for day in calendar}
    else:
        contrast_daily = {
            day: daily[subject_id][day] - daily[control_id][day] for day in calendar
        }
    control = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=prospective_pair_control_family_id(
                definition, subject_id
            ),
            hypothesis_ids=(contrast_id,),
            registration_prefix="prospective-control-contrast",
            definition=definition,
        ),
        daily_pnl_by_hypothesis={contrast_id: contrast_daily},
        historical_context=historical_context,
    )
    subject_selection = selection.hypothesis(subject_id)
    subject_control = control.hypothesis(contrast_id)
    subject_trades = tuple(item for item in trades if item["executable_id"] == subject_id)
    subject_intents = tuple(item for item in intents if item["executable_id"] == subject_id)
    day_entries = {day: 0 for day in calendar}
    for item in subject_trades:
        day_entries[str(item["decision_time"])[:10]] += 1
    positive_days = sorted((value for value in daily[subject_id].values() if value > 0), reverse=True)
    gross_positive_days = sum(positive_days)
    top5_share = 0 if gross_positive_days <= 0 else min(1_000_000, round(1_000_000 * sum(positive_days[:5]) / gross_positive_days))
    sorted_entries = sorted(day_entries.values())
    count = len(sorted_entries)
    median_entries = sorted_entries[count // 2] if count % 2 else (sorted_entries[count // 2 - 1] + sorted_entries[count // 2]) / 2
    p10 = sorted_entries[int((count - 1) * 0.10)]
    p90 = sorted_entries[ceil((count - 1) * 0.90)]
    fold_values: dict[str, list[int]] = {item.fold_id: [] for item in definition.folds}
    regime_values: dict[str, list[tuple[str, int]]] = {value: [] for value in definition.allowed_regimes}
    for item in subject_trades:
        pnl = int(item["native_net_pnl_micropoints"])
        fold_values[str(item["fold_id"])].append(pnl)
        regime_values[str(item["regime"])].append((str(item["fold_id"]), pnl))
    fold_net = {key: sum(values) for key, values in fold_values.items()}
    fold_pf = sorted(_profit_factor(values) for values in fold_values.values())
    drawdown, drawdown_share = _monthly_drawdown_share(subject_trades)
    prefix_mismatch = sum(
        int(item["mismatch_count"])
        for item in invariance
        if item["executable_id"] == subject_id and item["invariance_key"] == "feature_prefix"
    )
    append_mismatch = sum(
        int(item["mismatch_count"])
        for item in invariance
        if item["executable_id"] == subject_id and item["invariance_key"] == "decision_append"
    )
    supported_regimes = 0
    positive_regimes = 0
    for values in regime_values.values():
        by_fold: dict[str, int] = defaultdict(int)
        for fold_id, pnl in values:
            by_fold[fold_id] += pnl
        net = sum(by_fold.values())
        wins = sum(value > 0 for value in by_fold.values())
        positive_regimes += int(net > 0)
        supported_regimes += int(
            net > 0
            and len(values) >= 30
            and len(by_fold) >= 5
            and wins >= 3
            and 2 * wins > len(by_fold)
        )
    control_delta = sum(contrast_daily.values())
    control_pvalue = (
        1_000_000
        if subject_id == control_id
        else subject_control.raw_monte_carlo_upper_pvalue_ppm
    )
    metrics = {
        "activity_and_concentration": {
            "entries_per_day_milli": round(1000 * len(subject_trades) / count),
            "top5_profit_day_share_ppm": top5_share,
            "trade_count": len(subject_trades),
        },
        "after_cost_fixed_lot_economics": {
            "median_fold_profit_factor_milli": fold_pf[len(fold_pf) // 2],
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": drawdown_share,
            "net_profit_micropoints": sum(int(item["native_net_pnl_micropoints"]) for item in subject_trades),
            "stress_net_profit_micropoints": sum(int(item["stress_net_pnl_micropoints"]) for item in subject_trades),
        },
        "causal_feature_and_execution_validity": {
            "append_invariance_mismatch_count": append_mismatch,
            "causality_violation_count": sum(item["status"] == "causality_violation" for item in subject_intents),
            "nonfinite_metric_count": 0,
            "prefix_invariance_mismatch_count": prefix_mismatch,
            "unknown_cost_unresolved_signal_count": sum(item["status"] == "unknown_cost" for item in subject_intents),
        },
        "registered_control_contrast": {
            "primary_control_delta_net_profit_micropoints": control_delta,
            "primary_control_pvalue_upper_ppm": control_pvalue,
        },
        "selection_aware_signal_evidence": {
            "selection_aware_pvalue_ppm": subject_selection.synchronized_max_monte_carlo_upper_pvalue_ppm,
        },
        "temporal_and_regime_stability": {
            "evaluable_folds": sum(bool(values) for values in fold_values.values()),
            "supported_positive_regime_count": supported_regimes,
            "winning_fold_count": sum(value > 0 for value in fold_net.values()),
        },
    }
    statistics = {
        "control_inference": control.manifest(),
        "diagnostics": {
            "daily_entries_max_milli": max(sorted_entries) * 1000,
            "daily_entries_median_milli": round(1000 * median_entries),
            "daily_entries_p10_milli": p10 * 1000,
            "daily_entries_p90_milli": p90 * 1000,
            "eligible_day_count": count,
            "gap_excluded_signal_count": sum(
                item["status"] == "gap_excluded" for item in subject_intents
            ),
            "monthly_realized_exit_drawdown_micropoints": drawdown,
            "positive_regime_count": positive_regimes,
            "risk_policy_skipped_count": sum(
                item["status"] == "risk_policy_skipped"
                for item in subject_intents
            ),
            "zero_entry_day_rate_ppm": round(
                1_000_000
                * sum(value == 0 for value in sorted_entries)
                / count
            ),
        },
        "historical_context": historical_context.manifest(),
        "selection_inference": selection.manifest(),
        "subject_controls": {
            "configuration_id": member.configuration_id,
            "control_executable_id": control_id,
            "control_family_id": prospective_pair_control_family_id(
                definition, subject_id
            ),
            "selection_family_id": definition.inference_family_id,
            "subject_executable_id": subject_id,
        },
    }
    canonical_bytes(metrics)
    canonical_bytes(statistics)
    return metrics, statistics


def build_prospective_pair_calculation(
    *,
    trace: Mapping[str, Any],
    trace_output_name: str,
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, object]:
    parameters = prospective_pair_calculation_parameters(definition)
    metrics, statistics = _derive_metrics_and_statistics(
        trace=trace, definition=definition, parameters=parameters
    )
    value = {
        "evidence_modes": list(PROSPECTIVE_PAIR_EVIDENCE_MODES),
        "executable_id": trace["subject_executable_id"],
        "job_hash": trace["job_hash"],
        "job_id": trace["job_id"],
        "metrics": metrics,
        "mission_id": trace["mission_id"],
        "parameters": parameters,
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {
            "output_name": _ascii("pair trace output_name", trace_output_name),
            "sha256": sha256(canonical_bytes(trace)).hexdigest(),
        },
    }
    canonical_bytes(value)
    return value


def validate_prospective_pair_trace_calculation(
    *,
    trace: Mapping[str, Any],
    calculation: Mapping[str, Any],
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, dict[str, int]]:
    if (
        not isinstance(calculation, Mapping)
        or set(calculation) != _CALCULATION_FIELDS
        or calculation.get("schema") != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
        or calculation.get("protocol_id") != definition.protocol_id
        or calculation.get("protocol_definition") != definition.manifest()
        or tuple(calculation.get("evidence_modes", ())) != PROSPECTIVE_PAIR_EVIDENCE_MODES
    ):
        raise ScientificTraceError("prospective pair calculation schema is invalid")
    if any(
        calculation.get(name) != trace.get(trace_name)
        for name, trace_name in (
            ("executable_id", "subject_executable_id"),
            ("job_hash", "job_hash"),
            ("job_id", "job_id"),
            ("mission_id", "mission_id"),
        )
    ):
        raise ScientificTraceError("prospective pair calculation belongs to another execution")
    reference = _mapping("pair calculation trace", calculation.get("trace"))
    if (
        set(reference) != {"output_name", "sha256"}
        or reference.get("sha256") != sha256(canonical_bytes(trace)).hexdigest()
    ):
        raise ScientificTraceError("prospective pair calculation trace binding is invalid")
    _ascii("pair trace output_name", reference.get("output_name"))
    parameters = _mapping("pair calculation parameters", calculation.get("parameters"))
    metrics, statistics = _derive_metrics_and_statistics(
        trace=trace, definition=definition, parameters=parameters
    )
    if calculation.get("metrics") != metrics:
        raise ScientificTraceError("prospective pair metrics drifted from atomic rows")
    opened_statistics = _mapping("pair calculation statistics", calculation.get("statistics"))
    if set(opened_statistics) != _STATISTIC_FIELDS or dict(opened_statistics) != statistics:
        raise ScientificTraceError("prospective pair inference proof drifted")
    return metrics


__all__ = [
    "PROSPECTIVE_PAIR_CLAIMS",
    "PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA",
    "PROSPECTIVE_PAIR_EVIDENCE_MODES",
    "PROSPECTIVE_PAIR_INTENT_SCHEMA",
    "PROSPECTIVE_PAIR_INVARIANCE_SCHEMA",
    "PROSPECTIVE_PAIR_MEMBER_SCHEMA",
    "PROSPECTIVE_PAIR_PROTOCOL_DEFINITION_SCHEMA",
    "PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID",
    "PROSPECTIVE_PAIR_TRADE_SCHEMA",
    "PROSPECTIVE_PAIR_WINDOW_SCHEMA",
    "ProspectivePairMember",
    "ProspectivePairProtocolDefinition",
    "ProspectivePairWindow",
    "build_prospective_pair_calculation",
    "prospective_pair_calculation_parameters",
    "prospective_pair_control_contrast_id",
    "prospective_pair_control_family_id",
    "prospective_pair_observation_id",
    "prospective_pair_protocol_definition_from_manifest",
    "prospective_pair_trace_implementation_sha256",
    "validate_prospective_pair_trace_calculation",
]
