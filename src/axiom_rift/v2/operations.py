"""Single-writer orchestration for V2 objects, ledgers, and control state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from axiom_rift.v2.git_closeout import (
    GitCheckpointVerification,
    verify_content_checkpoint,
    verify_metadata_checkpoint,
)
from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.ledger import HashChainLedger, LedgerError
from axiom_rift.v2.lifecycle import validate_stage_basis
from axiom_rift.v2.paths import (
    V2_CONTROL_STATE,
    V2_EVIDENCE_LEDGER,
    V2_HYPOTHESIS_LEDGER,
    V2_MATERIAL_LEDGER,
    V2_OBJECT_DIR,
    V2_VALIDATION_RECEIPT_LEDGER,
)
from axiom_rift.v2.state import ControlStore
from axiom_rift.v2.state.store import (
    CONTROL_STATE_SCHEMA_V2,
    RECENT_CLOSED_GOAL_LIMIT,
    control_state_fingerprint,
)
from axiom_rift.v2.state.transitions import (
    INTERNAL_TO_ROOT_OUTCOME,
    INTERNAL_GOAL_TERMINAL_OUTCOMES,
    ROOT_TERMINAL_OUTCOMES,
    STAGE_IDENTITY_KINDS,
    TransitionError,
    claim_index,
    format_identity,
    identity_kind_for_stage,
    make_next_action,
    namespace_key,
    promote_claim,
    transition_stage,
    validate_identity,
    validate_next_action,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MaterialRecord:
    material_id: str
    kind: str
    payload: dict[str, Any]


class OperationStateError(RuntimeError):
    """Raised when durable ledgers and the compact control state disagree."""


DEFAULT_MISSION_BUDGET_LIMITS = {
    "hypothesis_batches": 12,
    "scout_jobs": 12,
    "confirmation_jobs": 4,
    "promotion_candidates": 2,
    "full_nine_fold_mt5_batches": 2,
    "holdout_reveals": 1,
}


class V2OperationWriter:
    """Own all active V2 state mutations; research functions remain pure."""

    def __init__(
        self,
        *,
        object_dir: Path = V2_OBJECT_DIR,
        control_state: Path = V2_CONTROL_STATE,
        hypothesis_ledger: Path | None = None,
        evidence_ledger: Path = V2_EVIDENCE_LEDGER,
        material_ledger: Path = V2_MATERIAL_LEDGER,
        validation_receipt_ledger: Path = V2_VALIDATION_RECEIPT_LEDGER,
        content_checkpoint_probe: Callable[[str, tuple[str, ...]], GitCheckpointVerification]
        | None = None,
        metadata_checkpoint_probe: Callable[[dict[str, Any]], GitCheckpointVerification] | None = None,
    ) -> None:
        self.objects = ObjectStore(object_dir)
        self.control = ControlStore(control_state, object_store=self.objects)
        if hypothesis_ledger is None:
            configured = None
            try:
                configured = self.control.load().get("scientific", {}).get(
                    "hypothesis_ledger_path"
                )
            except Exception:
                configured = None
            if isinstance(configured, str) and configured:
                resolved_control = control_state.resolve()
                if resolved_control.parent.name == "v2" and resolved_control.parent.parent.name == "registries":
                    hypothesis_ledger = resolved_control.parents[2] / configured
            if hypothesis_ledger is None:
                hypothesis_ledger = V2_HYPOTHESIS_LEDGER
        self.hypotheses = HashChainLedger(hypothesis_ledger, "hypothesis")
        self.evidence = HashChainLedger(evidence_ledger, "evidence")
        self.materials = HashChainLedger(material_ledger, "material")
        self.validation_receipts = HashChainLedger(
            validation_receipt_ledger, "validation_receipt"
        )
        self._content_checkpoint_probe = content_checkpoint_probe or (
            lambda commit, declared_paths: verify_content_checkpoint(
                self.control.path.parent,
                self.control.path,
                commit,
                declared_paths,
            )
        )
        self._metadata_checkpoint_probe = metadata_checkpoint_probe or (
            lambda git_sync: verify_metadata_checkpoint(self.control.path.parent, git_sync)
        )

    @property
    def ledgers(self) -> dict[str, HashChainLedger]:
        return {
            "hypothesis": self.hypotheses,
            "evidence": self.evidence,
            "material": self.materials,
            "validation_receipt": self.validation_receipts,
        }

    def reconciliation_report(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        current = state or self.control.load()
        recorded_heads = current.get("ledger_heads", {})
        reports: dict[str, dict[str, Any]] = {}
        for name, ledger in self.ledgers.items():
            rows = ledger.rows()
            observed = {
                "ledger_seq": rows[-1]["ledger_seq"] if rows else 0,
                "row_sha256": rows[-1]["row_sha256"] if rows else None,
            }
            recorded_raw = recorded_heads.get(name)
            recorded = (
                {
                    "ledger_seq": int(recorded_raw.get("ledger_seq", 0)),
                    "row_sha256": recorded_raw.get("row_sha256"),
                }
                if isinstance(recorded_raw, dict)
                else {"ledger_seq": 0, "row_sha256": None}
            )
            if observed == recorded:
                status = "in_sync"
            elif observed["ledger_seq"] > recorded["ledger_seq"]:
                status = "ledger_ahead_orphan_detected"
            elif observed["ledger_seq"] < recorded["ledger_seq"]:
                status = "control_head_ahead"
            else:
                status = "head_hash_mismatch"
            reports[name] = {"status": status, "recorded": recorded, "observed": observed}
        return {
            "ok": all(item["status"] == "in_sync" for item in reports.values()),
            "ledgers": reports,
            "pending_control_recovery": self.control.recovery_path.exists(),
        }

    def recover_pending_control(self) -> dict[str, Any]:
        """Complete a validated control replace that failed after durable ledger append."""

        candidate = self.control.load_recovery()
        if candidate is None:
            return self.control.load()
        report = self.reconciliation_report(candidate)
        if not report["ok"]:
            raise OperationStateError("pending control recovery does not match durable ledger heads")
        for object_id in candidate.get("reentry", {}).get("current_object_ids", []):
            self.objects.get(object_id)
        recovered = self.control.apply_recovery()
        if not self.reconciliation_report(recovered)["ok"]:
            raise OperationStateError("control recovery applied but ledger heads remain inconsistent")
        return recovered

    def _require_reconciled(self, state: dict[str, Any]) -> None:
        report = self.reconciliation_report(state)
        if not report["ok"]:
            problems = [
                f"{name}:{detail['status']}"
                for name, detail in report["ledgers"].items()
                if detail["status"] != "in_sync"
            ]
            raise OperationStateError("ledger/control reconciliation failed: " + ", ".join(problems))

    @staticmethod
    def _already_applied(state: dict[str, Any], idempotency_key: str) -> bool:
        return idempotency_key in state.get("applied_idempotency_keys", [])

    @staticmethod
    def _is_v2_state(state: Mapping[str, Any]) -> bool:
        return state.get("schema") == CONTROL_STATE_SCHEMA_V2

    @staticmethod
    def _new_slice_budget(slice_id: str) -> dict[str, Any]:
        return {
            "slice_id": slice_id,
            "implementation_remaining": 1,
            "validation_remaining": 1,
            "repair_remaining": 1,
            "recheck_remaining": 1,
            "identical_retry_allowed": False,
            "automatic_timeout_extension_allowed": False,
        }

    @staticmethod
    def _consume_mission_budget(draft: dict[str, Any], key: str) -> None:
        budget = draft.get("mission_budget")
        if not isinstance(budget, dict) or budget.get("frozen") is not True:
            raise OperationStateError("root mission budget must be frozen before research work")
        remaining = budget.get("remaining", {})
        if key not in remaining or not isinstance(remaining[key], int):
            raise OperationStateError(f"mission budget key is missing: {key}")
        if remaining[key] < 1:
            raise OperationStateError(f"mission budget is exhausted: {key}")
        remaining[key] -= 1

    @staticmethod
    def _require_mission_budget_available(state: dict[str, Any], key: str) -> None:
        budget = state.get("mission_budget")
        remaining = budget.get("remaining", {}) if isinstance(budget, dict) else {}
        if not isinstance(budget, dict) or budget.get("frozen") is not True or remaining.get(key, 0) < 1:
            raise OperationStateError(f"mission budget is unavailable: {key}")

    @staticmethod
    def _allocated_identity(
        state: dict[str, Any],
        kind: str,
        requested: str | None,
    ) -> tuple[str, str, int]:
        key = namespace_key(kind)
        counter = state.get("namespace", {}).get(key)
        expected = format_identity(kind, counter)
        identity = requested or expected
        validate_identity(kind, identity, counter)
        return identity, key, counter

    @staticmethod
    def _set_next_action(
        draft: dict[str, Any],
        action: dict[str, Any] | str,
    ) -> None:
        if draft.get("schema") == CONTROL_STATE_SCHEMA_V2:
            if not isinstance(action, dict):
                raise TransitionError("schema v2 requires structured next_action")
            validate_next_action(action)
            draft["cursor"]["next_action"] = action
            draft["cursor"].pop("exact_next_action", None)
        else:
            if not isinstance(action, str):
                raise TransitionError("schema v1 requires exact_next_action text")
            draft["cursor"]["exact_next_action"] = action

    @staticmethod
    def _append_or_existing(
        ledger: HashChainLedger,
        record_id: str,
        record_type: str,
        payload: dict[str, Any],
        occurred_at_utc: str,
    ) -> dict[str, Any]:
        for row in ledger.rows():
            if row["record_id"] == record_id:
                if row["content_sha256"] != sha256_payload(payload):
                    raise LedgerError(f"record id exists with different content: {record_id}")
                return row
        return ledger.append(record_id, record_type, payload, occurred_at_utc)

    @staticmethod
    def _add_authoritative_objects(state: dict[str, Any], object_ids: Iterable[str]) -> None:
        if state.get("schema") == CONTROL_STATE_SCHEMA_V2:
            reentry = state.setdefault("reentry", {})
            current = list(reentry.get("current_object_ids", []))
            for object_id in object_ids:
                if object_id not in current:
                    current.append(object_id)
            reentry["current_object_ids"] = current[-32:]
            return
        current = list(state["cursor"].get("authoritative_object_ids", []))
        for object_id in object_ids:
            if object_id not in current:
                current.append(object_id)
        state["cursor"]["authoritative_object_ids"] = current

    @staticmethod
    def _require_sorted_sha256_list(value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in value
        ):
            raise OperationStateError(f"{label} must be a sha256 list")
        if value != sorted(set(value)):
            raise OperationStateError(f"{label} must be sorted and unique")
        return value

    def _durable_family_configuration_hashes(self, family_id: str) -> list[str]:
        hashes: set[str] = set()
        for row in self.evidence.rows():
            receipt_object_id = row.get("payload", {}).get("receipt_object_id")
            if not isinstance(receipt_object_id, str):
                continue
            receipt = self.objects.get(receipt_object_id).get("payload", {})
            accounting = receipt.get("trial_accounting")
            if not isinstance(accounting, Mapping) or accounting.get("family_id") != family_id:
                continue
            values = accounting.get("configuration_hashes", [])
            if isinstance(values, list):
                hashes.update(
                    value
                    for value in values
                    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                )
        return sorted(hashes)

    def _durable_global_configuration_hashes(self) -> list[str]:
        hashes: set[str] = set()
        for row in self.evidence.rows():
            receipt_object_id = row.get("payload", {}).get("receipt_object_id")
            if not isinstance(receipt_object_id, str):
                continue
            receipt = self.objects.get(receipt_object_id).get("payload", {})
            accounting = receipt.get("trial_accounting")
            if not isinstance(accounting, Mapping):
                continue
            values = accounting.get("configuration_hashes", [])
            if isinstance(values, list):
                hashes.update(
                    value
                    for value in values
                    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                )
        return sorted(hashes)

    def _validate_nested_scout_receipt(self, receipt: Mapping[str, Any]) -> None:
        if receipt.get("schema") != "axiom_rift_v2_nested_scout_receipt_v1":
            return
        if receipt.get("stage") != "S" or receipt.get("nested_selection") is not True:
            raise OperationStateError("nested scout receipt stage or marker is invalid")
        if receipt.get("selection_source_data_role") != "validation_oos":
            raise OperationStateError("nested scout selection must use validation_oos")
        if receipt.get("development_paths_per_fold") != 1:
            raise OperationStateError("nested scout must freeze one development path per fold")
        if receipt.get("development_variant_selection") is not False:
            raise OperationStateError("nested scout receipt permits development selection")
        for field in ("selection_rule_sha256", "result_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field, ""))) is None:
                raise OperationStateError(f"nested scout receipt has invalid {field}")
        selected = receipt.get("selected_variant_hashes")
        configuration_hashes = receipt.get("selected_configuration_hashes")
        bundle_hashes = receipt.get("selected_model_bundle_sha256s")
        path_hashes = receipt.get("selected_path_hashes")
        if not isinstance(selected, Mapping) or not selected:
            raise OperationStateError("nested scout selected variant hashes are missing")
        if any(
            not isinstance(mapping, Mapping) or set(mapping) != set(selected)
            for mapping in (configuration_hashes, bundle_hashes, path_hashes)
        ):
            raise OperationStateError("nested scout selected-path hashes do not match folds")
        for mapping, label in (
            (selected, "selected variant"),
            (configuration_hashes, "selected configuration"),
            (bundle_hashes, "selected model bundle"),
            (path_hashes, "selected path"),
        ):
            if any(
                re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
                for value in mapping.values()
            ):
                raise OperationStateError(f"nested scout {label} hash is invalid")
        artifacts = receipt.get("artifacts")
        if not isinstance(artifacts, Mapping) or not {
            "metrics",
            "models",
            "trades",
            "causal_checks",
            "nested_selection",
            "trial_accounting",
        }.issubset(artifacts):
            raise OperationStateError("nested scout receipt artifacts are incomplete")
        accounting = receipt.get("trial_accounting")
        if not isinstance(accounting, Mapping):
            raise OperationStateError("nested scout trial accounting is missing")
        family_id = accounting.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            raise OperationStateError("nested scout family identity is missing")
        prior = self._durable_family_configuration_hashes(family_id)
        global_prior = self._durable_global_configuration_hashes()
        declared_prior = self._require_sorted_sha256_list(
            accounting.get("family_configuration_hashes_before"),
            "family_configuration_hashes_before",
        )
        current = self._require_sorted_sha256_list(
            accounting.get("configuration_hashes"), "configuration_hashes"
        )
        after = self._require_sorted_sha256_list(
            accounting.get("family_configuration_hashes_after"),
            "family_configuration_hashes_after",
        )
        declared_global_prior = self._require_sorted_sha256_list(
            accounting.get("global_configuration_hashes_before"),
            "global_configuration_hashes_before",
        )
        global_after = self._require_sorted_sha256_list(
            accounting.get("global_configuration_hashes_after"),
            "global_configuration_hashes_after",
        )
        expected_after = sorted(set(prior) | set(current))
        expected_global_after = sorted(set(global_prior) | set(current))
        if declared_prior != prior or after != expected_after:
            raise OperationStateError("nested scout family trial history differs from durable receipts")
        if declared_global_prior != global_prior or global_after != expected_global_after:
            raise OperationStateError("nested scout global trial history differs from durable receipts")
        integer_expectations = {
            "job_unique_configuration_count": len(current),
            "new_family_configuration_trials": len(set(current) - set(prior)),
            "family_trials_before": len(prior),
            "family_trials_cumulative": len(after),
            "global_trials_before": len(global_prior),
            "global_trials_cumulative": len(global_after),
            "development_selected_paths": len(selected),
        }
        for field, expected in integer_expectations.items():
            if accounting.get(field) != expected:
                raise OperationStateError(f"nested scout trial count does not reconcile: {field}")
        if accounting.get("development_variant_selection") is not False:
            raise OperationStateError("nested scout trial accounting permits development selection")
        if accounting.get("family_history_sha256_before") != sha256_payload(prior):
            raise OperationStateError("nested scout prior family-history hash is invalid")
        if accounting.get("family_history_sha256_after") != sha256_payload(after):
            raise OperationStateError("nested scout resulting family-history hash is invalid")
        if accounting.get("global_history_sha256_before") != sha256_payload(global_prior):
            raise OperationStateError("nested scout prior global-history hash is invalid")
        if accounting.get("global_history_sha256_after") != sha256_payload(global_after):
            raise OperationStateError("nested scout resulting global-history hash is invalid")

    def create_goal(
        self,
        *,
        goal_payload: dict[str, Any],
        idempotency_key: str,
        goal_id: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("generic goal lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        root_mission = state["root_mission"]
        if root_mission.get("terminal_outcome") is not None:
            raise OperationStateError("root mission is terminal and cannot open another internal goal")
        if state["cursor"].get("active_goal_id") is not None:
            raise OperationStateError("another internal goal is already active")
        scientific = state.get("scientific")
        scientific_open: dict[str, Any] | None = None
        if isinstance(scientific, dict) and scientific.get("status") == "not_started":
            if state.get("cursor", {}).get("next_action", {}).get("kind") != "await_new_root_goal":
                raise OperationStateError("empty scientific state is not at its root-goal boundary")
            candidate = goal_payload.get("scientific_mission")
            if not isinstance(candidate, dict):
                raise OperationStateError("future scientific goal requires mission-open policy")
            ceiling = candidate.get("emergency_hypothesis_ceiling")
            if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 24:
                raise OperationStateError("scientific emergency ceiling must be at least 24")
            if candidate.get("result_independent") is not True:
                raise OperationStateError("scientific emergency ceiling must be result-independent")
            if candidate.get("scientific_origin") != "v2_current":
                raise OperationStateError("scientific mission origin must be v2_current")
            epoch_id = candidate.get("epoch_id")
            if not isinstance(epoch_id, str) or re.fullmatch(r"V2EPOCH[0-9]{4}", epoch_id) is None:
                raise OperationStateError("scientific mission requires a V2 epoch identity")
            scientific_open = {
                "emergency_hypothesis_ceiling": ceiling,
                "epoch_id": epoch_id,
            }
        allocated, namespace_field, counter = self._allocated_identity(state, "goal", goal_id)
        action = next_action or make_next_action(
            "preregister_hypothesis",
            goal_id=allocated,
            summary=f"preregister first hypothesis for {allocated}",
        )
        validate_next_action(action)
        payload = {
            "goal_id": allocated,
            "root_mission_id": root_mission["mission_id"],
            "status": "created",
            "goal": goal_payload,
        }
        object_id = self.objects.put("internal_goal", payload)
        row = self._append_or_existing(
            self.evidence,
            f"{allocated}_CREATED",
            "internal_goal_created",
            {"goal_id": allocated, "goal_object_id": object_id, "status": "created"},
            utc_now(),
        )
        def mutate(draft: dict[str, Any]) -> None:
            if draft["root_mission"]["status"] == "ready":
                draft["root_mission"]["status"] = "active"
                draft["root_mission"]["user_goal_received"] = True
                draft["mission_budget"]["frozen"] = True
            if scientific_open is not None:
                ceiling = scientific_open["emergency_hypothesis_ceiling"]
                draft["mission_budget"]["limits"]["hypothesis_batches"] = ceiling
                draft["mission_budget"]["remaining"]["hypothesis_batches"] = ceiling
                draft["mission_budget"]["limits"]["scout_jobs"] = ceiling
                draft["mission_budget"]["remaining"]["scout_jobs"] = ceiling
                draft["scientific"].update(
                    {
                        "status": "active",
                        "root_mission_id": draft["root_mission"]["mission_id"],
                        "epoch_id": scientific_open["epoch_id"],
                    }
                )
                draft["harness"].update(
                    {"status": "operational", "real_research_started": True}
                )
            draft["namespace"][namespace_field] = counter + 1
            cursor = draft["cursor"]
            cursor.update(
                {
                    "active_goal_id": allocated,
                    "active_goal_object_id": object_id,
                    "goal_status": "created",
                    "active_hypothesis_id": None,
                    "stage": "idle",
                    "stage_id": None,
                    "stage_status": "idle",
                    "terminal_outcome": None,
                }
            )
            self._set_next_action(draft, action)
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            draft["claim"] = {
                "subject_kind": "none",
                "subject_id": None,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": None,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            reentry = draft["reentry"]
            reentry["active_job"] = None
            reentry["current_artifact_hashes"] = {allocated: object_id}
            reentry["completed_receipt_ids"] = []
            reentry["completed_evidence_ids"] = []
            draft["slice_budget"] = self._new_slice_budget(f"{allocated}_H")

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def open_goal(
        self,
        *,
        goal_id: str,
        idempotency_key: str,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("generic goal lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        validate_identity("goal", goal_id)
        cursor = state["cursor"]
        if cursor.get("active_goal_id") != goal_id or cursor.get("goal_status") != "created":
            raise OperationStateError("only the currently created goal may be opened")
        action = next_action or make_next_action(
            "preregister_hypothesis",
            goal_id=goal_id,
            summary=f"preregister a hypothesis for {goal_id}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["cursor"]["goal_status"] = "open"
            self._set_next_action(draft, action)

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def open_stage(
        self,
        *,
        new_stage: str,
        idempotency_key: str,
        stage_id: str | None = None,
        basis_evidence_id: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("generic stage lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        cursor = state["cursor"]
        goal_id = cursor.get("active_goal_id")
        if cursor.get("goal_status") != "open" or not isinstance(goal_id, str):
            raise OperationStateError("an open internal goal is required")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("cannot open a stage while an evidence job is active")
        kind = identity_kind_for_stage(new_stage)
        allocated, namespace_field, counter = self._allocated_identity(state, kind, stage_id)
        current_stage = str(cursor.get("stage"))
        budget_key = {
            "S": "scout_jobs",
            "R": "confirmation_jobs",
            "P": "promotion_candidates",
        }.get(new_stage)
        if budget_key is not None:
            self._require_mission_budget_available(state, budget_key)
        receipt_object_id: str | None = None
        if current_stage == "H" and new_stage == "S":
            if cursor.get("stage_status") != "preregistered":
                raise OperationStateError("H -> S requires preregistered hypothesis state")
        else:
            if not basis_evidence_id:
                raise OperationStateError(f"{current_stage} -> {new_stage} requires basis evidence")
            evidence_row = next(
                (row for row in self.evidence.rows() if row["record_id"] == basis_evidence_id),
                None,
            )
            if evidence_row is None:
                raise OperationStateError(f"basis evidence does not exist: {basis_evidence_id}")
            receipt_object_id = evidence_row["payload"].get("receipt_object_id")
            if not isinstance(receipt_object_id, str):
                raise OperationStateError("basis evidence has no receipt object")
            receipt = self.objects.get(receipt_object_id)["payload"]
            validate_stage_basis(
                current_stage=current_stage,
                new_stage=new_stage,
                new_stage_id=allocated,
                current_claim=str(state["claim"]["current_level"]),
                basis=receipt,
            )
        action = next_action or make_next_action(
            "declare_job",
            goal_id=goal_id,
            stage=new_stage,
            subject_id=allocated,
            job_kind=f"{new_stage.lower()}_evidence",
            prerequisite_receipt_ids=[basis_evidence_id] if basis_evidence_id else [],
            summary=f"declare evidence job for {allocated}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            if budget_key is not None:
                self._consume_mission_budget(draft, budget_key)
            draft["namespace"][namespace_field] = counter + 1
            draft["cursor"] = transition_stage(draft["cursor"], new_stage, allocated)
            self._set_next_action(draft, action)
            draft["reentry"]["active_job"] = None
            draft["slice_budget"] = self._new_slice_budget(allocated)

        referenced = [receipt_object_id] if receipt_object_id is not None else []
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=referenced,
        )

    def declare_active_job(
        self,
        *,
        job_id: str,
        kind: str,
        spec_object_id: str,
        input_hash: str,
        timeout_seconds: int,
        output_path: str,
        command: str,
        expected_artifacts: list[str],
        log_path: str,
        resume_action: str,
        idempotency_key: str,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("structured active_job requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        cursor = state["cursor"]
        goal_id = cursor.get("active_goal_id")
        stage = str(cursor.get("stage"))
        stage_id = cursor.get("stage_id")
        if not isinstance(goal_id, str) or stage not in STAGE_IDENTITY_KINDS or not isinstance(stage_id, str):
            raise OperationStateError("active goal and evidence stage are required")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("an evidence job is already active")
        self.objects.get(spec_object_id)
        if kind == "full_nine_fold_mt5":
            self._require_mission_budget_available(state, "full_nine_fold_mt5_batches")
        job = {
            "job_id": job_id,
            "goal_id": goal_id,
            "stage_id": stage_id,
            "kind": kind,
            "command": command,
            "status": "declared",
            "spec_object_id": spec_object_id,
            "input_hash": input_hash,
            "timeout_seconds": timeout_seconds,
            "output_path": output_path,
            "expected_artifacts": list(expected_artifacts),
            "log_path": log_path,
            "declared_at_utc": utc_now(),
            "started_at_utc": None,
            "resume_action": resume_action,
        }
        action = next_action or make_next_action(
            "run_job",
            goal_id=goal_id,
            stage=stage,
            subject_id=stage_id,
            job_kind=kind,
            summary=f"run declared job {job_id}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            if kind == "full_nine_fold_mt5":
                self._consume_mission_budget(draft, "full_nine_fold_mt5_batches")
            draft["reentry"]["active_job"] = job
            self._set_next_action(draft, action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[spec_object_id],
        )

    def start_active_job(
        self,
        *,
        job_id: str,
        idempotency_key: str,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("structured active_job requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        job = state["reentry"].get("active_job")
        if not isinstance(job, dict) or job.get("job_id") != job_id or job.get("status") != "declared":
            raise OperationStateError("only the declared active job may start")
        action = next_action or make_next_action(
            "record_evidence",
            goal_id=job["goal_id"],
            stage=str(state["cursor"]["stage"]),
            subject_id=job["stage_id"],
            prerequisite_receipt_ids=[],
            summary=f"record evidence for {job_id}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft_job = draft["reentry"]["active_job"]
            draft_job["status"] = "running"
            draft_job["started_at_utc"] = utc_now()
            self._set_next_action(draft, action)

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def consume_slice_budget(
        self,
        *,
        phase: str,
        idempotency_key: str,
        validation_key: str | None = None,
        expected_slice_id: str | None = None,
    ) -> dict[str, Any]:
        """Authorize one implementation, validation, repair, or recheck batch."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("slice budget enforcement requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        budget = state.get("slice_budget")
        if not isinstance(budget, dict):
            raise OperationStateError("no active slice budget exists")
        if expected_slice_id is not None and budget.get("slice_id") != expected_slice_id:
            raise OperationStateError("slice budget identity mismatch")
        key_by_phase = {
            "implementation": "implementation_remaining",
            "validation": "validation_remaining",
            "repair": "repair_remaining",
            "recheck": "recheck_remaining",
        }
        counter_key = key_by_phase.get(phase)
        if counter_key is None:
            raise OperationStateError(f"unknown slice budget phase: {phase}")
        if phase in {"validation", "recheck"}:
            if not isinstance(validation_key, str) or not validation_key:
                raise OperationStateError(f"{phase} requires a validation key")
            matching = [
                row
                for row in self.validation_receipts.rows()
                if row.get("payload", {}).get("validation_key") == validation_key
            ]
            if any(row["payload"].get("outcome") == "pass" for row in matching):
                return state
            if any(row["payload"].get("outcome") == "fail" for row in matching):
                raise OperationStateError(
                    "identical failed validation cannot be retried; change inputs or validator identity"
                )
        if budget.get(counter_key) != 1:
            raise OperationStateError(f"slice budget is exhausted: {phase}")

        def mutate(draft: dict[str, Any]) -> None:
            draft["slice_budget"][counter_key] = 0

        terminal_policy = (
            "validation_mutation"
            if state.get("root_mission", {}).get("status") == "terminal_validation_pending"
            else None
        )
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            terminal_validation_policy=terminal_policy,
        )

    def open_slice(self, *, slice_id: str, idempotency_key: str) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("slice lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        if state.get("slice_budget") is not None:
            raise OperationStateError("another coherent slice is already active")

        def mutate(draft: dict[str, Any]) -> None:
            draft["slice_budget"] = self._new_slice_budget(slice_id)

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def complete_reinforcement_ready(
        self,
        *,
        baseline_commit: str,
        mission_contract_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Close an engineering reinforcement at an empty scientific boundary."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("reinforcement close requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        if re.fullmatch(r"[0-9a-f]{40}", baseline_commit) is None:
            raise OperationStateError("reinforcement baseline commit is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", mission_contract_sha256) is None:
            raise OperationStateError("mission contract hash is invalid")
        if state.get("root_mission", {}).get("status") != "ready":
            raise OperationStateError("reinforcement close requires an unopened ready root")
        if state.get("cursor", {}).get("active_goal_id") is not None:
            raise OperationStateError("reinforcement close requires no active scientific goal")
        if state.get("reentry", {}).get("active_job") is not None:
            raise OperationStateError("reinforcement close requires no active job")
        if state.get("holdout", {}).get("reveal_count") != 0:
            raise OperationStateError("reinforcement close requires zero holdout reveals")
        payload = {
            "schema": "axiom_rift_v2_reinforcement_ready_receipt_v1",
            "baseline_commit": baseline_commit,
            "harness_status": "ready",
            "scientific_root": None,
            "scientific_epoch": "not_started",
            "scientific_ledger_deltas": {
                "hypothesis": 0,
                "trial": 0,
                "negative_memory": 0,
                "ingredient": 0,
                "candidate": 0,
            },
            "holdout_reveals_before": 0,
            "holdout_reveals_after": 0,
            "real_research_started": False,
            "next_action": "await_new_root_goal",
            "claim_ceiling": "none",
        }
        object_id = self.objects.put("reinforcement_ready_receipt", payload)
        row = self._append_or_existing(
            self.evidence,
            "V2_REINFORCEMENT_READY",
            "reinforcement_ready",
            {"receipt_object_id": object_id, **payload},
            utc_now(),
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["harness"] = {
                "status": "ready",
                "real_research_started": False,
                "ready_receipt_object_id": object_id,
                "baseline_commit": baseline_commit,
            }
            draft["scientific"] = {
                "status": "not_started",
                "root_mission_id": None,
                "epoch_id": None,
                "index_path": "registries/v2/scientific/index.yaml",
                "research_map_path": "registries/v2/scientific/research_map.yaml",
                "hypothesis_ledger_path": "registries/v2/scientific/hypothesis_ledger.jsonl",
                "hypothesis_object_ids": [],
                "trial_receipt_ids": [],
                "negative_memory_object_ids": [],
                "ingredient_object_ids": [],
                "candidate_object_ids": [],
                "selected_bundle_id": None,
                "holdout_reveals": 0,
            }
            draft["root_mission"].update(
                {
                    "contract_sha256": mission_contract_sha256,
                    "status": "ready",
                    "terminal_outcome": None,
                    "user_goal_received": False,
                }
            )
            draft["cursor"].update(
                {
                    "active_goal_id": None,
                    "active_goal_object_id": None,
                    "goal_status": "closed",
                    "active_hypothesis_id": None,
                    "stage": "idle",
                    "stage_id": None,
                    "stage_status": "idle",
                    "terminal_outcome": None,
                }
            )
            self._set_next_action(
                draft,
                make_next_action(
                    "await_new_root_goal",
                    summary="await a separate autonomous research root goal",
                ),
            )
            draft["mission_budget"]["frozen"] = False
            draft["slice_budget"] = draft.get("slice_budget")
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": 0,
                "row_sha256": None,
            }
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            draft["claim"] = {
                "subject_kind": "none",
                "subject_id": None,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": None,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            self._add_authoritative_objects(draft, [object_id])
            draft["reentry"]["active_job"] = None
            draft["reentry"]["current_artifact_hashes"]["V2_HARNESS_READY"] = object_id

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def refresh_ready_mission_contract(
        self,
        *,
        expected_previous_sha256: str,
        new_contract_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Repin a ready, unopened root mission after a governance-only change."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("mission contract refresh requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        for value in (expected_previous_sha256, new_contract_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise OperationStateError("mission contract hashes must be lowercase sha256")
        mission = state.get("root_mission", {})
        if mission.get("status") != "ready" or mission.get("user_goal_received") is not False:
            raise OperationStateError("an active or terminal root mission contract cannot be repinned")
        if mission.get("contract_sha256") != expected_previous_sha256:
            raise OperationStateError("mission contract previous hash does not match control state")
        if state.get("reentry", {}).get("active_job") is not None:
            raise OperationStateError("mission contract refresh requires no active evidence job")
        if state.get("cursor", {}).get("active_goal_id") is not None:
            raise OperationStateError("mission contract refresh requires no open internal goal")

        def mutate(draft: dict[str, Any]) -> None:
            draft["root_mission"]["contract_sha256"] = new_contract_sha256

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def close_slice(
        self,
        *,
        slice_id: str,
        validation_receipt_id: str,
        declared_content_paths: Iterable[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("slice lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        budget = state.get("slice_budget")
        if not isinstance(budget, dict) or budget.get("slice_id") != slice_id:
            raise OperationStateError("slice closeout identity mismatch")
        if budget.get("validation_remaining") != 0:
            raise OperationStateError("slice closeout requires consumed validation budget")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("slice closeout requires no active job")
        row = next(
            (
                item
                for item in self.validation_receipts.rows()
                if item["record_id"] == validation_receipt_id
            ),
            None,
        )
        if row is None or row["payload"].get("outcome") != "pass":
            raise OperationStateError("slice closeout requires a passing validation receipt")
        receipt_object_id = row["payload"].get("receipt_object_id")
        if not isinstance(receipt_object_id, str):
            raise OperationStateError("slice closeout validation receipt object is missing")
        receipt = self.objects.get(receipt_object_id)["payload"]
        if receipt.get("slice_id") != slice_id:
            raise OperationStateError("validation receipt belongs to another slice")
        declared = tuple(dict.fromkeys(path.replace("\\", "/") for path in declared_content_paths))
        if not declared or any(
            not path
            or path.endswith("/")
            or path.startswith("/")
            or ":" in path.split("/", 1)[0]
            or ".." in path.split("/")
            for path in declared
        ):
            raise OperationStateError("slice closeout declared content paths are invalid")

        def mutate(draft: dict[str, Any]) -> None:
            draft["slice_budget"] = None
            draft["reentry"]["git_sync"] = {
                "status": "unsynced",
                "validation_receipt_id": validation_receipt_id,
                "validation_key": row["payload"]["validation_key"],
                "validated_slice_id": slice_id,
                "declared_content_paths": list(declared),
            }
            if draft.get("root_mission", {}).get("status") == "terminal_validation_pending":
                self._set_next_action(
                    draft,
                    make_next_action(
                        "verify_git_closeout",
                        summary="commit and push validated root closeout content",
                    ),
                )

        terminal_policy = (
            "validated_content"
            if state.get("root_mission", {}).get("status") == "terminal_validation_pending"
            else None
        )
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[receipt_object_id],
            git_sync_policy="validated_content",
            terminal_validation_policy=terminal_policy,
        )

    def redesign_slice_after_failed_recheck(
        self,
        *,
        current_slice_id: str,
        new_slice_id: str,
        failed_validation_receipt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Open one boundary-redesign slice after the original repair path is exhausted."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("slice redesign requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        budget = state.get("slice_budget")
        if not isinstance(budget, dict) or budget.get("slice_id") != current_slice_id:
            raise OperationStateError("slice redesign identity mismatch")
        if any(
            budget.get(field) != 0
            for field in ("implementation_remaining", "validation_remaining", "repair_remaining", "recheck_remaining")
        ):
            raise OperationStateError("slice redesign requires exhausted implementation and check budgets")
        if not isinstance(new_slice_id, str) or not new_slice_id or new_slice_id == current_slice_id:
            raise OperationStateError("slice redesign requires a distinct new slice id")
        row = next(
            (
                item
                for item in self.validation_receipts.rows()
                if item["record_id"] == failed_validation_receipt_id
            ),
            None,
        )
        if row is None or row["payload"].get("outcome") != "fail":
            raise OperationStateError("slice redesign requires the failed recheck receipt")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("slice redesign requires no active job")

        def mutate(draft: dict[str, Any]) -> None:
            replacement = self._new_slice_budget(new_slice_id)
            replacement["implementation_remaining"] = 0
            replacement["redesign_from_slice_id"] = current_slice_id
            replacement["failed_validation_receipt_id"] = failed_validation_receipt_id
            draft["slice_budget"] = replacement

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def record_git_closeout(
        self,
        *,
        closeout_id: str,
        validated_content_commit: str,
        local_head_observed: str,
        origin_main_head_observed: str,
        validation_receipt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Record a verified content commit without self-referencing its metadata commit."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("Git closeout recording requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        for value in (validated_content_commit, local_head_observed, origin_main_head_observed):
            if re.fullmatch(r"[0-9a-f]{40}", value) is None:
                raise OperationStateError("Git closeout commits must be lowercase 40-character hashes")
        if not (
            validated_content_commit == local_head_observed == origin_main_head_observed
        ):
            raise OperationStateError("validated content commit was not the synchronized remote head")
        current_sync = state.get("reentry", {}).get("git_sync")
        if not isinstance(current_sync, dict) or current_sync.get("status") != "unsynced":
            raise OperationStateError("Git closeout requires an unsynced content state")
        dirty_fingerprint = current_sync.get("dirty_state_fingerprint")
        if dirty_fingerprint != control_state_fingerprint(state):
            raise OperationStateError("Git closeout state fingerprint differs")
        if current_sync.get("validation_receipt_id") != validation_receipt_id:
            raise OperationStateError("Git closeout receipt differs from validated content binding")
        declared_raw = current_sync.get("declared_content_paths")
        if not isinstance(declared_raw, list) or not declared_raw:
            raise OperationStateError("Git closeout declared content scope is missing")
        declared_content_paths = tuple(declared_raw)
        checkpoint = self._content_checkpoint_probe(
            validated_content_commit,
            declared_content_paths,
        )
        if not checkpoint.ok:
            raise OperationStateError(f"Git content checkpoint failed: {checkpoint.code}")
        if checkpoint.head != local_head_observed or checkpoint.remote_head != origin_main_head_observed:
            raise OperationStateError("observed Git heads differ from the verified content checkpoint")
        validation_row = next(
            (
                row
                for row in self.validation_receipts.rows()
                if row["record_id"] == validation_receipt_id
            ),
            None,
        )
        if validation_row is None or validation_row["payload"].get("outcome") != "pass":
            raise OperationStateError("Git closeout requires a passing validation receipt")
        validation_rows = self.validation_receipts.rows()
        if not validation_rows or validation_rows[-1]["record_id"] != validation_receipt_id:
            raise OperationStateError("Git closeout requires the latest validation receipt")
        if validation_row["payload"].get("validation_key") != current_sync.get("validation_key"):
            raise OperationStateError("Git closeout validation key differs from content binding")
        if validation_row["payload"].get("slice_id") != current_sync.get("validated_slice_id"):
            raise OperationStateError("Git closeout validation slice differs from content binding")
        receipt_object_id = validation_row["payload"].get("receipt_object_id")
        if not isinstance(receipt_object_id, str):
            raise OperationStateError("validation receipt object is missing")
        payload = {
            "closeout_id": closeout_id,
            "validated_content_commit": validated_content_commit,
            "validation_receipt_id": validation_receipt_id,
            "validation_receipt_object_id": receipt_object_id,
            "branch": "main",
            "push_target": "origin/main",
            "local_head_observed": local_head_observed,
            "origin_main_head_observed": origin_main_head_observed,
            "content_state_fingerprint": dirty_fingerprint,
            "dirty_revision": current_sync.get("dirty_revision"),
            "declared_content_paths": list(declared_content_paths),
            "status": "metadata_pending_push",
        }
        object_id = self.objects.put("git_closeout", payload)
        metadata_paths = [
            "registries/v2/control_state.yaml",
            "registries/v2/evidence_ledger.jsonl",
            f"registries/v2/objects/{object_id}.json",
        ]
        row = self._append_or_existing(
            self.evidence,
            closeout_id,
            "git_closeout_recorded",
            {**payload, "closeout_object_id": object_id},
            utc_now(),
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            self._add_authoritative_objects(draft, [object_id])
            draft["reentry"]["git_sync"] = {
                "status": "metadata_pending_push",
                "validated_content_commit": validated_content_commit,
                "local_head": local_head_observed,
                "origin_main_head": origin_main_head_observed,
                "validation_receipt_id": validation_receipt_id,
                "closeout_object_id": object_id,
                "content_state_fingerprint": dirty_fingerprint,
                "dirty_revision": current_sync.get("dirty_revision"),
                "declared_content_paths": list(declared_content_paths),
                "metadata_allowed_paths": metadata_paths,
            }
            if draft.get("root_mission", {}).get("status") == "terminal_validation_pending":
                draft["root_mission"]["status"] = "terminal_pending_push"
                self._set_next_action(
                    draft,
                    make_next_action(
                        "verify_git_closeout",
                        summary="push and verify root terminal metadata",
                    ),
                )

        finalize_root = state.get("root_mission", {}).get("status") == "terminal_validation_pending"
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[receipt_object_id, object_id],
            git_sync_policy="record_metadata",
            root_transition_policy="finalize_metadata" if finalize_root else None,
        )

    def issue_holdout_permit(
        self,
        *,
        permit_id: str,
        candidate_id: str,
        frozen_identity_bundle_sha256: str,
        p_gate_receipt_id: str,
        trial_accounting_receipt_id: str,
        idempotency_key: str,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue, but do not consume, a one-time P-stage holdout permit."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("holdout permits require control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        if re.fullmatch(r"V2HP[0-9]{4}", permit_id) is None:
            raise OperationStateError(f"invalid holdout permit identity: {permit_id}")
        validate_identity("hypothesis", candidate_id)
        cursor = state["cursor"]
        if cursor.get("stage") != "P" or cursor.get("goal_status") != "open":
            raise OperationStateError("holdout permit requires an open P stage")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("holdout permit requires no active evidence job")
        holdout = state.get("holdout", {})
        if holdout.get("reveal_count") != 0 or holdout.get("permit") is not None:
            raise OperationStateError("holdout has already been revealed or permitted")
        self._require_mission_budget_available(state, "holdout_reveals")
        claim = state["claim"]
        if claim.get("subject_id") != candidate_id or claim.get("identity_frozen") is not True:
            raise OperationStateError("candidate identity is not frozen")
        if claim_index(str(claim.get("current_level"))) < claim_index("economics_pass"):
            raise OperationStateError("holdout permit requires economics_pass evidence")
        frozen_object_id = claim.get("identity_bundle_object_id")
        if not isinstance(frozen_object_id, str):
            raise OperationStateError("frozen identity bundle object is missing")
        frozen_object = self.objects.get(frozen_object_id)
        observed_frozen_hash = sha256_payload(frozen_object["payload"])
        if (
            claim.get("frozen_identity_bundle_sha256") != frozen_identity_bundle_sha256
            or observed_frozen_hash != frozen_identity_bundle_sha256
        ):
            raise OperationStateError("frozen identity bundle hash does not match")
        evidence_rows = {row["record_id"]: row for row in self.evidence.rows()}
        p_gate_row = evidence_rows.get(p_gate_receipt_id)
        trial_row = evidence_rows.get(trial_accounting_receipt_id)
        if p_gate_row is None or trial_row is None:
            raise OperationStateError("P gate and trial-accounting receipts must exist in evidence ledger")

        def receipt_from(row: dict[str, Any], label: str) -> tuple[str, dict[str, Any]]:
            object_id = row["payload"].get("receipt_object_id")
            if not isinstance(object_id, str):
                raise OperationStateError(f"{label} evidence has no receipt object")
            return object_id, self.objects.get(object_id)["payload"]

        p_gate_object_id, p_gate_receipt = receipt_from(p_gate_row, "P gate")
        trial_object_id, trial_receipt = receipt_from(trial_row, "trial accounting")
        if (
            p_gate_receipt.get("stage") != "P"
            or p_gate_receipt.get("gate_passed") is not True
            or p_gate_receipt.get("candidate_id") != candidate_id
            or p_gate_receipt.get("frozen_identity_bundle_sha256") != frozen_identity_bundle_sha256
        ):
            raise OperationStateError("P gate receipt is incomplete or belongs to another candidate")
        if (
            trial_receipt.get("trial_accounting_complete") is not True
            or trial_receipt.get("candidate_id") != candidate_id
        ):
            raise OperationStateError("trial-accounting receipt is incomplete or belongs to another candidate")
        git_sync = state["reentry"].get("git_sync")
        if not isinstance(git_sync, dict) or git_sync.get("status") not in {
            "metadata_pending_push",
            "synced",
        }:
            raise OperationStateError("holdout permit requires recorded Git closeout metadata")
        checkpoint = self._metadata_checkpoint_probe(git_sync if isinstance(git_sync, dict) else {})
        if not checkpoint.ok or not isinstance(checkpoint.head, str):
            raise OperationStateError(
                f"holdout permit requires a pushed Git metadata checkpoint: {checkpoint.code}"
            )
        goal_id = cursor["active_goal_id"]
        stage_id = cursor["stage_id"]
        action = next_action or make_next_action(
            "declare_job",
            goal_id=goal_id,
            stage="P",
            subject_id=stage_id,
            job_kind="forward_holdout_reveal",
            prerequisite_receipt_ids=[p_gate_receipt_id, trial_accounting_receipt_id],
            summary=f"declare one-time holdout reveal under {permit_id}",
        )
        validate_next_action(action)
        permit_payload = {
            "permit_id": permit_id,
            "goal_id": goal_id,
            "candidate_id": candidate_id,
            "stage_id": stage_id,
            "frozen_identity_bundle_object_id": frozen_object_id,
            "frozen_identity_bundle_sha256": frozen_identity_bundle_sha256,
            "p_gate_receipt_id": p_gate_receipt_id,
            "trial_accounting_receipt_id": trial_accounting_receipt_id,
            "git_sync_commit": checkpoint.head,
            "reveal_count_before": 0,
            "max_reveals": 1,
            "status": "issued_not_consumed",
        }
        permit_object_id = self.objects.put("holdout_permit", permit_payload)
        row = self._append_or_existing(
            self.evidence,
            permit_id,
            "holdout_permit_issued",
            {**permit_payload, "permit_object_id": permit_object_id},
            utc_now(),
        )
        def mutate(draft: dict[str, Any]) -> None:
            self._consume_mission_budget(draft, "holdout_reveals")
            draft["holdout"]["permit"] = {
                "permit_id": permit_id,
                "permit_object_id": permit_object_id,
                "candidate_id": candidate_id,
                "frozen_identity_bundle_sha256": frozen_identity_bundle_sha256,
                "p_gate_receipt_id": p_gate_receipt_id,
                "trial_accounting_receipt_id": trial_accounting_receipt_id,
            }
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            self._add_authoritative_objects(draft, [permit_object_id])
            self._set_next_action(draft, action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[
                frozen_object_id,
                p_gate_object_id,
                trial_object_id,
                permit_object_id,
            ],
        )

    def close_goal(
        self,
        *,
        outcome: str,
        basis_evidence_id: str,
        summary_payload: dict[str, Any],
        idempotency_key: str,
        root_terminal_outcome: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if outcome not in INTERNAL_GOAL_TERMINAL_OUTCOMES:
            raise OperationStateError(f"invalid internal goal outcome: {outcome}")
        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("generic goal lifecycle requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        cursor = state["cursor"]
        goal_id = cursor.get("active_goal_id")
        if not isinstance(goal_id, str) or cursor.get("goal_status") != "open":
            raise OperationStateError("an open internal goal is required")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("cannot close an internal goal with an active job")
        evidence_row = next(
            (row for row in self.evidence.rows() if row["record_id"] == basis_evidence_id),
            None,
        )
        if evidence_row is None:
            raise OperationStateError(f"basis evidence does not exist: {basis_evidence_id}")
        evidence_goal_id = evidence_row["payload"].get("goal_id")
        if evidence_goal_id != goal_id:
            raise OperationStateError("goal closeout evidence does not belong to the active goal")
        if root_terminal_outcome is None and outcome == "completed_internal_goal":
            root_terminal_outcome = INTERNAL_TO_ROOT_OUTCOME[outcome]
        if root_terminal_outcome is not None:
            expected_root_outcome = INTERNAL_TO_ROOT_OUTCOME[outcome]
            if root_terminal_outcome != expected_root_outcome:
                raise OperationStateError("internal and root terminal outcomes do not correspond")
            if next_action is not None:
                raise OperationStateError("root closeout next_action is writer-owned")
            if state["root_mission"].get("status") != "active":
                raise OperationStateError("root terminal request requires an active root mission")
            if (
                root_terminal_outcome == "completed_pre_live_handoff"
                and state["claim"].get("current_level") != "pre_live_ready"
            ):
                raise OperationStateError("successful root request requires pre_live_ready claim")
            next_action = make_next_action(
                "close_root_mission",
                mission_id=state["root_mission"]["mission_id"],
                terminal_outcome=root_terminal_outcome,
                basis_evidence_id=basis_evidence_id,
                prerequisite_receipt_ids=[basis_evidence_id],
                summary=f"close root mission as {root_terminal_outcome}",
            )
        elif next_action is None:
            next_action = make_next_action(
                "open_goal",
                goal_id=format_identity("goal", state["namespace"]["next_goal"]),
                summary="open the next internal research goal",
            )
        elif next_action.get("kind") == "close_root_mission":
            raise OperationStateError("caller may not inject a root closeout action")
        validate_next_action(next_action)
        request_object_id: str | None = None
        terminal_request: dict[str, Any] | None = None
        if root_terminal_outcome is not None:
            request_payload = {
                "mission_id": state["root_mission"]["mission_id"],
                "outcome": root_terminal_outcome,
                "basis_evidence_id": basis_evidence_id,
                "requested_by_goal_id": goal_id,
                "claim_snapshot": state["claim"],
            }
            request_object_id = self.objects.put("root_terminal_request", request_payload)
            terminal_request = {
                "mission_id": request_payload["mission_id"],
                "outcome": root_terminal_outcome,
                "basis_evidence_id": basis_evidence_id,
                "requested_by_goal_id": goal_id,
                "request_object_id": request_object_id,
            }
        summary = {
            "goal_id": goal_id,
            "outcome": outcome,
            "basis_evidence_id": basis_evidence_id,
            "summary": summary_payload,
            "root_terminal_request_object_id": request_object_id,
        }
        object_id = self.objects.put("internal_goal_closeout", summary)
        row = self._append_or_existing(
            self.evidence,
            f"{goal_id}_CLOSEOUT",
            "internal_goal_closed",
            {
                "goal_id": goal_id,
                "outcome": outcome,
                "basis_evidence_id": basis_evidence_id,
                "summary_object_id": object_id,
                "root_terminal_request_object_id": request_object_id,
            },
            utc_now(),
        )
        def mutate(draft: dict[str, Any]) -> None:
            history = draft.setdefault("history", {}).setdefault("recent_closed_goals", [])
            history.append(
                {"goal_id": goal_id, "outcome": outcome, "summary_object_id": object_id}
            )
            draft["history"]["recent_closed_goals"] = history[-RECENT_CLOSED_GOAL_LIMIT:]
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            draft["cursor"].update(
                {
                    "active_goal_id": None,
                    "active_goal_object_id": None,
                    "goal_status": "closed",
                    "last_closed_goal_id": goal_id,
                    "last_goal_outcome": outcome,
                    "active_hypothesis_id": None,
                    "stage": "idle",
                    "stage_id": None,
                    "stage_status": "idle",
                    "terminal_outcome": None,
                }
            )
            self._set_next_action(draft, next_action)
            if terminal_request is not None:
                draft["root_mission"]["terminal_request"] = terminal_request
            draft["claim"] = {
                "subject_kind": "none",
                "subject_id": None,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": None,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            draft["reentry"]["active_job"] = None
            draft["reentry"]["current_object_ids"] = []
            draft["reentry"]["current_artifact_hashes"] = {}
            draft["reentry"]["completed_receipt_ids"] = []
            draft["reentry"]["completed_evidence_ids"] = []
            draft["slice_budget"] = None
            authoritative = [object_id]
            if request_object_id is not None:
                authoritative.append(request_object_id)
            self._add_authoritative_objects(draft, authoritative)

        referenced = [object_id]
        if request_object_id is not None:
            referenced.append(request_object_id)
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=referenced,
        )

    def close_root_mission(
        self,
        *,
        outcome: str,
        basis_evidence_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Close the persistent root only from durable terminal evidence."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("root mission closeout requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        if outcome not in ROOT_TERMINAL_OUTCOMES:
            raise OperationStateError(f"invalid root mission outcome: {outcome}")
        root_mission = state["root_mission"]
        if root_mission.get("status") != "active":
            raise OperationStateError("root mission closeout requires active status")
        if state["cursor"].get("active_goal_id") is not None:
            raise OperationStateError("close the active internal goal before the root mission")
        if state["reentry"].get("active_job") is not None:
            raise OperationStateError("root mission cannot close with an active job")
        action = state["cursor"].get("next_action")
        if not isinstance(action, dict) or action.get("kind") != "close_root_mission":
            raise OperationStateError("root closeout requires its structured next action")
        if (
            action.get("mission_id") != root_mission["mission_id"]
            or action.get("terminal_outcome") != outcome
            or action.get("basis_evidence_id") != basis_evidence_id
        ):
            raise OperationStateError("root closeout arguments differ from the structured action")
        request = root_mission.get("terminal_request")
        if not isinstance(request, dict):
            raise OperationStateError("root terminal request is missing")
        if (
            request.get("mission_id") != root_mission["mission_id"]
            or request.get("outcome") != outcome
            or request.get("basis_evidence_id") != basis_evidence_id
        ):
            raise OperationStateError("root terminal request differs from closeout arguments")
        request_object_id = request.get("request_object_id")
        if not isinstance(request_object_id, str):
            raise OperationStateError("root terminal request object is missing")
        request_payload = self.objects.get(request_object_id)["payload"]
        evidence_row = next(
            (row for row in self.evidence.rows() if row["record_id"] == basis_evidence_id),
            None,
        )
        if evidence_row is None:
            raise OperationStateError("root mission basis evidence is missing")
        receipt_object_id = evidence_row["payload"].get("receipt_object_id")
        if not isinstance(receipt_object_id, str):
            raise OperationStateError("root mission basis evidence has no receipt object")
        receipt = self.objects.get(receipt_object_id)["payload"]
        mission_id = root_mission["mission_id"]
        if receipt.get("mission_id") != mission_id or receipt.get("outcome") != outcome:
            raise OperationStateError("root mission basis receipt identity or outcome differs")
        if outcome == "closed_no_candidate":
            if receipt.get("material_exhaustion_complete") is not True:
                raise OperationStateError("closed_no_candidate requires material exhaustion evidence")
            if not (
                receipt.get("mission_budget_exhausted") is True
                or receipt.get("remaining_axes_low_information_value") is True
            ):
                raise OperationStateError("material exhaustion basis is incomplete")
        claim_snapshot = request_payload.get("claim_snapshot")
        if outcome == "completed_pre_live_handoff" and (
            not isinstance(claim_snapshot, dict)
            or claim_snapshot.get("current_level") != "pre_live_ready"
        ):
            raise OperationStateError("successful root closeout requires pre_live_ready request claim")
        if outcome == "blocked_external" and not isinstance(state["reentry"].get("blocker"), dict):
            raise OperationStateError("blocked_external requires a complete blocker")
        payload = {
            "mission_id": mission_id,
            "outcome": outcome,
            "basis_evidence_id": basis_evidence_id,
            "basis_receipt_object_id": receipt_object_id,
            "terminal_request_object_id": request_object_id,
            "mission_budget": state["mission_budget"],
            "status": "terminal_validation_pending",
        }
        object_id = self.objects.put("root_mission_closeout", payload)
        row = self._append_or_existing(
            self.evidence,
            f"{mission_id}_CLOSEOUT",
            "root_mission_closed",
            {**payload, "closeout_object_id": object_id},
            utc_now(),
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["root_mission"]["status"] = "terminal_validation_pending"
            draft["root_mission"]["terminal_outcome"] = outcome
            draft["root_mission"]["closeout_object_id"] = object_id
            draft["cursor"]["terminal_outcome"] = outcome
            self._set_next_action(
                draft,
                make_next_action(
                    "validate_root_closeout",
                    summary=f"validate root terminal content: {outcome}",
                ),
            )
            terminal_slice_id = f"{mission_id}_terminal_closeout"
            draft["slice_budget"] = self._new_slice_budget(terminal_slice_id)
            draft["slice_budget"]["implementation_remaining"] = 0
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            self._add_authoritative_objects(draft, [object_id])

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[request_object_id, receipt_object_id, object_id],
            root_transition_policy="prepare_validation",
        )

    def register_material_batch(
        self,
        records: tuple[MaterialRecord, ...],
        *,
        idempotency_key: str,
        exact_next_action: str | dict[str, Any],
        occurred_at_utc: str | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        occurred = occurred_at_utc or utc_now()
        object_ids: list[str] = []
        rows: list[dict[str, Any]] = []
        for record in records:
            material_payload = {
                "material_id": record.material_id,
                "kind": record.kind,
                **record.payload,
            }
            object_id = self.objects.put("material", material_payload)
            row = self._append_or_existing(
                self.materials,
                record.material_id,
                "material_registered",
                {"material_object_id": object_id, **material_payload},
                occurred,
            )
            object_ids.append(object_id)
            rows.append(row)
        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, object_ids)
            draft["ledger_heads"]["material"] = {
                "ledger_seq": rows[-1]["ledger_seq"],
                "row_sha256": rows[-1]["row_sha256"],
            }
            artifact_hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if self._is_v2_state(draft) else "artifact_hashes",
                {},
            )
            for record, object_id in zip(records, object_ids, strict=True):
                artifact_hashes[record.material_id] = object_id
            self._set_next_action(draft, exact_next_action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=object_ids,
        )

    def preregister_hypothesis(
        self,
        *,
        hypothesis_id: str | None,
        spec_path: str,
        spec_sha256: str,
        spec_payload: dict[str, Any],
        split_set_id: str,
        material_ids: list[str],
        idempotency_key: str,
        goal_id: str | None = None,
        acceptance_profile_id: str = "V2SAP0001",
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        is_v2 = self._is_v2_state(state)
        if is_v2:
            active_goal_id = state["cursor"].get("active_goal_id")
            if state["cursor"].get("goal_status") != "open" or not isinstance(active_goal_id, str):
                raise OperationStateError("an open internal goal is required before preregistration")
            if goal_id is not None and goal_id != active_goal_id:
                raise OperationStateError("hypothesis goal_id does not match active goal")
            goal_id = active_goal_id
            allocated, namespace_field, counter = self._allocated_identity(
                state, "hypothesis", hypothesis_id
            )
            hypothesis_id = allocated
            self._require_mission_budget_available(state, "hypothesis_batches")
            if spec_payload.get("goal_id") != goal_id:
                raise OperationStateError("hypothesis spec goal_id does not match active goal")
            if spec_payload.get("hypothesis_id") != hypothesis_id:
                raise OperationStateError("hypothesis spec identity does not match allocated identity")
            try:
                from axiom_rift.v2.research.scout import validate_hypothesis_v2_payload

                validated_hypothesis = validate_hypothesis_v2_payload(spec_payload)
            except (ImportError, ValueError) as exc:
                raise OperationStateError(f"hypothesis preregistration is invalid: {exc}") from exc
            acceptance = spec_payload.get("acceptance_profile", {})
            data = spec_payload.get("data", {})
            if acceptance.get("profile_id") != acceptance_profile_id:
                raise OperationStateError("acceptance profile identity differs from writer input")
            if data.get("split_set_id") != split_set_id:
                raise OperationStateError("split-set identity differs from writer input")
            if validated_hypothesis["sensitivity_plan"].hypothesis_id != hypothesis_id:
                raise OperationStateError("sensitivity plan identity differs from hypothesis")
            trial_plan = validated_hypothesis["trial_plan"]
            family_id = trial_plan.get("family_id")
            if not isinstance(family_id, str) or not family_id:
                raise OperationStateError("trial family identity is missing")
            durable_family_hashes = self._durable_family_configuration_hashes(family_id)
            declared_family_hashes = self._require_sorted_sha256_list(
                trial_plan.get("family_configuration_hashes_before"),
                "family_configuration_hashes_before",
            )
            if declared_family_hashes != durable_family_hashes:
                raise OperationStateError(
                    "hypothesis family history differs from durable evidence receipts"
                )
            if trial_plan.get("family_trials_before") != len(durable_family_hashes):
                raise OperationStateError("hypothesis family trial count is not durable")
            if trial_plan.get("family_history_sha256_before") != sha256_payload(
                durable_family_hashes
            ):
                raise OperationStateError("hypothesis family history hash is invalid")
            durable_global_hashes = self._durable_global_configuration_hashes()
            declared_global_hashes = self._require_sorted_sha256_list(
                trial_plan.get("global_configuration_hashes_before"),
                "global_configuration_hashes_before",
            )
            if declared_global_hashes != durable_global_hashes:
                raise OperationStateError(
                    "hypothesis global history differs from durable evidence receipts"
                )
            if trial_plan.get("global_trials_before") != len(durable_global_hashes):
                raise OperationStateError("hypothesis global trial count is not durable")
            if trial_plan.get("global_history_sha256_before") != sha256_payload(
                durable_global_hashes
            ):
                raise OperationStateError("hypothesis global history hash is invalid")
        else:
            if hypothesis_id != "V2H0001":
                raise ValueError("bootstrap writer expects the first V2 hypothesis identity")
            goal_id = "V2G0001"
            namespace_field = "next_hypothesis"
            counter = 1
        action = next_action or (
            make_next_action(
                "open_stage",
                goal_id=goal_id,
                stage="S",
                subject_id=format_identity("scout", state["namespace"]["next_scout"]),
                prerequisite_receipt_ids=[],
                summary=f"open causal scout for {hypothesis_id}",
            )
            if is_v2
            else "open_V2S0001_causal_scout"
        )
        if is_v2:
            validate_next_action(action)
        occurred = utc_now()
        object_id = self.objects.put("hypothesis_spec", spec_payload)
        ledger_payload = {
            "goal_id": goal_id,
            "hypothesis_id": hypothesis_id,
            "spec_path": spec_path,
            "spec_sha256": spec_sha256,
            "hypothesis_object_id": object_id,
            "origin": "newly_originated_v2",
            "v1_evidence_inherited": False,
            "material_ids": material_ids,
            "split_set_id": split_set_id,
            "acceptance_profile_id": acceptance_profile_id,
            "claim_ceiling": "diagnostic_observation",
            "status": "preregistered",
        }
        row = self._append_or_existing(
            self.hypotheses,
            hypothesis_id,
            "hypothesis_preregistered",
            ledger_payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            if draft["namespace"][namespace_field] != counter:
                raise ValueError("hypothesis namespace changed before commit")
            draft["namespace"][namespace_field] = counter + 1
            if is_v2:
                self._consume_mission_budget(draft, "hypothesis_batches")
            draft["cursor"] = transition_stage(draft["cursor"], "H", hypothesis_id)
            draft["cursor"]["active_hypothesis_id"] = hypothesis_id
            draft["cursor"]["stage_status"] = "preregistered"
            self._set_next_action(draft, action)
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            draft["claim"] = {
                "subject_kind": "hypothesis",
                "subject_id": hypothesis_id,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": object_id,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            if not is_v2:
                draft["reentry"]["active_slice_id"] = "V2SL0005_first_scout"
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[hypothesis_id] = object_id

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def preregister_autonomous_hypothesis(
        self,
        *,
        batch_payload: dict[str, Any],
        idempotency_key: str,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register one future-epoch batch without using bootstrap scout semantics."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("autonomous preregistration requires schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        scientific = state.get("scientific")
        if not isinstance(scientific, dict) or scientific.get("status") != "active":
            raise OperationStateError("an active scientific epoch is required")
        goal_id = state.get("cursor", {}).get("active_goal_id")
        if state.get("cursor", {}).get("goal_status") != "open" or not isinstance(goal_id, str):
            raise OperationStateError("an open internal goal is required")
        try:
            from axiom_rift.v2.research.autonomy import HypothesisBatch

            batch = HypothesisBatch.from_payload(batch_payload)
        except (ImportError, ValueError) as exc:
            raise OperationStateError(f"autonomous hypothesis batch is invalid: {exc}") from exc
        if batch.scientific_epoch_id != scientific.get("epoch_id"):
            raise OperationStateError("hypothesis epoch differs from active science")
        allocated, namespace_field, counter = self._allocated_identity(
            state,
            "hypothesis",
            batch.hypothesis_id,
        )
        self._require_mission_budget_available(state, "hypothesis_batches")
        action = next_action or make_next_action(
            "open_stage",
            goal_id=goal_id,
            stage="S",
            subject_id=format_identity("scout", state["namespace"]["next_scout"]),
            summary=f"open registered Scout mode for {allocated}",
        )
        validate_next_action(action)
        object_id = self.objects.put("autonomous_hypothesis_batch", batch.to_payload())
        row = self._append_or_existing(
            self.hypotheses,
            allocated,
            "autonomous_hypothesis_preregistered",
            {
                "goal_id": goal_id,
                "hypothesis_id": allocated,
                "hypothesis_object_id": object_id,
                "scientific_epoch_id": batch.scientific_epoch_id,
                "hypothesis_type": batch.hypothesis_type,
                "scout_mode": batch.scout_mode,
                "claim_ceiling": "diagnostic_observation",
            },
            utc_now(),
        )

        def mutate(draft: dict[str, Any]) -> None:
            if draft["namespace"][namespace_field] != counter:
                raise OperationStateError("hypothesis namespace changed before commit")
            draft["namespace"][namespace_field] = counter + 1
            self._consume_mission_budget(draft, "hypothesis_batches")
            draft["cursor"] = transition_stage(draft["cursor"], "H", allocated)
            draft["cursor"]["active_hypothesis_id"] = allocated
            draft["cursor"]["stage_status"] = "preregistered"
            self._set_next_action(draft, action)
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            refs = draft["scientific"]["hypothesis_object_ids"]
            if object_id not in refs:
                refs.append(object_id)
            draft["claim"] = {
                "subject_kind": "hypothesis",
                "subject_id": allocated,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": object_id,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            draft["reentry"]["current_artifact_hashes"][allocated] = object_id

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def open_scout(
        self,
        *,
        idempotency_key: str,
        scout_id: str | None = None,
        next_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._is_v2_state(state):
            return self.open_stage(
                new_stage="S",
                stage_id=scout_id,
                idempotency_key=idempotency_key,
                next_action=next_action,
            )
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)

        def mutate(draft: dict[str, Any]) -> None:
            if draft["namespace"]["next_scout"] != 1:
                raise ValueError("scout namespace does not point to V2S0001")
            draft["namespace"]["next_scout"] = 2
            draft["cursor"] = transition_stage(draft["cursor"], "S", "V2S0001")
            draft["cursor"]["exact_next_action"] = "run_V2S0001_bounded_real_data_scout"
            draft["claim"]["claim_ceiling"] = "diagnostic_observation"
            draft["reentry"]["active_job"] = {
                "job_id": "V2S0001",
                "kind": "bounded_real_data_scout",
                "status": "declared",
                "started_at_utc": utc_now(),
                "timeout_seconds": 120,
                "mt5": False,
                "fold_count": 3,
            }

        return self.control.commit(state["revision"], idempotency_key, mutate)

    def record_evidence(
        self,
        *,
        evidence_id: str,
        record_type: str,
        receipt: dict[str, Any],
        idempotency_key: str,
        exact_next_action: str | dict[str, Any],
        promote_diagnostic_observation: bool = False,
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        is_v2 = self._is_v2_state(state)
        active_job = state.get("reentry", {}).get("active_job")
        job_matched = False
        if is_v2:
            if not isinstance(exact_next_action, dict):
                raise TransitionError("schema v2 evidence recording requires structured next_action")
            validate_next_action(exact_next_action)
            expected_context = {
                "goal_id": state["cursor"].get("active_goal_id"),
                "stage": state["cursor"].get("stage"),
                "stage_id": state["cursor"].get("stage_id"),
            }
            observed_context = {field: receipt.get(field) for field in expected_context}
            if observed_context != expected_context:
                raise OperationStateError(
                    f"evidence receipt does not match active stage: expected {expected_context}, "
                    f"observed {observed_context}"
                )
            receipt_hypothesis = receipt.get("hypothesis_id")
            if receipt_hypothesis is not None and receipt_hypothesis != state["cursor"].get("active_hypothesis_id"):
                raise OperationStateError("evidence receipt hypothesis does not match active hypothesis")
        if is_v2 and active_job is not None:
            if not isinstance(active_job, dict):
                raise OperationStateError("active_job is invalid")
            expected = {
                "job_id": active_job.get("job_id"),
                "goal_id": active_job.get("goal_id"),
                "stage_id": active_job.get("stage_id"),
                "input_hash": active_job.get("input_hash"),
            }
            observed = {field: receipt.get(field) for field in expected}
            if observed != expected:
                raise OperationStateError(
                    f"evidence receipt does not match active job: expected {expected}, observed {observed}"
                )
            if active_job.get("status") not in {"running", "completed_pending_record"}:
                raise OperationStateError("active job must be running or completed_pending_record")
            receipt_artifacts = receipt.get("artifacts")
            artifact_paths = {
                item.get("path")
                for item in receipt_artifacts.values()
                if isinstance(receipt_artifacts, dict) and isinstance(item, dict)
            } if isinstance(receipt_artifacts, dict) else set()
            missing_artifacts = set(active_job.get("expected_artifacts", [])) - artifact_paths
            if missing_artifacts:
                raise OperationStateError(
                    "evidence receipt is missing active-job artifacts: "
                    + ", ".join(sorted(missing_artifacts))
                )
            job_matched = True
        if is_v2:
            self._validate_nested_scout_receipt(receipt)
        occurred = utc_now()
        object_id = self.objects.put("evidence_receipt", receipt)
        payload = {
            "evidence_id": evidence_id,
            "goal_id": receipt.get("goal_id", "V2G0001" if not is_v2 else None),
            "hypothesis_id": receipt.get("hypothesis_id"),
            "stage": receipt.get("stage", "bootstrap"),
            "stage_id": receipt.get("stage_id"),
            "receipt_object_id": object_id,
            "outcome": receipt.get("outcome", receipt.get("status")),
            "claim_ceiling": receipt.get("claim_ceiling", "none"),
            "result_sha256": receipt.get("result_sha256"),
        }
        row = self._append_or_existing(
            self.evidence,
            evidence_id,
            record_type,
            payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            completed = draft["reentry"].setdefault("completed_evidence_ids", [])
            if evidence_id not in completed:
                completed.append(evidence_id)
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[evidence_id] = object_id
            if job_matched:
                draft["reentry"]["active_job"] = None
            self._set_next_action(draft, exact_next_action)
            if receipt.get("stage") == str(draft["cursor"].get("stage")):
                draft["cursor"]["stage_status"] = "completed"
                draft["cursor"]["stage_outcome"] = receipt.get("outcome")
            if promote_diagnostic_observation and draft["claim"]["current_level"] == "none":
                draft["claim"] = promote_claim(
                    draft["claim"], "diagnostic_observation", [evidence_id]
                )

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def record_hypothesis_disposition(
        self,
        *,
        hypothesis_id: str,
        evidence_id: str,
        outcome: str,
        memory_path: str,
        memory_sha256: str,
        memory_payload: dict[str, Any],
        idempotency_key: str,
        exact_next_action: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        is_v2 = self._is_v2_state(state)
        goal_id = (
            state["cursor"].get("active_goal_id") if is_v2 else "V2G0001"
        )
        if is_v2:
            if exact_next_action is None and isinstance(goal_id, str):
                exact_next_action = make_next_action(
                    "preregister_hypothesis",
                    goal_id=goal_id,
                    stage="H",
                    subject_id=format_identity(
                        "hypothesis", state["namespace"]["next_hypothesis"]
                    ),
                    prerequisite_receipt_ids=[evidence_id],
                    summary="select and preregister the next distinct high-information hypothesis",
                )
            if not isinstance(exact_next_action, dict):
                raise TransitionError("schema v2 disposition requires structured next_action")
            validate_next_action(exact_next_action)
            validate_identity("hypothesis", hypothesis_id)
            if state["cursor"].get("active_hypothesis_id") != hypothesis_id:
                raise OperationStateError("disposition hypothesis is not active")
            if not isinstance(goal_id, str):
                raise OperationStateError("disposition requires an active goal")
            evidence_row = next(
                (row for row in self.evidence.rows() if row["record_id"] == evidence_id),
                None,
            )
            if evidence_row is None or evidence_row["payload"].get("hypothesis_id") != hypothesis_id:
                raise OperationStateError("disposition basis evidence does not match active hypothesis")
        elif exact_next_action is None:
            raise TransitionError("schema v1 disposition requires exact_next_action text")
        occurred = utc_now()
        object_id = self.objects.put("negative_memory", memory_payload)
        record_id = f"{hypothesis_id}_DISPOSITION"
        payload = {
            "goal_id": goal_id,
            "hypothesis_id": hypothesis_id,
            "event_type": "disposition_recorded",
            "outcome": outcome,
            "evidence_ids": [evidence_id],
            "negative_memory_path": memory_path,
            "negative_memory_sha256": memory_sha256,
            "negative_memory_object_id": object_id,
            "claim_ceiling": "diagnostic_observation",
        }
        row = self._append_or_existing(
            self.hypotheses,
            record_id,
            "hypothesis_disposition_recorded",
            payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[f"{hypothesis_id}_negative_memory"] = object_id
            self._set_next_action(draft, exact_next_action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def advance_stage(
        self,
        *,
        new_stage: str,
        stage_id: str,
        basis_evidence_id: str,
        idempotency_key: str,
        exact_next_action: str | dict[str, Any],
    ) -> dict[str, Any]:
        state = self.control.load()
        if self._is_v2_state(state):
            if not isinstance(exact_next_action, dict):
                raise TransitionError("schema v2 stage transition requires structured next_action")
            return self.open_stage(
                new_stage=new_stage,
                stage_id=stage_id,
                basis_evidence_id=basis_evidence_id,
                idempotency_key=idempotency_key,
                next_action=exact_next_action,
            )
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        evidence_row = next(
            (row for row in self.evidence.rows() if row["record_id"] == basis_evidence_id),
            None,
        )
        if evidence_row is None:
            raise ValueError(f"basis evidence does not exist: {basis_evidence_id}")
        receipt_object_id = evidence_row["payload"].get("receipt_object_id")
        if not isinstance(receipt_object_id, str):
            raise ValueError("basis evidence has no receipt object")
        receipt = self.objects.get(receipt_object_id)["payload"]
        validate_stage_basis(
            current_stage=str(state["cursor"]["stage"]),
            new_stage=new_stage,
            new_stage_id=stage_id,
            current_claim=str(state["claim"]["current_level"]),
            basis=receipt,
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["cursor"] = transition_stage(draft["cursor"], new_stage, stage_id)
            self._set_next_action(draft, exact_next_action)
            draft["reentry"]["active_job"] = None

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[receipt_object_id],
        )

    def record_validation_receipt(
        self,
        *,
        receipt_id: str,
        receipt: dict[str, Any],
        idempotency_key: str,
        exact_next_action: str | dict[str, Any],
    ) -> dict[str, Any]:
        if receipt.get("outcome") not in {"pass", "fail"}:
            raise ValueError("validation receipt outcome must be pass or fail")
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        is_v2 = self._is_v2_state(state)
        if is_v2:
            if not isinstance(exact_next_action, dict):
                raise TransitionError("schema v2 validation receipt requires structured next_action")
            validate_next_action(exact_next_action)
        occurred = utc_now()
        object_id = self.objects.put("validation_receipt", receipt)
        payload = {
            "validation_key": receipt["validation_key"],
            "outcome": receipt["outcome"],
            "receipt_object_id": object_id,
            "validator_id": receipt["validator_id"],
            "duration_seconds": receipt["duration_seconds"],
            "slice_id": receipt.get("slice_id"),
        }
        row = self._append_or_existing(
            self.validation_receipts,
            receipt_id,
            "validation_receipt_recorded",
            payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["validation_receipt"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            completed = draft["reentry"].setdefault("completed_receipt_ids", [])
            if receipt_id not in completed:
                completed.append(receipt_id)
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[receipt_id] = object_id
            self._set_next_action(draft, exact_next_action)

        terminal_policy = (
            "validation_mutation"
            if state.get("root_mission", {}).get("status") == "terminal_validation_pending"
            else None
        )
        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
            terminal_validation_policy=terminal_policy,
        )

    def migrate_control_state_v1_to_v2(
        self,
        *,
        mission_id: str,
        mission_contract_path: str,
        mission_contract_sha256: str,
        mission_budget_limits: Mapping[str, int] | None = None,
        idempotency_key: str = "migrate_control_state_v1_to_v2",
        closed_goal_id: str = "V2G0001",
        closed_work_unit_id: str = "V2B0001",
    ) -> dict[str, Any]:
        """Atomically replace the activated bootstrap snapshot with compact V2.1 state.

        Immutable activation objects and every ledger head are retained. The
        bootstrap goal is recorded as history, while the root mission becomes
        ready for the already-reserved next internal goal.
        """

        state = self.control.load()
        if self._is_v2_state(state):
            migration = state.get("migration", {})
            if self._already_applied(state, idempotency_key) or migration.get("v1_to_v2") == "completed":
                return state
            raise OperationStateError("control state already uses schema v2 without migration marker")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        if state.get("active_truth") != "v2" or state.get("bootstrap_goal_outcome") != "activated":
            raise OperationStateError("migration requires completed V2 activation")
        if state.get("reentry", {}).get("active_job") is not None:
            raise OperationStateError("migration requires no active evidence job")
        validate_identity("goal", closed_goal_id)
        activation = state.get("activation")
        if not isinstance(activation, dict):
            raise OperationStateError("migration requires activation evidence references")
        activation_evidence_id = activation.get("activation_evidence_id")
        activation_object_id = activation.get("activation_object_id")
        if not isinstance(activation_evidence_id, str) or not isinstance(activation_object_id, str):
            raise OperationStateError("activation evidence identity is incomplete")
        self.objects.get(activation_object_id)
        limits = dict(mission_budget_limits or DEFAULT_MISSION_BUDGET_LIMITS)
        if set(limits) != set(DEFAULT_MISSION_BUDGET_LIMITS) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in limits.values()
        ):
            raise OperationStateError("mission budget limits are incomplete or invalid")
        reserved_goal_id = format_identity("goal", state["namespace"]["next_goal"])
        summary_payload = {
            "goal_id": closed_goal_id,
            "work_unit_id": closed_work_unit_id,
            "outcome": "completed_v2_activation",
            "activation_evidence_id": activation_evidence_id,
            "activation_object_id": activation_object_id,
            "candidate_validation_receipt_id": activation.get("candidate_validation_receipt_id"),
            "ledger_heads": state.get("ledger_heads", {}),
            "git_closeout": state.get("reentry", {}).get("git_closeout"),
        }
        summary_object_id = self.objects.put("bootstrap_goal_closeout", summary_payload)
        next_action = make_next_action(
            "open_goal",
            goal_id=reserved_goal_id,
            summary=f"open reserved internal goal {reserved_goal_id}",
        )
        def mutate(draft: dict[str, Any]) -> None:
            draft["schema"] = CONTROL_STATE_SCHEMA_V2
            draft["status"] = "active"
            draft.pop("goal_id", None)
            draft["root_mission"] = {
                "mission_id": mission_id,
                "contract_path": mission_contract_path,
                "contract_sha256": mission_contract_sha256,
                "status": "ready",
                "terminal_outcome": None,
                "user_goal_received": False,
            }
            draft["mission_budget"] = {
                "frozen": False,
                "limits": limits,
                "remaining": dict(limits),
            }
            draft["slice_budget"] = None
            draft["cursor"] = {
                "active_goal_id": None,
                "active_goal_object_id": None,
                "goal_status": "closed",
                "last_closed_goal_id": closed_goal_id,
                "last_goal_outcome": "completed_v2_activation",
                "active_hypothesis_id": None,
                "stage": "idle",
                "stage_id": None,
                "stage_status": "idle",
                "terminal_outcome": None,
                "next_action": next_action,
            }
            draft["reentry"] = {
                "active_job": None,
                "current_object_ids": [],
                "current_artifact_hashes": {},
                "completed_receipt_ids": [],
                "completed_evidence_ids": [],
                "blocker": None,
                "git_sync": {
                    "status": "unsynced",
                    "invalidated_by_operation": "migrate_control_state_v1_to_v2",
                    "previous_validated_content_commit": None,
                },
            }
            draft["claim"] = {
                "subject_kind": "none",
                "subject_id": None,
                "current_level": "none",
                "claim_ceiling": "none",
                "identity_bundle_object_id": None,
                "basis_receipt_ids": [],
                "blocked_by": [],
            }
            draft["history"] = {
                "recent_closed_goals": [
                    {
                        "goal_id": closed_goal_id,
                        "work_unit_id": closed_work_unit_id,
                        "outcome": "completed_v2_activation",
                        "summary_object_id": summary_object_id,
                    }
                ],
                "activation_closeout_object_id": summary_object_id,
            }
            draft["holdout"] = {
                "reveal_count": 0,
                "max_reveals": 1,
                "permit": None,
            }
            draft["migration"] = {
                "v1_to_v2": "completed",
                "source_schema": "axiom_rift_v2_control_state_v1",
                "closed_goal_id": closed_goal_id,
                "closed_work_unit_id": closed_work_unit_id,
                "reserved_next_goal_id": reserved_goal_id,
            }

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[summary_object_id, activation_object_id],
        )

    def activate_v2(
        self,
        *,
        candidate_validation_receipt_id: str,
        activation_evidence_id: str,
        idempotency_key: str,
        post_activation_action: str,
    ) -> dict[str, Any]:
        validation_row = next(
            (
                row
                for row in self.validation_receipts.rows()
                if row["record_id"] == candidate_validation_receipt_id
            ),
            None,
        )
        if validation_row is None or validation_row["payload"].get("outcome") != "pass":
            raise ValueError("V2 activation requires a passing candidate validation receipt")
        validation_object_id = validation_row["payload"]["receipt_object_id"]
        validation_receipt = self.objects.get(validation_object_id)["payload"]
        if validation_receipt.get("phase") != "candidate":
            raise ValueError("activation basis receipt is not a candidate-phase gate")
        state = self.control.load()
        if self._already_applied(state, idempotency_key):
            return state
        if self._is_v2_state(state):
            raise ValueError("activate_v2 is bootstrap-only and cannot run on schema v2")
        self._require_reconciled(state)
        if state.get("active_truth") != "v1_until_v2_activation":
            raise ValueError("activation compare-and-swap expected V1 authority")
        activation_receipt = {
            "schema": "axiom_rift_v2_activation_receipt_v1",
            "goal_id": "V2G0001",
            "stage": "bootstrap",
            "stage_id": "V2A0001",
            "status": "passed",
            "outcome": "v2_activated",
            "expected_before": "v1_until_v2_activation",
            "active_truth_after": "v2",
            "expected_revision": state["revision"],
            "resulting_revision": state["revision"] + 1,
            "candidate_validation_receipt_id": candidate_validation_receipt_id,
            "candidate_validation_object_id": validation_object_id,
            "required_evidence_ids": ["V2E000004", "V2E000005", "V2E000006", "V2E000007"],
            "first_scout_outcome": state["cursor"].get("stage_outcome"),
            "post_activation_action": post_activation_action,
            "activation_is_alpha_evidence": False,
            "selected_or_runtime_claim_created": False,
            "claim_ceiling": "none",
            "occurred_at_utc": utc_now(),
        }
        activation_object_id = self.objects.put("activation_receipt", activation_receipt)
        evidence_payload = {
            "evidence_id": activation_evidence_id,
            "goal_id": "V2G0001",
            "hypothesis_id": None,
            "stage": "bootstrap",
            "stage_id": "V2A0001",
            "receipt_object_id": activation_object_id,
            "outcome": "v2_activated",
            "claim_ceiling": "none",
            "result_sha256": activation_object_id,
        }
        evidence_row = self._append_or_existing(
            self.evidence,
            activation_evidence_id,
            "v2_activation_recorded",
            evidence_payload,
            activation_receipt["occurred_at_utc"],
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["active_truth"] = "v2"
            draft["status"] = "active"
            draft["bootstrap_goal_outcome"] = "activated"
            draft["activation"] = {
                "activation_evidence_id": activation_evidence_id,
                "activation_object_id": activation_object_id,
                "candidate_validation_receipt_id": candidate_validation_receipt_id,
                "rollback_authority": "pre_closeout_only",
            }
            self._add_authoritative_objects(draft, [activation_object_id, validation_object_id])
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": evidence_row["ledger_seq"],
                "row_sha256": evidence_row["row_sha256"],
            }
            completed = draft["reentry"].setdefault("completed_evidence_ids", [])
            if activation_evidence_id not in completed:
                completed.append(activation_evidence_id)
            draft["reentry"]["artifact_hashes"][activation_evidence_id] = activation_object_id
            draft["reentry"]["active_slice_id"] = "V2SL0006_activation_closeout"
            draft["reentry"]["active_job"] = None
            draft["cursor"]["exact_next_action"] = post_activation_action

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[activation_object_id, validation_object_id],
        )
