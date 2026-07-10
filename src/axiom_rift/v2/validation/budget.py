"""Bounded per-slice validation, repair, and recheck accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from axiom_rift.v2.validation.receipts import ValidationReceiptStore


class ValidationBudgetError(RuntimeError):
    """Raised when a slice attempts work outside its declared budget."""


class IdenticalFailedValidationError(ValidationBudgetError):
    """Raised when an unchanged failed validation key is retried."""


class ValidationDurationExceeded(ValidationBudgetError):
    """Raised after a validator reports a duration above the hard ceiling."""


@dataclass(frozen=True)
class BudgetAuthorization:
    slice_id: str
    phase: str
    validation_key: str | None
    action: str
    cache_hit: bool
    budget_spent: bool
    cached_receipt: dict[str, Any] | None
    counters: dict[str, int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v21_budget_authorization_v1",
            "slice_id": self.slice_id,
            "phase": self.phase,
            "validation_key": self.validation_key,
            "action": self.action,
            "cache_hit": self.cache_hit,
            "budget_spent": self.budget_spent,
            "cached_receipt": self.cached_receipt,
            "counters": dict(self.counters),
        }


class SliceValidationBudget:
    """One coherent slice may validate, repair, and recheck at most once each."""

    def __init__(
        self,
        slice_id: str,
        receipt_store: ValidationReceiptStore,
        *,
        validation_limit: int = 1,
        repair_limit: int = 1,
        recheck_limit: int = 1,
        hard_ceiling_seconds: float = 30.0,
        validation_used: int = 0,
        repair_used: int = 0,
        recheck_used: int = 0,
    ) -> None:
        if not slice_id:
            raise ValidationBudgetError("slice_id is required")
        limits = (validation_limit, repair_limit, recheck_limit)
        used = (validation_used, repair_used, recheck_used)
        if any(not isinstance(value, int) or value < 0 for value in (*limits, *used)):
            raise ValidationBudgetError("validation budget counters must be nonnegative integers")
        if any(observed > limit for observed, limit in zip(used, limits, strict=True)):
            raise ValidationBudgetError("used validation budget exceeds its limit")
        if not math.isfinite(hard_ceiling_seconds) or hard_ceiling_seconds <= 0:
            raise ValidationBudgetError("hard validation ceiling must be positive and finite")
        self.slice_id = slice_id
        self.receipt_store = receipt_store
        self.validation_limit = validation_limit
        self.repair_limit = repair_limit
        self.recheck_limit = recheck_limit
        self.hard_ceiling_seconds = float(hard_ceiling_seconds)
        self.validation_used = validation_used
        self.repair_used = repair_used
        self.recheck_used = recheck_used

    @property
    def counters(self) -> dict[str, int]:
        return {
            "validation_used": self.validation_used,
            "validation_remaining": self.validation_limit - self.validation_used,
            "repair_used": self.repair_used,
            "repair_remaining": self.repair_limit - self.repair_used,
            "recheck_used": self.recheck_used,
            "recheck_remaining": self.recheck_limit - self.recheck_used,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v21_slice_validation_budget_v1",
            "slice_id": self.slice_id,
            "limits": {
                "validation": self.validation_limit,
                "repair": self.repair_limit,
                "recheck": self.recheck_limit,
                "hard_ceiling_seconds": self.hard_ceiling_seconds,
            },
            "counters": self.counters,
        }

    def authorize_validation(self, validation_key: str, *, recheck: bool = False) -> BudgetAuthorization:
        if not validation_key:
            raise ValidationBudgetError("validation_key is required")
        cached = self.receipt_store.cached_success(validation_key)
        phase = "recheck" if recheck else "validation"
        if cached is not None:
            return BudgetAuthorization(
                slice_id=self.slice_id,
                phase=phase,
                validation_key=validation_key,
                action="reuse_success_receipt",
                cache_hit=True,
                budget_spent=False,
                cached_receipt=cached,
                counters=self.counters,
            )
        if self._has_failed_key(validation_key):
            raise IdenticalFailedValidationError(
                "identical failed validation key cannot be retried; change the inputs or validator identity"
            )
        if recheck:
            if self.recheck_used >= self.recheck_limit:
                raise ValidationBudgetError("slice recheck budget is exhausted")
            self.recheck_used += 1
        else:
            if self.validation_used >= self.validation_limit:
                raise ValidationBudgetError("slice validation budget is exhausted")
            self.validation_used += 1
        return BudgetAuthorization(
            slice_id=self.slice_id,
            phase=phase,
            validation_key=validation_key,
            action="execute_once",
            cache_hit=False,
            budget_spent=True,
            cached_receipt=None,
            counters=self.counters,
        )

    def authorize_repair(self) -> BudgetAuthorization:
        if self.repair_used >= self.repair_limit:
            raise ValidationBudgetError("slice repair budget is exhausted")
        self.repair_used += 1
        return BudgetAuthorization(
            slice_id=self.slice_id,
            phase="repair",
            validation_key=None,
            action="consolidated_repair_once",
            cache_hit=False,
            budget_spent=True,
            cached_receipt=None,
            counters=self.counters,
        )

    def check_duration(self, duration_seconds: float) -> None:
        """Check reported elapsed time after execution; no daemon or watchdog is started."""

        if not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise ValidationBudgetError("validation duration must be nonnegative and finite")
        if duration_seconds > self.hard_ceiling_seconds:
            raise ValidationDurationExceeded(
                f"validation duration {duration_seconds:.6f}s exceeds {self.hard_ceiling_seconds:.6f}s"
            )

    def _has_failed_key(self, validation_key: str) -> bool:
        for row in self.receipt_store.ledger.rows():
            payload = row.get("payload", {})
            if payload.get("validation_key") == validation_key and payload.get("outcome") == "fail":
                return True
        return False
