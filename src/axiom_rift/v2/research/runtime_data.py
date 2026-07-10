"""Runtime data eligibility and delayed sizing gates for V2 harness proof.

The types are pure and synthetic-safe. They do not inspect a terminal, download
data, choose a source, or mutate the active registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping

from axiom_rift.v2.identity import sha256_payload


RUNTIME_STATUSES = frozenset({"eligible", "pending", "ineligible"})
SIZING_MODES = frozenset({"fixed_lot", "dynamic_equity"})
EARLY_FIXED_LOT_CONTEXTS = frozenset({"H", "S", "R_initial"})
LATE_SIZING_CONTEXTS = frozenset({"R_sizing", "P", "M"})
REQUIRED_RISK_ACCOUNTING = frozenset(
    {
        "path_dependent_equity",
        "starting_equity",
        "margin",
        "free_margin",
        "contract_size",
        "lot_minimum",
        "lot_maximum",
        "lot_step",
        "concurrent_exposure",
        "drawdown_state",
        "restart_recovery",
        "broker_specification",
    }
)


class RuntimeDataError(ValueError):
    """Raised when runtime access or sizing evidence is incomplete."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _require_hash(value: str, label: str) -> None:
    if not _is_sha256(value):
        raise RuntimeDataError(f"{label} must be a lowercase sha256")


@dataclass(frozen=True)
class RuntimeSourceProbe:
    source_id: str
    provider: str
    symbol: str
    timeframe: str
    terminal_sha256: str
    account_capability_sha256: str
    adapter_sha256: str
    alignment_policy_sha256: str
    historical_access: bool
    live_access: bool
    recent_closed_bars: bool
    causal_at_us100_m5_close: bool
    cold_start_history: bool
    freshness_observable: bool
    deterministic_missing_policy: bool
    python_runtime_access: bool
    ea_runtime_access: bool
    python_ea_parity_passed: bool
    live_conformance_observed: bool
    pending_reason: str | None = None

    def __post_init__(self) -> None:
        for label in ("source_id", "provider", "symbol", "timeframe"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value:
                raise RuntimeDataError(f"runtime source {label} is required")
        if re.fullmatch(r"V2SRC[0-9]{4}", self.source_id) is None:
            raise RuntimeDataError("runtime source identity is invalid")
        for label in (
            "terminal_sha256",
            "account_capability_sha256",
            "adapter_sha256",
            "alignment_policy_sha256",
        ):
            _require_hash(getattr(self, label), label)
        if self.pending_reason is not None and not self.pending_reason:
            raise RuntimeDataError("pending reason must be null or nonempty")

    @property
    def cache_key(self) -> str:
        return sha256_payload(
            {
                "schema": "axiom_rift_v2_runtime_source_cache_key_v1",
                "provider": self.provider,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "terminal_sha256": self.terminal_sha256,
                "account_capability_sha256": self.account_capability_sha256,
                "adapter_sha256": self.adapter_sha256,
                "alignment_policy_sha256": self.alignment_policy_sha256,
            }
        )

    def evaluate(self) -> "RuntimeEligibilityReceipt":
        if self.historical_access and not self.live_access:
            status = "ineligible"
            reason_codes = ("historical_only",)
        elif not self.live_conformance_observed:
            status = "pending"
            reason_codes = (self.pending_reason or "live_conformance_pending",)
        else:
            required = {
                "live_access": self.live_access,
                "recent_closed_bars": self.recent_closed_bars,
                "causal_at_us100_m5_close": self.causal_at_us100_m5_close,
                "cold_start_history": self.cold_start_history,
                "freshness_observable": self.freshness_observable,
                "deterministic_missing_policy": self.deterministic_missing_policy,
                "python_runtime_access": self.python_runtime_access,
                "ea_runtime_access": self.ea_runtime_access,
                "python_ea_parity_passed": self.python_ea_parity_passed,
            }
            failures = tuple(key for key, passed in required.items() if not passed)
            status = "eligible" if not failures else "ineligible"
            reason_codes = () if not failures else failures
        payload = {
            "schema": "axiom_rift_v2_runtime_eligibility_receipt_v1",
            "source_id": self.source_id,
            "cache_key": self.cache_key,
            "status": status,
            "reason_codes": list(reason_codes),
            "historical_access": self.historical_access,
            "live_conformance_observed": self.live_conformance_observed,
            "scientific_hypothesis_evidence": False,
        }
        return RuntimeEligibilityReceipt(
            source_id=self.source_id,
            cache_key=self.cache_key,
            status=status,
            reason_codes=reason_codes,
            historical_access=self.historical_access,
            live_conformance_observed=self.live_conformance_observed,
            receipt_sha256=sha256_payload(payload),
        )


@dataclass(frozen=True)
class RuntimeEligibilityReceipt:
    source_id: str
    cache_key: str
    status: str
    reason_codes: tuple[str, ...]
    historical_access: bool
    live_conformance_observed: bool
    receipt_sha256: str
    scientific_hypothesis_evidence: bool = False

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2SRC[0-9]{4}", self.source_id) is None:
            raise RuntimeDataError("runtime eligibility source identity is invalid")
        _require_hash(self.cache_key, "cache_key")
        _require_hash(self.receipt_sha256, "receipt_sha256")
        if self.status not in RUNTIME_STATUSES:
            raise RuntimeDataError("runtime eligibility status is invalid")
        if not all(isinstance(value, str) and value for value in self.reason_codes):
            raise RuntimeDataError("runtime eligibility reason codes are invalid")
        if self.status == "eligible" and self.reason_codes:
            raise RuntimeDataError("eligible runtime source cannot retain failure reasons")
        if self.status != "eligible" and not self.reason_codes:
            raise RuntimeDataError("noneligible runtime source requires a reason")
        if self.scientific_hypothesis_evidence:
            raise RuntimeDataError("runtime eligibility is infrastructure evidence only")


@dataclass(frozen=True)
class RuntimeDataEligibilityRegistry:
    entries: Mapping[str, RuntimeEligibilityReceipt]

    def __post_init__(self) -> None:
        normalized: dict[str, RuntimeEligibilityReceipt] = {}
        cache_keys: set[str] = set()
        for source_id, receipt in self.entries.items():
            if not isinstance(receipt, RuntimeEligibilityReceipt) or receipt.source_id != source_id:
                raise RuntimeDataError("runtime registry key differs from receipt identity")
            if receipt.cache_key in cache_keys:
                raise RuntimeDataError("runtime registry cache keys must be unique")
            cache_keys.add(receipt.cache_key)
            normalized[source_id] = receipt
        object.__setattr__(self, "entries", MappingProxyType(normalized))

    @classmethod
    def empty(cls) -> "RuntimeDataEligibilityRegistry":
        return cls({})

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def register(
        self,
        receipt: RuntimeEligibilityReceipt,
    ) -> "RuntimeDataEligibilityRegistry":
        existing = self.entries.get(receipt.source_id)
        if existing is not None:
            if existing.receipt_sha256 == receipt.receipt_sha256:
                return self
            raise RuntimeDataError(
                "runtime source identity changed; allocate a new source or recertification receipt"
            )
        updated = dict(self.entries)
        updated[receipt.source_id] = receipt
        return RuntimeDataEligibilityRegistry(updated)

    def require_eligible(self, source_ids: tuple[str, ...]) -> None:
        for source_id in tuple(dict.fromkeys(source_ids)):
            receipt = self.entries.get(source_id)
            if receipt is None:
                raise RuntimeDataError(f"runtime source has no conformance receipt: {source_id}")
            if receipt.status != "eligible":
                raise RuntimeDataError(
                    f"runtime source is not executable: {source_id}:{receipt.status}"
                )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_runtime_data_eligibility_registry_v1",
            "entries": {
                source_id: {
                    "cache_key": receipt.cache_key,
                    "status": receipt.status,
                    "reason_codes": list(receipt.reason_codes),
                    "receipt_sha256": receipt.receipt_sha256,
                }
                for source_id, receipt in sorted(self.entries.items())
            },
        }


@dataclass(frozen=True)
class SizingDescriptor:
    program_id: str
    mode: str
    exact_rule_frozen: bool

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2SZ[0-9]{4}", self.program_id) is None:
            raise RuntimeDataError("sizing program identity is invalid")
        if self.mode not in SIZING_MODES:
            raise RuntimeDataError("sizing mode is invalid")


@dataclass(frozen=True)
class PortfolioRiskDescriptor:
    program_id: str
    exact_rule_frozen: bool
    accounted_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2PR[0-9]{4}", self.program_id) is None:
            raise RuntimeDataError("portfolio-risk program identity is invalid")
        if not all(isinstance(value, str) and value for value in self.accounted_fields):
            raise RuntimeDataError("portfolio risk accounting fields are invalid")


@dataclass(frozen=True)
class SizingGateContext:
    stage_context: str
    fixed_lot_candidate_quality_passed: bool = False
    fixed_lot_economics_passed: bool = False

    def __post_init__(self) -> None:
        if self.stage_context not in EARLY_FIXED_LOT_CONTEXTS | LATE_SIZING_CONTEXTS:
            raise RuntimeDataError("sizing stage context is invalid")


def validate_sizing_gate(
    sizing: SizingDescriptor,
    portfolio_risk: PortfolioRiskDescriptor,
    context: SizingGateContext,
) -> None:
    """Enforce fixed-lot discovery and evidence-gated later growth sizing."""

    if context.stage_context in EARLY_FIXED_LOT_CONTEXTS:
        if sizing.mode != "fixed_lot":
            raise RuntimeDataError("dynamic equity sizing is forbidden before candidate quality")
        return
    if sizing.mode == "dynamic_equity":
        if not context.fixed_lot_candidate_quality_passed:
            raise RuntimeDataError("dynamic sizing requires fixed-lot candidate quality")
        if not context.fixed_lot_economics_passed:
            raise RuntimeDataError("dynamic sizing cannot rescue failed fixed-lot economics")
        missing = REQUIRED_RISK_ACCOUNTING - set(portfolio_risk.accounted_fields)
        if missing:
            raise RuntimeDataError(
                "dynamic sizing is missing risk accounting: " + ", ".join(sorted(missing))
            )
    if context.stage_context in {"P", "M"}:
        if not sizing.exact_rule_frozen or not portfolio_risk.exact_rule_frozen:
            raise RuntimeDataError("P and M require frozen sizing and portfolio-risk identities")


__all__ = [
    "EARLY_FIXED_LOT_CONTEXTS",
    "LATE_SIZING_CONTEXTS",
    "PortfolioRiskDescriptor",
    "REQUIRED_RISK_ACCOUNTING",
    "RUNTIME_STATUSES",
    "RuntimeDataEligibilityRegistry",
    "RuntimeDataError",
    "RuntimeEligibilityReceipt",
    "RuntimeSourceProbe",
    "SIZING_MODES",
    "SizingDescriptor",
    "SizingGateContext",
    "validate_sizing_gate",
]
