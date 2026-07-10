"""Single-writer orchestration for V2 objects, ledgers, and control state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
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
from axiom_rift.v2.state import ControlStateError, ControlStore
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
                try:
                    configured = self.control.load(
                        allow_legacy_scientific_bind=True
                    ).get("scientific", {}).get("hypothesis_ledger_path")
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

    def _durable_family_configuration_hashes(
        self,
        family_id: str,
        *,
        exclude_receipt_object_id: str | None = None,
    ) -> list[str]:
        hashes: set[str] = set()
        for row in self.evidence.rows():
            receipt_object_id = row.get("payload", {}).get("receipt_object_id")
            if not isinstance(receipt_object_id, str):
                continue
            if receipt_object_id == exclude_receipt_object_id:
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

    def _durable_global_configuration_hashes(
        self,
        *,
        exclude_receipt_object_id: str | None = None,
    ) -> list[str]:
        hashes: set[str] = set()
        for row in self.evidence.rows():
            receipt_object_id = row.get("payload", {}).get("receipt_object_id")
            if not isinstance(receipt_object_id, str):
                continue
            if receipt_object_id == exclude_receipt_object_id:
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

    def _scientific_project_root(self) -> Path:
        control_path = self.control.path.resolve()
        if (
            control_path.parent.name == "v2"
            and control_path.parent.parent.name == "registries"
        ):
            return control_path.parents[2]
        return control_path.parent

    def _scientific_hypothesis_ledger(self) -> HashChainLedger:
        return HashChainLedger(
            self._scientific_project_root()
            / "registries/v2/scientific/hypothesis_ledger.jsonl",
            "hypothesis",
        )

    def _require_scientific_hypothesis_ledger_binding(
        self, scientific: Mapping[str, Any]
    ) -> None:
        expected = (
            self._scientific_project_root()
            / str(scientific.get("hypothesis_ledger_path"))
        ).resolve()
        if self.hypotheses.path != expected:
            raise OperationStateError(
                "writer hypothesis ledger differs from the bound scientific index"
            )

    def _load_scientific_seed_binding(self) -> dict[str, Any]:
        import yaml

        root = self._scientific_project_root().resolve()
        index_relative = "registries/v2/scientific/index.yaml"
        map_relative = "registries/v2/scientific/research_map.yaml"
        payloads: dict[str, Any] = {}
        hashes: dict[str, str] = {}
        for label, relative in (("index", index_relative), ("map", map_relative)):
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                raise OperationStateError(f"scientific {label} seed is missing")
            raw = path.read_bytes()
            try:
                payload = yaml.safe_load(raw.decode("ascii"))
            except (UnicodeError, yaml.YAMLError) as exc:
                raise OperationStateError(
                    f"scientific {label} seed is not valid ASCII YAML: {exc}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise OperationStateError(
                    f"scientific {label} seed must be a mapping"
                )
            payloads[label] = dict(payload)
            hashes[label] = hashlib.sha256(raw).hexdigest()
        index = payloads["index"]
        research_map_seed = payloads["map"]
        expected_index_keys = {
            "schema",
            "status",
            "encoding",
            "role",
            "scientific_origin",
            "active_index_path",
            "research_map_seed_path",
            "research_map_seed_sha256",
            "durable_sources",
            "reference_fields",
            "mutable_scientific_content_allowed",
        }
        expected_map_keys = {
            "schema",
            "status",
            "encoding",
            "scientific_origin",
            "dimensions",
            "allowed_states",
            "axis_id_template",
            "initial_state",
            "mutable_scientific_content_allowed",
        }
        if set(index) != expected_index_keys or set(research_map_seed) != expected_map_keys:
            raise OperationStateError("scientific seed fields differ from the immutable schema")
        expected_sources = {
            "hypothesis": "registries/v2/scientific/hypothesis_ledger.jsonl",
            "trial": "registries/v2/evidence_ledger.jsonl",
            "negative_memory": "registries/v2/scientific/hypothesis_ledger.jsonl",
            "ingredient": "registries/v2/material_ledger.jsonl",
            "candidate": "registries/v2/evidence_ledger.jsonl",
            "objects": "registries/v2/objects",
        }
        expected_references = {
            "hypotheses": "hypothesis_object_ids",
            "trials": "trial_receipt_ids",
            "negative_memories": "negative_memory_object_ids",
            "ingredients": "ingredient_object_ids",
            "candidates": "candidate_object_ids",
        }
        from axiom_rift.v2.research.autonomy import (
            GENERIC_DIMENSIONS,
            RESEARCH_STATES,
            assert_no_scientific_inheritance,
        )

        if (
            index.get("schema") != "axiom_rift_v2_scientific_index_seed_v1"
            or index.get("status") != "immutable_seed"
            or index.get("encoding") != "ascii_only"
            or index.get("role") != "active_index_bootstrap_manifest"
            or index.get("scientific_origin") != "v2_current"
            or index.get("active_index_path")
            != "registries/v2/control_state.yaml"
            or index.get("research_map_seed_path") != map_relative
            or index.get("research_map_seed_sha256") != hashes["map"]
            or index.get("durable_sources") != expected_sources
            or index.get("reference_fields") != expected_references
            or index.get("mutable_scientific_content_allowed") is not False
            or research_map_seed.get("schema")
            != "axiom_rift_v2_research_map_seed_v1"
            or research_map_seed.get("status") != "immutable_seed"
            or research_map_seed.get("encoding") != "ascii_only"
            or research_map_seed.get("scientific_origin") != "v2_current"
            or research_map_seed.get("dimensions") != list(GENERIC_DIMENSIONS)
            or research_map_seed.get("allowed_states") != list(RESEARCH_STATES)
            or research_map_seed.get("axis_id_template") != "axis_{dimension}"
            or research_map_seed.get("initial_state") != "unseen"
            or research_map_seed.get("mutable_scientific_content_allowed") is not False
        ):
            raise OperationStateError("scientific seed content is invalid")
        try:
            assert_no_scientific_inheritance(index)
            assert_no_scientific_inheritance(research_map_seed)
        except ValueError as exc:
            raise OperationStateError(
                f"scientific seed inheritance guard failed: {exc}"
            ) from exc
        return {
            "seed_manifest_path": index_relative,
            "seed_manifest_sha256": hashes["index"],
            "research_map_seed_path": map_relative,
            "research_map_seed_sha256": hashes["map"],
        }

    @staticmethod
    def _scientific_references(scientific: Mapping[str, Any]) -> dict[str, list[str]]:
        return {
            field: list(scientific.get(field, []))
            for field in (
                "hypothesis_object_ids",
                "trial_receipt_ids",
                "negative_memory_object_ids",
                "ingredient_object_ids",
                "candidate_object_ids",
            )
        }

    def _put_research_map_snapshot(
        self,
        *,
        state: Mapping[str, Any],
        research_map: Any,
        snapshot_seq: int,
        parent_object_id: str | None,
        trigger: Mapping[str, Any],
        references: Mapping[str, list[str]],
        recent_dominant_axes: Iterable[str] = (),
        binding: Mapping[str, str] | None = None,
        root_mission_id: str | None = None,
        goal_id: str | None = None,
        scientific_epoch_id: str | None = None,
    ) -> str:
        scientific = state["scientific"]
        self._require_scientific_hypothesis_ledger_binding(scientific)
        resolved_binding = dict(binding or scientific)
        payload = {
            "schema": "axiom_rift_v2_research_map_snapshot_v1",
            "scientific_origin": "v2_current",
            "root_mission_id": (
                scientific["root_mission_id"]
                if root_mission_id is None
                else root_mission_id
            ),
            "goal_id": (
                state["cursor"].get("active_goal_id")
                if goal_id is None
                else goal_id
            ),
            "scientific_epoch_id": (
                scientific["epoch_id"]
                if scientific_epoch_id is None
                else scientific_epoch_id
            ),
            "seed_manifest_sha256": resolved_binding["seed_manifest_sha256"],
            "research_map_seed_sha256": resolved_binding[
                "research_map_seed_sha256"
            ],
            "snapshot_seq": snapshot_seq,
            "parent_research_map_object_id": parent_object_id,
            "trigger": dict(trigger),
            "axes": research_map.to_payload()["axes"],
            "recent_dominant_axes": list(recent_dominant_axes)[-5:],
            "references": {key: list(value) for key, value in references.items()},
        }
        return self.objects.put("research_map_snapshot", payload)

    def _active_scientific_hypothesis_context(
        self,
        state: Mapping[str, Any],
    ) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
        research_map, map_snapshot = self._load_bound_research_map(state)
        scientific = state["scientific"]
        self._require_scientific_hypothesis_ledger_binding(scientific)
        hypothesis_id = state["cursor"].get("active_hypothesis_id")
        if not isinstance(hypothesis_id, str):
            raise OperationStateError("active scientific hypothesis is missing")
        hypothesis_row = next(
            (
                row
                for row in self.hypotheses.rows()
                if row.get("record_id") == hypothesis_id
                and row.get("record_type") == "hypothesis_preregistered"
            ),
            None,
        )
        if hypothesis_row is None:
            raise OperationStateError("active scientific hypothesis ledger row is missing")
        ledger_payload = hypothesis_row.get("payload")
        if not isinstance(ledger_payload, dict):
            raise OperationStateError("active scientific hypothesis ledger payload is invalid")
        hypothesis_object_id = ledger_payload.get("hypothesis_object_id")
        dominant_axis = ledger_payload.get("dominant_axis")
        if (
            ledger_payload.get("scientific_origin") != "v2_current"
            or ledger_payload.get("scientific_epoch_id") != scientific.get("epoch_id")
            or ledger_payload.get("hypothesis_id") != hypothesis_id
            or not isinstance(hypothesis_object_id, str)
            or hypothesis_object_id
            not in scientific.get("hypothesis_object_ids", [])
            or state.get("claim", {}).get("identity_bundle_object_id")
            != hypothesis_object_id
            or not isinstance(dominant_axis, str)
            or dominant_axis not in research_map.axes
        ):
            raise OperationStateError(
                "active scientific hypothesis does not reconcile with the bound index"
            )
        wrapped = self.objects.get(hypothesis_object_id)
        spec_payload = wrapped.get("payload")
        if wrapped.get("kind") != "hypothesis_spec" or not isinstance(
            spec_payload, dict
        ):
            raise OperationStateError("active scientific hypothesis object is invalid")
        return research_map, map_snapshot, ledger_payload, spec_payload

    @staticmethod
    def _scientific_tested_context(receipt: Mapping[str, Any]) -> dict[str, str]:
        bundle_hashes = receipt.get("bundle_role_hashes")
        programs = receipt.get("programs")
        anchors = receipt.get("scout_anchor_ids")
        if not isinstance(bundle_hashes, Mapping) or not isinstance(programs, Mapping):
            raise OperationStateError("scientific receipt lacks tested-context identities")
        trade_programs = {
            role: role_programs.get("trade")
            for role, role_programs in sorted(programs.items())
            if isinstance(role_programs, Mapping)
        }
        if len(trade_programs) != len(programs):
            raise OperationStateError("scientific receipt trade-program context is incomplete")
        return {
            "program_bundle_sha256": sha256_payload(dict(sorted(bundle_hashes.items()))),
            "data_identity_sha256": str(receipt.get("dataset_sha256")),
            "split_identity_sha256": sha256_payload(
                {
                    "split_source_sha256": receipt.get("split_source_sha256"),
                    "boundary_source_sha256": receipt.get("boundary_source_sha256"),
                    "scout_anchor_ids": anchors,
                }
            ),
            "cost_identity_sha256": sha256_payload(trade_programs),
            "direction_context": "program_bundle_bound",
            "session_context": "dataset_bound",
            "regime_context": "dataset_bound",
            "lifecycle_context": "trade_program_bound",
        }

    def _validate_scientific_scheduler_audit(
        self,
        *,
        state: Mapping[str, Any],
        spec_payload: Mapping[str, Any],
        research_map: Any,
        map_snapshot: Mapping[str, Any],
        scientific_batch: Any,
        initial_configuration_hashes: Iterable[str],
    ) -> dict[str, str]:
        audit = spec_payload.get("scheduler_audit")
        expected_fields = {
            "schema",
            "scientific_epoch_id",
            "research_map_object_id",
            "research_map_snapshot_seq",
            "evaluated_executable_hashes",
            "seen_semantic_signatures",
            "scientific_references",
            "recent_dominant_axes",
            "semantic_definition",
            "proposals",
            "decision",
        }
        if not isinstance(audit, Mapping) or set(audit) != expected_fields:
            raise OperationStateError("scientific scheduler audit fields are incomplete")
        scientific = state["scientific"]
        references = map_snapshot.get("references")
        if not isinstance(references, Mapping):
            raise OperationStateError(
                "scientific scheduler research-map references are invalid"
            )
        references = {key: list(value) for key, value in references.items()}
        durable_global = self._durable_global_configuration_hashes()
        visible_hypothesis_objects = set(references["hypothesis_object_ids"])
        seen_signatures = sorted(
            {
                row.get("payload", {}).get("semantic_signature_sha256")
                for row in self.hypotheses.rows()
                if isinstance(
                    row.get("payload", {}).get("semantic_signature_sha256"), str
                )
                and row.get("payload", {}).get("hypothesis_object_id")
                in visible_hypothesis_objects
            }
        )
        recent_axes = list(map_snapshot.get("recent_dominant_axes", []))
        semantic_definition = audit.get("semantic_definition")
        if (
            audit.get("schema") != "axiom_rift_v2_scheduler_audit_v1"
            or audit.get("scientific_epoch_id") != scientific.get("epoch_id")
            or audit.get("research_map_object_id")
            != scientific.get("current_research_map_object_id")
            or audit.get("research_map_snapshot_seq")
            != scientific.get("research_map_snapshot_seq")
            or audit.get("evaluated_executable_hashes") != durable_global
            or audit.get("seen_semantic_signatures") != seen_signatures
            or audit.get("scientific_references") != references
            or audit.get("recent_dominant_axes") != recent_axes
            or not isinstance(semantic_definition, Mapping)
            or sha256_payload(semantic_definition)
            != scientific_batch.semantic_signature_sha256
        ):
            raise OperationStateError(
                "scientific scheduler audit differs from durable scheduler inputs"
            )
        proposal_rows = audit.get("proposals")
        if not isinstance(proposal_rows, list) or not proposal_rows:
            raise OperationStateError("scientific scheduler proposals are missing")
        expected_proposal_fields = {
            "hypothesis_id",
            "family_id",
            "dominant_axis",
            "executable_hashes",
            "semantic_signature_sha256",
            "expected_information_value",
            "structural_novelty",
            "complementary_potential",
            "scientific_trial_cost",
            "adjacency_penalty",
            "causal_executable",
            "data_identifiable",
        }
        try:
            from axiom_rift.v2.research.autonomy import (
                SchedulerProposal,
                ScopedNegativeMemory,
                choose_next_hypothesis,
            )

            proposals = []
            for row in proposal_rows:
                if not isinstance(row, Mapping) or set(row) != expected_proposal_fields:
                    raise OperationStateError(
                        "scientific scheduler proposal fields are invalid"
                    )
                proposals.append(
                    SchedulerProposal(
                        hypothesis_id=row["hypothesis_id"],
                        family_id=row["family_id"],
                        dominant_axis=row["dominant_axis"],
                        executable_hashes=tuple(row["executable_hashes"]),
                        semantic_signature_sha256=row[
                            "semantic_signature_sha256"
                        ],
                        expected_information_value=row[
                            "expected_information_value"
                        ],
                        structural_novelty=row["structural_novelty"],
                        complementary_potential=row[
                            "complementary_potential"
                        ],
                        scientific_trial_cost=row["scientific_trial_cost"],
                        adjacency_penalty=row["adjacency_penalty"],
                        causal_executable=row["causal_executable"],
                        data_identifiable=row["data_identifiable"],
                    )
                )
            negative_memories = []
            for object_id in references["negative_memory_object_ids"]:
                wrapped = self.objects.get(object_id)
                if wrapped.get("kind") != "negative_memory":
                    raise OperationStateError(
                        "scientific scheduler negative-memory kind is invalid"
                    )
                negative_memories.append(
                    ScopedNegativeMemory.from_payload(wrapped.get("payload"))
                )
            decision = choose_next_hypothesis(
                proposals,
                research_map,
                recent_dominant_axes=tuple(recent_axes),
                evaluated_executable_hashes=frozenset(durable_global),
                seen_semantic_signatures=frozenset(seen_signatures),
                negative_memory=tuple(negative_memories),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationStateError(
                f"scientific scheduler audit is invalid: {exc}"
            ) from exc
        selected = next(
            (
                proposal
                for proposal in proposals
                if proposal.hypothesis_id == decision.selected_hypothesis_id
            ),
            None,
        )
        expected_initial = sorted(set(initial_configuration_hashes))
        if (
            selected is None
            or selected.hypothesis_id != scientific_batch.hypothesis_id
            or selected.family_id != scientific_batch.family_id
            or selected.dominant_axis != scientific_batch.dominant_axis
            or list(selected.executable_hashes) != expected_initial
            or selected.semantic_signature_sha256
            != scientific_batch.semantic_signature_sha256
        ):
            raise OperationStateError(
                "scientific scheduler selection differs from the hypothesis batch"
            )
        candidate_records = [
            {
                "hypothesis_id": row.hypothesis_id,
                "accepted": row.accepted,
                "rejection_codes": list(row.rejection_codes),
                "priority_score": row.priority_score,
                "factors": dict(row.factors),
            }
            for row in decision.candidate_records
        ]
        expected_decision = {
            "schema": "axiom_rift_v2_scheduler_decision_v1",
            "selected_hypothesis_id": decision.selected_hypothesis_id,
            "candidate_records": candidate_records,
            "decision_sha256": decision.decision_sha256,
        }
        if audit.get("decision") != expected_decision:
            raise OperationStateError(
                "scientific scheduler decision does not reproduce exactly"
            )
        return {
            "scheduler_audit_sha256": sha256_payload(audit),
            "scheduler_decision_sha256": decision.decision_sha256,
        }

    @staticmethod
    def _nonregressive_research_state(
        research_map: Any, axis_id: str, proposed: str
    ) -> str:
        depth = {
            "unseen": 0,
            "shallow": 1,
            "contextual": 2,
            "synthesis_ready": 2,
            "deepened": 3,
            "refuted": 4,
        }
        current = research_map.axes[axis_id].state
        return current if depth[current] > depth[proposed] else proposed

    def _load_bound_research_map(
        self,
        state: Mapping[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        scientific = state.get("scientific")
        if (
            not isinstance(scientific, Mapping)
            or scientific.get("binding_schema")
            != "axiom_rift_v2_scientific_index_binding_v1"
        ):
            raise OperationStateError("scientific control-state index is not bound")
        binding = self._load_scientific_seed_binding()
        if any(scientific.get(key) != value for key, value in binding.items()):
            raise OperationStateError("scientific seed binding has drifted")
        object_id = scientific.get("current_research_map_object_id")
        if not isinstance(object_id, str):
            raise OperationStateError("current research map object is missing")
        wrapped = self.objects.get(object_id)
        payload = wrapped.get("payload")
        if wrapped.get("kind") != "research_map_snapshot" or not isinstance(
            payload, dict
        ):
            raise OperationStateError("current research map object kind is invalid")
        expected_payload_fields = {
            "schema",
            "scientific_origin",
            "root_mission_id",
            "goal_id",
            "scientific_epoch_id",
            "seed_manifest_sha256",
            "research_map_seed_sha256",
            "snapshot_seq",
            "parent_research_map_object_id",
            "trigger",
            "axes",
            "recent_dominant_axes",
            "references",
        }
        expected_reference_fields = set(self._scientific_references(scientific))
        if set(payload) != expected_payload_fields or not isinstance(
            payload.get("references"), Mapping
        ) or set(payload["references"]) != expected_reference_fields:
            raise OperationStateError("research map snapshot fields are invalid")
        try:
            from axiom_rift.v2.research.autonomy import (
                ResearchMap,
                assert_no_scientific_inheritance,
            )

            assert_no_scientific_inheritance(payload)
        except ValueError as exc:
            raise OperationStateError(
                f"research map snapshot inheritance guard failed: {exc}"
            ) from exc
        references = self._scientific_references(scientific)
        snapshot_references = payload.get("references")
        references_reconcile = isinstance(snapshot_references, Mapping)
        if references_reconcile:
            for field, current_values in references.items():
                observed_values = snapshot_references.get(field)
                if field == "hypothesis_object_ids":
                    references_reconcile = (
                        isinstance(observed_values, list)
                        and current_values[: len(observed_values)] == observed_values
                    )
                else:
                    references_reconcile = observed_values == current_values
                if not references_reconcile:
                    break
        if (
            payload.get("schema") != "axiom_rift_v2_research_map_snapshot_v1"
            or payload.get("scientific_origin") != "v2_current"
            or payload.get("root_mission_id") != scientific.get("root_mission_id")
            or payload.get("goal_id") != state["cursor"].get("active_goal_id")
            or payload.get("scientific_epoch_id") != scientific.get("epoch_id")
            or payload.get("seed_manifest_sha256")
            != scientific.get("seed_manifest_sha256")
            or payload.get("research_map_seed_sha256")
            != scientific.get("research_map_seed_sha256")
            or payload.get("snapshot_seq")
            != scientific.get("research_map_snapshot_seq")
            or not references_reconcile
        ):
            raise OperationStateError("current research map snapshot does not reconcile")
        recent = payload.get("recent_dominant_axes")
        if (
            not isinstance(recent, list)
            or len(recent) > 5
            or not all(isinstance(value, str) for value in recent)
        ):
            raise OperationStateError("research map recent-axis history is invalid")
        snapshot_seq = payload["snapshot_seq"]
        parent_object_id = payload.get("parent_research_map_object_id")
        if snapshot_seq == 0:
            if parent_object_id is not None:
                raise OperationStateError("initial research map may not have a parent")
        else:
            if not isinstance(parent_object_id, str):
                raise OperationStateError("research map parent object is missing")
            parent = self.objects.get(parent_object_id)
            parent_payload = parent.get("payload")
            if (
                parent.get("kind") != "research_map_snapshot"
                or not isinstance(parent_payload, Mapping)
                or parent_payload.get("scientific_epoch_id")
                != payload.get("scientific_epoch_id")
                or parent_payload.get("root_mission_id")
                != payload.get("root_mission_id")
                or parent_payload.get("snapshot_seq") != snapshot_seq - 1
            ):
                raise OperationStateError("research map parent chain is invalid")

        research_map = ResearchMap.from_payload(
            {
                "schema": "axiom_rift_v2_research_map_v1",
                "scientific_epoch_id": payload.get("scientific_epoch_id"),
                "axes": payload.get("axes"),
            }
        )
        if any(axis_id not in research_map.axes for axis_id in recent):
            raise OperationStateError("research map recent-axis identity is invalid")
        return research_map, payload

    def bind_active_scientific_index(
        self,
        *,
        expected_seed_manifest_sha256: str,
        expected_research_map_seed_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            state = self.control.load()
        except ControlStateError:
            state = self.control.load(allow_legacy_scientific_bind=True)
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        scientific = state.get("scientific")
        if not isinstance(scientific, dict):
            raise OperationStateError("scientific state is missing")
        if scientific.get("binding_schema") is not None:
            raise OperationStateError("scientific index is already bound")
        if (
            state["cursor"].get("active_hypothesis_id") is not None
            or state["cursor"].get("stage") != "idle"
            or state["reentry"].get("active_job") is not None
            or state["holdout"].get("reveal_count") != 0
            or any(self._scientific_references(scientific).values())
            or scientific.get("selected_bundle_id") is not None
        ):
            raise OperationStateError(
                "scientific index bind requires the empty pre-H boundary"
            )
        hypothesis_path = (
            self._scientific_project_root()
            / str(scientific.get("hypothesis_ledger_path"))
        )
        if hypothesis_path.exists() and hypothesis_path.read_bytes().strip():
            raise OperationStateError(
                "scientific index bind requires an empty hypothesis ledger"
            )
        binding = self._load_scientific_seed_binding()
        if (
            binding["seed_manifest_sha256"] != expected_seed_manifest_sha256
            or binding["research_map_seed_sha256"]
            != expected_research_map_seed_sha256
        ):
            raise OperationStateError("scientific seed hashes differ from bind inputs")
        from axiom_rift.v2.research.autonomy import ResearchMap

        research_map = ResearchMap.for_epoch(str(scientific["epoch_id"]))
        references = self._scientific_references(scientific)
        map_object_id = self._put_research_map_snapshot(
            state=state,
            research_map=research_map,
            snapshot_seq=0,
            parent_object_id=None,
            trigger={
                "kind": "epoch_open",
                "hypothesis_id": None,
                "evidence_id": None,
                "negative_memory_object_id": None,
                "ingredient_object_id": None,
            },
            references=references,
            binding=binding,
        )

        def mutate(draft: dict[str, Any]) -> None:
            legacy = draft["scientific"]
            draft["scientific"] = {
                "binding_schema": "axiom_rift_v2_scientific_index_binding_v1",
                "status": "active",
                "root_mission_id": legacy["root_mission_id"],
                "epoch_id": legacy["epoch_id"],
                "active_index_path": "registries/v2/control_state.yaml",
                **binding,
                "current_research_map_object_id": map_object_id,
                "research_map_snapshot_seq": 0,
                "hypothesis_ledger_path": legacy["hypothesis_ledger_path"],
                **references,
                "selected_bundle_id": None,
                "holdout_reveals": 0,
            }
            self._add_authoritative_objects(draft, [map_object_id])
            draft["reentry"]["current_artifact_hashes"][
                "V2_SCIENTIFIC_RESEARCH_MAP"
            ] = map_object_id

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[map_object_id],
            scientific_bind_policy=True,
        )

    def _verified_scientific_artifacts(
        self,
        receipt: Mapping[str, Any],
        required_names: set[str],
    ) -> dict[str, Any]:
        artifacts = receipt["artifacts"]
        project_root = self._scientific_project_root().resolve()
        payloads: dict[str, Any] = {}
        for name in required_names:
            descriptor = artifacts[name]
            relative = Path(descriptor["path"])
            if relative.is_absolute() or ".." in relative.parts or "\\" in descriptor["path"]:
                raise OperationStateError(
                    f"scientific scout artifact path is invalid: {name}"
                )
            resolved = (project_root / relative).resolve()
            if project_root not in resolved.parents or not resolved.is_file():
                raise OperationStateError(
                    f"scientific scout artifact is missing: {name}"
                )
            raw = resolved.read_bytes()
            if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
                raise OperationStateError(
                    f"scientific scout artifact hash differs: {name}"
                )
            if name == "trades":
                continue
            try:
                import json

                payloads[name] = json.loads(raw.decode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise OperationStateError(
                    f"scientific scout artifact is not valid ASCII JSON: {name}"
                ) from exc
        return payloads

    def _scientific_receipt_evaluation_profile(
        self,
        receipt: Mapping[str, Any],
    ) -> Any | None:
        """Resolve the immutable preregistered KPI profile without live-registry replay."""

        rows = [
            row
            for row in self._scientific_hypothesis_ledger().rows()
            if row.get("record_type") == "hypothesis_preregistered"
            and row.get("record_id") == receipt.get("hypothesis_id")
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise OperationStateError(
                "scientific scout hypothesis profile binding is ambiguous"
            )
        object_id = rows[0].get("payload", {}).get("hypothesis_object_id")
        if not isinstance(object_id, str):
            raise OperationStateError(
                "scientific scout hypothesis profile object is missing"
            )
        wrapped = self.objects.get(object_id)
        spec_payload = wrapped.get("payload")
        if (
            wrapped.get("kind") != "hypothesis_spec"
            or not isinstance(spec_payload, Mapping)
            or sha256_payload(spec_payload) != receipt.get("spec_payload_sha256")
        ):
            raise OperationStateError(
                "scientific scout hypothesis profile binding differs"
            )
        acceptance = spec_payload.get("acceptance_profile")
        if not isinstance(acceptance, Mapping):
            raise OperationStateError(
                "scientific scout acceptance profile is missing"
            )
        try:
            from axiom_rift.v2.research.scout import load_evaluation_profile

            return load_evaluation_profile(acceptance)
        except (ImportError, ValueError) as exc:
            raise OperationStateError(
                f"scientific scout acceptance profile is invalid: {exc}"
            ) from exc

    def _replay_scientific_kpi_evaluation(
        self,
        *,
        metrics: Mapping[str, Any],
        causal: Mapping[str, Any],
        trade_implementation_key: str,
        evaluation_profile: Any | None,
    ) -> str | None:
        """Reconcile a declared KPI route against frozen rules and aggregate inputs."""

        kpi = metrics.get("kpi_evaluation")
        kpi_route = kpi.get("route") if isinstance(kpi, Mapping) else None
        if isinstance(kpi, Mapping):
            if (
                kpi.get("schema") != "axiom_rift_v2_kpi_evaluation_v1"
                or kpi.get("stage") != "S"
                or kpi_route
                not in {"route_to_R", "scientific_reject", "evidence_gap", "repair_required"}
                or causal.get("kpi_route") != kpi_route
                or causal.get("hard_profile_passed")
                is not (kpi_route == "route_to_R")
            ):
                raise OperationStateError(
                    "scientific scout KPI route does not reconcile"
                )
        elif evaluation_profile is not None:
            raise OperationStateError("scientific scout KPI evaluation is missing")
        if evaluation_profile is not None:
            try:
                from axiom_rift.v2.research.evaluation import interpret_kpis
                from axiom_rift.v2.research.scientific_scout import (
                    scientific_kpi_observations,
                )

                expected_kpi = interpret_kpis(
                    "S",
                    scientific_kpi_observations(
                        metrics,
                        causal_checks_passed=(
                            causal.get("all_role_checks_passed") is True
                        ),
                        trade_implementation_key=trade_implementation_key,
                    ),
                    evaluation_profile,
                ).to_payload()
            except (ImportError, ValueError) as exc:
                raise OperationStateError(
                    f"scientific scout KPI replay failed: {exc}"
                ) from exc
            if dict(kpi) != expected_kpi:
                raise OperationStateError(
                    "scientific scout KPI evaluation differs from preregistration"
                )
        return kpi_route

    def _validate_scientific_scout_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        state: Mapping[str, Any] | None = None,
        exclude_receipt_object_id: str | None = None,
    ) -> None:
        """Validate a scientific S receipt, including a valid empty-path rejection."""

        if receipt.get("schema") != "axiom_rift_v2_scientific_scout_receipt_v1":
            return
        roles = (
            "continuation_low",
            "continuation_base",
            "continuation_high",
            "failed_break_reversal",
            "compression_ablation",
        )
        anchors = ("V2D002", "V2D005", "V2D008")
        if (
            receipt.get("stage") != "S"
            or receipt.get("scientific_programs") is not True
            or receipt.get("nested_selection") is not True
            or receipt.get("selection_source_data_role") != "validation_oos"
            or receipt.get("development_paths_per_fold") != 1
            or receipt.get("development_variant_selection") is not False
        ):
            raise OperationStateError("scientific scout receipt policy is invalid")
        if (
            receipt.get("claim_ceiling") != "diagnostic_observation"
            or receipt.get("economics_claim_allowed") is not False
            or receipt.get("mt5_executed") is not False
            or receipt.get("isolated_nine_fold_executed") is not False
        ):
            raise OperationStateError("scientific scout receipt exceeds the S claim boundary")
        if receipt.get("scout_anchor_ids") != list(anchors):
            raise OperationStateError("scientific scout anchors differ from the frozen set")
        for field in (
            "selection_rule_sha256",
            "result_sha256",
            "spec_sha256",
            "spec_payload_sha256",
            "program_registry_sha256",
            "runtime_sha256",
            "runtime_executable_sha256",
            "dataset_sha256",
            "split_source_sha256",
            "boundary_source_sha256",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field, ""))) is None:
                raise OperationStateError(f"scientific scout receipt has invalid {field}")
        registry_path = receipt.get("program_registry_path")
        if (
            not isinstance(registry_path, str)
            or not registry_path
            or "\\" in registry_path
            or registry_path.startswith("/")
            or ".." in Path(registry_path).parts
        ):
            raise OperationStateError("scientific scout registry path is invalid")
        bundle_hashes = receipt.get("bundle_role_hashes")
        release_hashes = receipt.get("release_configuration_hashes")
        programs = receipt.get("programs")
        if (
            not isinstance(bundle_hashes, Mapping)
            or set(bundle_hashes) != set(roles)
            or not all(
                re.fullmatch(r"[0-9a-f]{64}", str(value))
                for value in bundle_hashes.values()
            )
            or len(set(bundle_hashes.values())) != len(roles)
            or not isinstance(release_hashes, Mapping)
            or set(release_hashes) != set(roles)
            or not all(
                re.fullmatch(r"[0-9a-f]{64}", str(value))
                for value in release_hashes.values()
            )
            or len(set(release_hashes.values())) != len(roles)
            or not isinstance(programs, Mapping)
            or set(programs) != set(roles)
            or any(
                not isinstance(role_programs, Mapping)
                or len(role_programs) != 8
                for role_programs in programs.values()
            )
        ):
            raise OperationStateError("scientific scout program bundle identity is incomplete")
        trade_implementation_keys = {
            role_programs["trade"].get(
                "implementation_key",
                "fixed_6bar_observed_spread_v1",
            )
            for role_programs in programs.values()
            if isinstance(role_programs, Mapping)
            and isinstance(role_programs.get("trade"), Mapping)
        }
        declared_trade_implementation = receipt.get(
            "trade_implementation_key",
            "fixed_6bar_observed_spread_v1",
        )
        if (
            len(trade_implementation_keys) != 1
            or next(iter(trade_implementation_keys))
            != declared_trade_implementation
            or declared_trade_implementation
            not in {
                "fixed_6bar_observed_spread_v1",
                "fixed_6bar_causal_spread_floor_v1",
            }
        ):
            raise OperationStateError(
                "scientific scout trade implementation identity differs"
            )
        selected_roles = receipt.get("selected_roles")
        selected_variants = receipt.get("selected_variant_hashes")
        selected_configurations = receipt.get("selected_configuration_hashes")
        selected_bundles = receipt.get("selected_model_bundle_sha256s")
        selected_paths = receipt.get("selected_path_hashes")
        selected_mappings = (
            selected_roles,
            selected_variants,
            selected_configurations,
            selected_bundles,
            selected_paths,
        )
        if any(not isinstance(mapping, Mapping) for mapping in selected_mappings):
            raise OperationStateError("scientific scout selected-path mappings are missing")
        selected_folds = set(selected_roles)
        if (
            not selected_folds.issubset(anchors)
            or any(set(mapping) != selected_folds for mapping in selected_mappings[1:])
        ):
            raise OperationStateError("scientific scout selected-path folds do not reconcile")
        for fold_id in selected_folds:
            role = selected_roles[fold_id]
            if (
                role not in roles[:3]
                or selected_configurations[fold_id] != bundle_hashes[role]
                or selected_bundles[fold_id] != bundle_hashes[role]
                or selected_variants[fold_id] != release_hashes[role]
                or re.fullmatch(r"[0-9a-f]{64}", str(selected_paths[fold_id])) is None
            ):
                raise OperationStateError("scientific scout selected path is not a frozen continuation")
        artifacts = receipt.get("artifacts")
        required_artifacts = {
            "metrics",
            "models",
            "trades",
            "causal_checks",
            "nested_selection",
            "trial_accounting",
        }
        if not isinstance(artifacts, Mapping) or not required_artifacts.issubset(artifacts):
            raise OperationStateError("scientific scout receipt artifacts are incomplete")
        for name in required_artifacts:
            descriptor = artifacts[name]
            if (
                not isinstance(descriptor, Mapping)
                or not isinstance(descriptor.get("path"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(descriptor.get("sha256", ""))) is None
            ):
                raise OperationStateError(f"scientific scout artifact is invalid: {name}")
        artifact_payloads = self._verified_scientific_artifacts(
            receipt, required_artifacts
        )
        if (
            artifact_payloads["metrics"] != receipt.get("metrics_summary")
            or artifact_payloads["causal_checks"] != receipt.get("causal_summary")
            or artifact_payloads["trial_accounting"] != receipt.get("trial_accounting")
            or artifact_payloads["nested_selection"].get("selection_rule_sha256")
            != receipt.get("selection_rule_sha256")
        ):
            raise OperationStateError("scientific scout artifact payloads do not reconcile")
        models_payload = artifact_payloads["models"]
        if (
            not isinstance(models_payload, Mapping)
            or models_payload.get("program_identities") != programs
            or models_payload.get("bundle_role_hashes") != bundle_hashes
            or models_payload.get("release_configuration_hashes") != release_hashes
            or models_payload.get("runtime_sha256") != receipt.get("runtime_sha256")
            or models_payload.get("runtime_executable_sha256")
            != receipt.get("runtime_executable_sha256")
            or models_payload.get(
                "trade_implementation_key",
                "fixed_6bar_observed_spread_v1",
            )
            != declared_trade_implementation
        ):
            raise OperationStateError("scientific scout model artifact identity differs")
        metrics = receipt.get("metrics_summary")
        causal = receipt.get("causal_summary")
        if not isinstance(metrics, Mapping) or not isinstance(causal, Mapping):
            raise OperationStateError("scientific scout result summaries are missing")
        unknown = metrics.get("unknown_cost_observation_count")
        validation_unknown = metrics.get("validation_unknown_cost_observation_count")
        development_unknown = metrics.get("development_unknown_cost_observation_count")
        if (
            isinstance(unknown, bool)
            or not isinstance(unknown, int)
            or unknown < 0
            or isinstance(validation_unknown, bool)
            or not isinstance(validation_unknown, int)
            or validation_unknown < 0
            or isinstance(development_unknown, bool)
            or not isinstance(development_unknown, int)
            or development_unknown < 0
            or unknown != validation_unknown + development_unknown
        ):
            raise OperationStateError("scientific scout unknown-cost accounting is invalid")
        causal_passed = causal.get("all_role_checks_passed") is True
        evaluation_profile = self._scientific_receipt_evaluation_profile(receipt)
        kpi_route = self._replay_scientific_kpi_evaluation(
            metrics=metrics,
            causal=causal,
            trade_implementation_key=declared_trade_implementation,
            evaluation_profile=evaluation_profile,
        )

        selection_payload = artifact_payloads["nested_selection"]
        validation_evaluations = selection_payload.get("validation_evaluations")
        development_evaluations = selection_payload.get("development_evaluations")
        selection_rows = selection_payload.get("selections")
        if evaluation_profile is not None:
            if (
                not isinstance(validation_evaluations, list)
                or len(validation_evaluations) != 15
                or not isinstance(development_evaluations, list)
                or len(development_evaluations) != len(selected_folds)
                or not isinstance(selection_rows, list)
                or len(selection_rows) != 3
            ):
                raise OperationStateError(
                    "scientific scout nested evaluation counts do not reconcile"
                )
            evaluation_rows = (*validation_evaluations, *development_evaluations)
            if any(
                not isinstance(row, Mapping)
                or not isinstance(row.get("metrics"), Mapping)
                for row in evaluation_rows
            ):
                raise OperationStateError(
                    "scientific scout nested evaluation metrics are missing"
                )
            validation_metrics = [row["metrics"] for row in validation_evaluations]
            development_metrics = [row["metrics"] for row in development_evaluations]

            def nonnegative_integer(value: Any) -> bool:
                return (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                )

            nested_unknown_values = [
                row.get("unknown_cost_observation_count")
                for row in (*validation_metrics, *development_metrics)
            ]
            if not all(nonnegative_integer(value) for value in nested_unknown_values):
                raise OperationStateError(
                    "scientific scout nested unknown-cost accounting is invalid"
                )
            if (
                validation_unknown
                != sum(
                    int(row["unknown_cost_observation_count"])
                    for row in validation_metrics
                )
                or development_unknown
                != sum(
                    int(row["unknown_cost_observation_count"])
                    for row in development_metrics
                )
            ):
                raise OperationStateError(
                    "scientific scout nested unknown-cost totals differ"
                )
            development_evaluable = [
                row.get("evaluable_trade_count") for row in development_metrics
            ]
            development_net = [
                row.get("net_broker_points") for row in development_metrics
            ]
            if (
                not all(nonnegative_integer(value) for value in development_evaluable)
                or not nonnegative_integer(metrics.get("evaluable_trade_count"))
                or metrics.get("evaluable_trade_count")
                != sum(int(value) for value in development_evaluable)
                or not nonnegative_integer(metrics.get("positive_net_fold_count"))
                or metrics.get("positive_net_fold_count")
                != sum(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and float(value) > 0.0
                    for value in development_net
                )
            ):
                raise OperationStateError(
                    "scientific scout development economics counts differ"
                )
            if unknown == 0:
                if (
                    not all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(float(value))
                        for value in development_net
                    )
                    or not isinstance(metrics.get("net_broker_points"), (int, float))
                    or isinstance(metrics.get("net_broker_points"), bool)
                    or not math.isfinite(float(metrics["net_broker_points"]))
                    or not math.isclose(
                        float(metrics["net_broker_points"]),
                        sum(float(value) for value in development_net),
                        rel_tol=1e-12,
                        abs_tol=1e-9,
                    )
                ):
                    raise OperationStateError(
                        "scientific scout development net economics differ"
                    )
            elif metrics.get("net_broker_points") is not None:
                raise OperationStateError(
                    "scientific scout unknown costs cannot have aggregate net economics"
                )

            if declared_trade_implementation == "fixed_6bar_causal_spread_floor_v1":
                required_count_metrics = (
                    "shadow_evaluable_trade_count",
                    "shadow_positive_net_fold_count",
                    "validation_zero_decision_spread_rejection_count",
                    "development_zero_decision_spread_rejection_count",
                    "validation_execution_spread_fallback_count",
                    "development_execution_spread_fallback_count",
                )
                if (
                    any(
                        not nonnegative_integer(metrics.get(name))
                        for name in required_count_metrics
                    )
                    or not isinstance(metrics.get("shadow_net_broker_points"), (int, float))
                    or isinstance(metrics.get("shadow_net_broker_points"), bool)
                    or not math.isfinite(float(metrics["shadow_net_broker_points"]))
                    or metrics.get("after_cost_metric_state")
                    != "causal_policy_evaluable"
                ):
                    raise OperationStateError(
                        "scientific scout causal cost metrics are invalid"
                    )
                for row in (*validation_metrics, *development_metrics):
                    if (
                        not nonnegative_integer(
                            row.get("shadow_evaluable_trade_count")
                        )
                        or not nonnegative_integer(
                            row.get("zero_decision_spread_rejection_count")
                        )
                        or not nonnegative_integer(
                            row.get("execution_spread_fallback_count")
                        )
                        or not isinstance(
                            row.get("shadow_net_broker_points"), (int, float)
                        )
                        or isinstance(row.get("shadow_net_broker_points"), bool)
                        or not math.isfinite(
                            float(row["shadow_net_broker_points"])
                        )
                        or row.get("after_cost_metric_state")
                        != "causal_policy_evaluable"
                        or int(row["shadow_evaluable_trade_count"])
                        > int(row.get("evaluable_trade_count", -1))
                    ):
                        raise OperationStateError(
                            "scientific scout nested causal cost metrics are invalid"
                        )
                expected_shadow_count = sum(
                    int(row["shadow_evaluable_trade_count"])
                    for row in development_metrics
                )
                expected_shadow_net = sum(
                    float(row["shadow_net_broker_points"])
                    for row in development_metrics
                )
                expected_shadow_positive = sum(
                    float(row["shadow_net_broker_points"]) > 0.0
                    for row in development_metrics
                )
                causal_count_expectations = {
                    "shadow_evaluable_trade_count": expected_shadow_count,
                    "shadow_positive_net_fold_count": expected_shadow_positive,
                    "validation_zero_decision_spread_rejection_count": sum(
                        int(row["zero_decision_spread_rejection_count"])
                        for row in validation_metrics
                    ),
                    "development_zero_decision_spread_rejection_count": sum(
                        int(row["zero_decision_spread_rejection_count"])
                        for row in development_metrics
                    ),
                    "validation_execution_spread_fallback_count": sum(
                        int(row["execution_spread_fallback_count"])
                        for row in validation_metrics
                    ),
                    "development_execution_spread_fallback_count": sum(
                        int(row["execution_spread_fallback_count"])
                        for row in development_metrics
                    ),
                }
                if any(
                    metrics.get(name) != value
                    for name, value in causal_count_expectations.items()
                ) or not math.isclose(
                    float(metrics["shadow_net_broker_points"]),
                    expected_shadow_net,
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                ):
                    raise OperationStateError(
                        "scientific scout causal shadow totals do not reconcile"
                    )
        elif declared_trade_implementation == "fixed_6bar_causal_spread_floor_v1":
            raise OperationStateError(
                "scientific scout causal receipt lacks a preregistered profile"
            )

        outcome = receipt.get("outcome")
        gate_passed = receipt.get("gate_passed")
        if outcome == "route_to_R":
            if (
                gate_passed is not True
                or selected_folds != set(anchors)
                or unknown
                or not causal_passed
                or kpi_route not in {None, "route_to_R"}
            ):
                raise OperationStateError("scientific scout R route lacks three evaluable causal paths")
        elif outcome == "scientific_reject":
            if (
                gate_passed is not False
                or unknown
                or not causal_passed
                or kpi_route in {"evidence_gap", "repair_required"}
            ):
                raise OperationStateError("scientific rejection contains a repair-class evidence gap")
        elif outcome == "evidence_gap":
            if (
                gate_passed is not False
                or not causal_passed
                or (
                    kpi_route != "evidence_gap"
                    and not (kpi_route is None and unknown > 0)
                )
            ):
                raise OperationStateError("scientific scout evidence-gap routing is unsupported")
        elif outcome == "repair_required":
            raise OperationStateError(
                "scientific scout repair-required output cannot become hypothesis evidence"
            )
        else:
            raise OperationStateError("scientific scout outcome is invalid")
        accounting = receipt.get("trial_accounting")
        if not isinstance(accounting, Mapping):
            raise OperationStateError("scientific scout trial accounting is missing")
        family_id = accounting.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            raise OperationStateError("scientific scout family identity is missing")
        prior = self._durable_family_configuration_hashes(
            family_id,
            exclude_receipt_object_id=exclude_receipt_object_id,
        )
        global_prior = self._durable_global_configuration_hashes(
            exclude_receipt_object_id=exclude_receipt_object_id,
        )
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
        expected_current = sorted(bundle_hashes.values())
        expected_after = sorted(set(prior) | set(current))
        expected_global_after = sorted(set(global_prior) | set(current))
        if current != expected_current:
            raise OperationStateError("scientific scout trials differ from the registered bundles")
        if declared_prior != prior or after != expected_after:
            raise OperationStateError("scientific scout family trial history differs from durable receipts")
        if declared_global_prior != global_prior or global_after != expected_global_after:
            raise OperationStateError("scientific scout global trial history differs from durable receipts")
        integer_expectations = {
            "configuration_trials": 5,
            "job_unique_configuration_count": 5,
            "new_family_configuration_trials": len(set(current) - set(prior)),
            "validation_evaluation_cells": 15,
            "local_calibration_trials": 0,
            "inner_selection_events": 3,
            "development_selected_paths": len(selected_folds),
            "family_trials_before": len(prior),
            "family_trials_cumulative": len(after),
            "global_trials_before": len(global_prior),
            "global_trials_cumulative": len(global_after),
            "holdout_reveals": 0,
        }
        for field, expected in integer_expectations.items():
            if accounting.get(field) != expected:
                raise OperationStateError(
                    f"scientific scout trial count does not reconcile: {field}"
                )
        if (
            accounting.get("development_variant_selection") is not False
            or accounting.get("trial_accounting_complete") is not True
            or accounting.get("family_history_sha256_before") != sha256_payload(prior)
            or accounting.get("family_history_sha256_after") != sha256_payload(after)
            or accounting.get("global_history_sha256_before") != sha256_payload(global_prior)
            or accounting.get("global_history_sha256_after") != sha256_payload(global_after)
        ):
            raise OperationStateError("scientific scout trial history hashes are invalid")

        result_body = {
            "outcome": outcome,
            "gate_passed": gate_passed,
            "metrics": artifact_payloads["metrics"],
            "causal_checks": artifact_payloads["causal_checks"],
            "validation_evaluations": selection_payload.get(
                "validation_evaluations"
            ),
            "selections": selection_payload.get("selections"),
            "development_evaluations": selection_payload.get(
                "development_evaluations"
            ),
            "selected_path_hashes": dict(selected_paths),
            "trial_accounting": artifact_payloads["trial_accounting"],
            "claim_ceiling": "diagnostic_observation",
            "mt5_executed": False,
            "economics_claim_allowed": False,
        }
        if sha256_payload(result_body) != receipt.get("result_sha256"):
            raise OperationStateError("scientific scout result hash does not reconcile")

        if state is not None:
            active_job = state.get("reentry", {}).get("active_job")
            if not isinstance(active_job, Mapping):
                raise OperationStateError(
                    "scientific scout evidence requires a declared active job"
                )
            spec_object_id = active_job.get("spec_object_id")
            if (
                not isinstance(spec_object_id, str)
                or state.get("claim", {}).get("identity_bundle_object_id")
                != spec_object_id
            ):
                raise OperationStateError(
                    "scientific scout job is not bound to the active hypothesis object"
                )
            spec_object = self.objects.get(spec_object_id)
            if spec_object.get("kind") != "hypothesis_spec":
                raise OperationStateError("scientific scout job spec is not a hypothesis")
            spec_payload = spec_object.get("payload")
            if (
                not isinstance(spec_payload, Mapping)
                or sha256_payload(spec_payload) != receipt.get("spec_payload_sha256")
            ):
                raise OperationStateError("scientific scout spec payload hash differs")
            try:
                from axiom_rift.v2.research.scout import (
                    validate_hypothesis_v2_payload,
                )

                validated = validate_hypothesis_v2_payload(
                    spec_payload,
                    project_root=self._scientific_project_root(),
                )
            except (ImportError, ValueError) as exc:
                raise OperationStateError(
                    f"active scientific hypothesis binding is invalid: {exc}"
                ) from exc
            registry = validated["scientific_program_registry"]
            batch = validated["scientific_bundle_batch"]
            expected_programs = {
                role: {
                    kind: bundle.programs[kind].receipt_identity()
                    for kind in bundle.programs
                }
                for role, bundle in batch.bundles.items()
            }
            trial_plan = validated["trial_plan"]
            spec_data = spec_payload.get("data", {})
            hypothesis_row = next(
                (
                    row
                    for row in self.hypotheses.rows()
                    if row["record_id"] == receipt.get("hypothesis_id")
                ),
                None,
            )
            if (
                receipt.get("program_registry_path") != registry.relative_path
                or receipt.get("program_registry_sha256") != registry.registry_sha256
                or bundle_hashes != dict(batch.bundle_role_hashes)
                or release_hashes
                != dict(validated["release_configuration_hashes"])
                or receipt.get("runtime_sha256") != validated["runtime_sha256"]
                or receipt.get("runtime_executable_sha256")
                != validated["runtime_executable_sha256"]
                or receipt.get("selection_rule_sha256")
                != validated["selection_rule_sha256"]
                or programs != expected_programs
                or accounting.get("family_id") != trial_plan.get("family_id")
                or accounting.get("family_configuration_hashes_before")
                != trial_plan.get("family_configuration_hashes_before")
                or accounting.get("global_configuration_hashes_before")
                != trial_plan.get("global_configuration_hashes_before")
                or receipt.get("scout_anchor_ids")
                != spec_data.get("scout_anchor_ids")
                or receipt.get("dataset_path")
                != spec_data.get("dataset", {}).get("path")
                or receipt.get("dataset_sha256")
                != spec_data.get("dataset", {}).get("sha256")
                or receipt.get("split_source_path")
                != spec_data.get("split_source", {}).get("path")
                or receipt.get("split_source_sha256")
                != spec_data.get("split_source", {}).get("sha256")
                or receipt.get("boundary_source_path")
                != spec_data.get("boundary_source", {}).get("path")
                or receipt.get("boundary_source_sha256")
                != spec_data.get("boundary_source", {}).get("sha256")
                or hypothesis_row is None
                or receipt.get("spec_path")
                != hypothesis_row["payload"].get("spec_path")
                or receipt.get("spec_sha256")
                != hypothesis_row["payload"].get("spec_sha256")
            ):
                raise OperationStateError(
                    "scientific scout receipt differs from the active hypothesis"
                )

    def validate_recorded_scientific_scout_receipt(
        self,
        receipt_object_id: str,
    ) -> dict[str, Any]:
        """Revalidate one recorded scout against its pre-append trial history."""

        wrapped = self.objects.get(receipt_object_id)
        receipt = wrapped.get("payload")
        if (
            wrapped.get("kind") != "evidence_receipt"
            or not isinstance(receipt, dict)
            or receipt.get("schema")
            != "axiom_rift_v2_scientific_scout_receipt_v1"
        ):
            raise OperationStateError(
                "recorded scientific scout receipt object is invalid"
            )
        matching_rows = [
            row
            for row in self.evidence.rows()
            if row.get("record_type") == "scientific_scout_completed"
            and row.get("payload", {}).get("receipt_object_id")
            == receipt_object_id
        ]
        if len(matching_rows) != 1:
            raise OperationStateError(
                "recorded scientific scout receipt must have one evidence row"
            )
        self._validate_scientific_scout_receipt(
            receipt,
            exclude_receipt_object_id=receipt_object_id,
        )
        return receipt

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
        scientific_binding: dict[str, Any] | None = None
        if isinstance(scientific, dict) and scientific.get("status") == "not_started":
            if state.get("cursor", {}).get("next_action", {}).get("kind") != "await_new_root_goal":
                raise OperationStateError("empty scientific state is not at its root-goal boundary")
            git_sync = state.get("reentry", {}).get("git_sync")
            checkpoint = self._metadata_checkpoint_probe(
                git_sync if isinstance(git_sync, dict) else {}
            )
            if not checkpoint.ok:
                raise OperationStateError(
                    f"scientific root requires a verified metadata checkpoint: {checkpoint.code}"
                )
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
            scientific_binding = self._load_scientific_seed_binding()
            expected_binding = {
                "binding_schema": "axiom_rift_v2_scientific_index_binding_v1",
                "active_index_path": "registries/v2/control_state.yaml",
                **scientific_binding,
                "hypothesis_ledger_path": (
                    "registries/v2/scientific/hypothesis_ledger.jsonl"
                ),
            }
            if any(scientific.get(key) != value for key, value in expected_binding.items()):
                raise OperationStateError("not-started scientific seed binding has drifted")
            if self._scientific_hypothesis_ledger().rows():
                raise OperationStateError(
                    "future scientific goal requires an empty scientific hypothesis ledger"
                )
            scientific_open = {
                "emergency_hypothesis_ceiling": ceiling,
                "epoch_id": epoch_id,
            }
        allocated, namespace_field, counter = self._allocated_identity(state, "goal", goal_id)
        action = next_action or make_next_action(
            "open_goal",
            goal_id=allocated,
            summary=f"open created scientific goal {allocated}",
        )
        validate_next_action(action)
        payload = {
            "goal_id": allocated,
            "root_mission_id": root_mission["mission_id"],
            "status": "created",
            "goal": goal_payload,
        }
        object_id = self.objects.put("internal_goal", payload)
        research_map_object_id: str | None = None
        if scientific_open is not None:
            from axiom_rift.v2.research.autonomy import ResearchMap

            references = self._scientific_references(scientific)
            research_map_object_id = self._put_research_map_snapshot(
                state=state,
                research_map=ResearchMap.for_epoch(scientific_open["epoch_id"]),
                snapshot_seq=0,
                parent_object_id=None,
                trigger={
                    "kind": "epoch_open",
                    "hypothesis_id": None,
                    "evidence_id": None,
                    "negative_memory_object_id": None,
                    "ingredient_object_id": None,
                },
                references=references,
                binding=scientific_binding,
                root_mission_id=root_mission["mission_id"],
                goal_id=allocated,
                scientific_epoch_id=scientific_open["epoch_id"],
            )
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
                        "current_research_map_object_id": research_map_object_id,
                        "research_map_snapshot_seq": 0,
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
            authoritative_objects = [object_id]
            if research_map_object_id is not None:
                authoritative_objects.append(research_map_object_id)
            self._add_authoritative_objects(draft, authoritative_objects)
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
            if research_map_object_id is not None:
                reentry["current_artifact_hashes"][
                    "V2_SCIENTIFIC_RESEARCH_MAP"
                ] = research_map_object_id
            reentry["completed_receipt_ids"] = []
            reentry["completed_evidence_ids"] = []
            draft["slice_budget"] = self._new_slice_budget(f"{allocated}_H")

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[
                object_id,
                *(
                    [research_map_object_id]
                    if research_map_object_id is not None
                    else []
                ),
            ],
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
        pending = cursor.get("next_action")
        if (
            not isinstance(pending, dict)
            or pending.get("kind") != "open_goal"
            or pending.get("goal_id") != goal_id
        ):
            raise OperationStateError("open_goal does not match the structured next action")
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

    def record_active_job_failure(
        self,
        *,
        job_id: str,
        failure_id: str,
        failure_code: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Persist an execution failure without treating it as hypothesis evidence."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("active-job failure requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        job = state.get("reentry", {}).get("active_job")
        if (
            not isinstance(job, dict)
            or job.get("job_id") != job_id
            or job.get("status") != "running"
        ):
            raise OperationStateError("only the running active job may record failure")
        if re.fullmatch(r"[a-z][a-z0-9_]*", failure_code) is None:
            raise OperationStateError("active-job failure code is invalid")
        if not isinstance(summary, str) or not summary.strip():
            raise OperationStateError("active-job failure summary is required")
        try:
            summary.encode("ascii")
        except UnicodeEncodeError as exc:
            raise OperationStateError("active-job failure summary must be ASCII") from exc
        occurred = utc_now()
        payload = {
            "schema": "axiom_rift_v2_evidence_job_failure_v1",
            "job_id": job_id,
            "goal_id": job["goal_id"],
            "stage_id": job["stage_id"],
            "kind": job["kind"],
            "spec_object_id": job["spec_object_id"],
            "input_hash": job["input_hash"],
            "failure_code": failure_code,
            "summary": summary,
            "log_path": job["log_path"],
            "failed_at_utc": occurred,
            "scientific_evidence": False,
            "trial_count_delta": 0,
            "claim_ceiling": "none",
        }
        object_id = self.objects.put("evidence_job_failure", payload)
        row = self._append_or_existing(
            self.evidence,
            failure_id,
            "evidence_job_failed",
            {**payload, "failure_object_id": object_id},
            occurred,
        )
        action = make_next_action(
            "repair",
            goal_id=job["goal_id"],
            stage=str(state["cursor"]["stage"]),
            subject_id=job["stage_id"],
            prerequisite_receipt_ids=[failure_id],
            summary=f"repair failed evidence job {job_id}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft_job = draft["reentry"]["active_job"]
            draft_job.update(
                {
                    "status": "failed",
                    "failure_id": failure_id,
                    "failure_object_id": object_id,
                    "failure_code": failure_code,
                    "failed_at_utc": occurred,
                }
            )
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            self._add_authoritative_objects(draft, [object_id])
            draft["reentry"]["current_artifact_hashes"][failure_id] = object_id
            self._set_next_action(draft, action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def resume_active_job_after_repair(
        self,
        *,
        job_id: str,
        repaired_code_sha256: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Resume the same declared input after one bounded implementation repair."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError("active-job resume requires control-state schema v2")
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        job = state.get("reentry", {}).get("active_job")
        if (
            not isinstance(job, dict)
            or job.get("job_id") != job_id
            or job.get("status") not in {"failed", "timed_out"}
        ):
            raise OperationStateError("only a failed active job may resume after repair")
        if re.fullmatch(r"[0-9a-f]{64}", repaired_code_sha256) is None:
            raise OperationStateError("repaired code hash is invalid")
        budget = state.get("slice_budget")
        if not isinstance(budget, dict) or budget.get("repair_remaining") != 0:
            raise OperationStateError("active-job resume requires a consumed repair budget")
        action = make_next_action(
            "record_evidence",
            goal_id=job["goal_id"],
            stage=str(state["cursor"]["stage"]),
            subject_id=job["stage_id"],
            prerequisite_receipt_ids=[job["failure_id"]],
            summary=f"record repaired evidence for {job_id}",
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft_job = draft["reentry"]["active_job"]
            draft_job.update(
                {
                    "status": "running",
                    "started_at_utc": utc_now(),
                    "resumed_after_failure_id": draft_job["failure_id"],
                    "repaired_code_sha256": repaired_code_sha256,
                    "resume_count": int(draft_job.get("resume_count", 0)) + 1,
                }
            )
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
        if self._scientific_hypothesis_ledger().rows():
            raise OperationStateError(
                "reinforcement close requires an empty scientific hypothesis ledger"
            )
        binding = self._load_scientific_seed_binding()
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
                "binding_schema": "axiom_rift_v2_scientific_index_binding_v1",
                "status": "not_started",
                "root_mission_id": None,
                "epoch_id": None,
                "active_index_path": "registries/v2/control_state.yaml",
                **binding,
                "current_research_map_object_id": None,
                "research_map_snapshot_seq": None,
                "hypothesis_ledger_path": (
                    "registries/v2/scientific/hypothesis_ledger.jsonl"
                ),
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
            draft["reentry"]["current_artifact_hashes"].pop(
                "V2_SCIENTIFIC_RESEARCH_MAP", None
            )
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
            pending = state["cursor"].get("next_action")
            if (
                not isinstance(pending, dict)
                or pending.get("kind") != "preregister_hypothesis"
                or pending.get("goal_id") != active_goal_id
            ):
                raise OperationStateError(
                    "hypothesis preregistration does not match the structured next action"
                )
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
            control_path = self.control.path.resolve()
            if (
                control_path.parent.name == "v2"
                and control_path.parent.parent.name == "registries"
            ):
                project_root = control_path.parents[2]
            else:
                project_root = control_path.parent
            try:
                from axiom_rift.v2.research.scout import validate_hypothesis_v2_payload

                validated_hypothesis = validate_hypothesis_v2_payload(
                    spec_payload,
                    project_root=project_root,
                )
            except (ImportError, ValueError) as exc:
                raise OperationStateError(f"hypothesis preregistration is invalid: {exc}") from exc
            scientific = state.get("scientific")
            scientific_batch = None
            scientific_research_map = None
            scientific_scheduler_binding = None
            if isinstance(scientific, dict) and scientific.get("status") == "active":
                if state["cursor"].get("active_hypothesis_id") is not None:
                    raise OperationStateError(
                        "prior scientific hypothesis requires a durable disposition"
                    )
                self._require_scientific_hypothesis_ledger_binding(scientific)
                scientific_research_map, _map_snapshot = (
                    self._load_bound_research_map(state)
                )
                scientific_batch = validated_hypothesis.get("hypothesis_batch")
                if scientific_batch is None:
                    raise OperationStateError(
                        "active scientific preregistration requires an autonomy batch"
                    )
                if spec_payload.get("scientific_origin") != "v2_current":
                    raise OperationStateError("hypothesis scientific origin is invalid")
                if scientific_batch.scientific_epoch_id != scientific.get("epoch_id"):
                    raise OperationStateError("hypothesis epoch differs from active science")
                if scientific_batch.hypothesis_id != hypothesis_id:
                    raise OperationStateError("autonomy batch identity differs from hypothesis")
                if scientific_batch.dominant_axis not in scientific_research_map.axes:
                    raise OperationStateError(
                        "scientific hypothesis dominant axis is absent from the research map"
                    )
                if scientific_batch.hypothesis_type == "synthesis_ablation":
                    parent_ids = set(scientific_batch.parent_evidence_ids)
                    matched_parent_ids: set[str] = set()
                    for ingredient_object_id in scientific.get(
                        "ingredient_object_ids", []
                    ):
                        wrapped_ingredient = self.objects.get(ingredient_object_id)
                        ingredient = wrapped_ingredient.get("payload")
                        if (
                            wrapped_ingredient.get("kind")
                            != "scientific_ingredient"
                            or not isinstance(ingredient, Mapping)
                        ):
                            raise OperationStateError(
                                "scientific ingredient reference is invalid"
                            )
                        if (
                            ingredient.get("scientific_epoch_id")
                            == scientific.get("epoch_id")
                            and ingredient.get("status") == "s_survivor"
                            and ingredient.get("evidence_id") in parent_ids
                        ):
                            matched_parent_ids.add(ingredient["evidence_id"])
                    if matched_parent_ids != parent_ids or len(parent_ids) < 2:
                        raise OperationStateError(
                            "synthesis parents are not durable same-epoch ingredients"
                        )
                raw_path = Path(spec_path)
                if (
                    raw_path.is_absolute()
                    or "\\" in spec_path
                    or ".." in raw_path.parts
                    or not spec_path
                ):
                    raise OperationStateError("scientific hypothesis path must be repo-relative POSIX")
                resolved_spec = (project_root / raw_path).resolve()
                if project_root != resolved_spec.parent and project_root not in resolved_spec.parents:
                    raise OperationStateError("scientific hypothesis path escapes the project root")
                if not resolved_spec.is_file():
                    raise OperationStateError("scientific hypothesis file is missing")
                raw_spec = resolved_spec.read_bytes()
                try:
                    import yaml

                    parsed_spec = yaml.safe_load(raw_spec.decode("ascii"))
                except (UnicodeError, yaml.YAMLError) as exc:
                    raise OperationStateError(
                        f"scientific hypothesis file is not valid ASCII YAML: {exc}"
                    ) from exc
                if parsed_spec != spec_payload:
                    raise OperationStateError(
                        "scientific hypothesis file differs from the writer payload"
                    )
                if hashlib.sha256(raw_spec).hexdigest() != spec_sha256:
                    raise OperationStateError("scientific hypothesis file hash differs")
            acceptance = spec_payload.get("acceptance_profile", {})
            data = spec_payload.get("data", {})
            if acceptance.get("profile_id") != acceptance_profile_id:
                raise OperationStateError("acceptance profile identity differs from writer input")
            if data.get("split_set_id") != split_set_id:
                raise OperationStateError("split-set identity differs from writer input")
            sensitivity_plan = validated_hypothesis["sensitivity_plan"]
            if (
                sensitivity_plan is not None
                and sensitivity_plan.hypothesis_id != hypothesis_id
            ):
                raise OperationStateError("sensitivity plan identity differs from hypothesis")
            if validated_hypothesis.get("scientific_bundle_batch") is not None:
                declared_material_ids = data.get("material_ids")
                if (
                    not isinstance(declared_material_ids, list)
                    or declared_material_ids != sorted(set(material_ids))
                ):
                    raise OperationStateError(
                        "scientific hypothesis material ids differ from writer input"
                    )
                durable_material_ids = {
                    row["record_id"] for row in self.materials.rows()
                }
                if not set(material_ids).issubset(durable_material_ids):
                    raise OperationStateError(
                        "scientific hypothesis references a non-durable material"
                    )
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
            if scientific_batch is not None:
                initial_hashes = set(
                    validated_hypothesis.get("initial_configuration_hashes", [])
                )
                if initial_hashes & set(durable_global_hashes):
                    raise OperationStateError(
                        "scientific hypothesis repeats a globally evaluated configuration"
                    )
                if validated_hypothesis.get("scientific_bundle_batch") is not None:
                    scientific_scheduler_binding = (
                        self._validate_scientific_scheduler_audit(
                            state=state,
                            spec_payload=spec_payload,
                            research_map=scientific_research_map,
                            map_snapshot=_map_snapshot,
                            scientific_batch=scientific_batch,
                            initial_configuration_hashes=initial_hashes,
                        )
                    )
                try:
                    from axiom_rift.v2.research.autonomy import ScopedNegativeMemory

                    for memory_object_id in scientific.get(
                        "negative_memory_object_ids", []
                    ):
                        wrapped_memory = self.objects.get(memory_object_id)
                        if wrapped_memory.get("kind") != "negative_memory":
                            raise OperationStateError(
                                "scientific negative-memory object kind is invalid"
                            )
                        memory = ScopedNegativeMemory.from_payload(
                            wrapped_memory.get("payload")
                        )
                        disposition_row = next(
                            (
                                row
                                for row in self.hypotheses.rows()
                                if row.get("record_type")
                                == "hypothesis_disposition_recorded"
                                and row.get("payload", {}).get(
                                    "negative_memory_object_id"
                                )
                                == memory_object_id
                                and row.get("payload", {}).get(
                                    "scientific_epoch_id"
                                )
                                == scientific.get("epoch_id")
                                and row.get("payload", {}).get("hypothesis_id")
                                == memory.hypothesis_id
                            ),
                            None,
                        )
                        if disposition_row is None:
                            raise OperationStateError(
                                "scientific negative memory lacks a durable disposition"
                            )
                        if memory.blocks(
                            family_id=scientific_batch.family_id,
                            executable_hashes=initial_hashes,
                        ):
                            raise OperationStateError(
                                "scientific hypothesis conflicts with durable negative memory"
                            )
                except ValueError as exc:
                    raise OperationStateError(
                        f"scientific negative memory is invalid: {exc}"
                    ) from exc
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
        if is_v2 and scientific_batch is not None:
            ledger_payload.update(
                {
                    "scientific_origin": "v2_current",
                    "scientific_epoch_id": scientific_batch.scientific_epoch_id,
                    "hypothesis_type": scientific_batch.hypothesis_type,
                    "dominant_axis": scientific_batch.dominant_axis,
                    "scout_mode": scientific_batch.scout_mode,
                    "family_id": scientific_batch.family_id,
                    "semantic_signature_sha256": scientific_batch.semantic_signature_sha256,
                    "bundle_roles": dict(scientific_batch.bundle_roles),
                    "autonomy_batch_sha256": sha256_payload(scientific_batch.to_payload()),
                }
            )
            if scientific_scheduler_binding is not None:
                ledger_payload.update(scientific_scheduler_binding)
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
            scientific_state = draft.get("scientific")
            if (
                is_v2
                and isinstance(scientific_state, dict)
                and scientific_state.get("status") == "active"
            ):
                refs = scientific_state["hypothesis_object_ids"]
                if object_id not in refs:
                    refs.append(object_id)
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
        """Reject the incomplete batch-only path; the full H spec is canonical."""

        raise OperationStateError(
            "batch-only autonomous preregistration is forbidden; "
            "use preregister_hypothesis with one full scientific specification"
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
            self._validate_scientific_scout_receipt(receipt, state=state)
        scientific_receipt = (
            is_v2
            and receipt.get("schema")
            == "axiom_rift_v2_scientific_scout_receipt_v1"
        )
        research_map = None
        map_snapshot: dict[str, Any] | None = None
        scientific_hypothesis: dict[str, Any] | None = None
        if scientific_receipt:
            (
                research_map,
                map_snapshot,
                scientific_hypothesis,
                _scientific_spec,
            ) = self._active_scientific_hypothesis_context(state)
            if scientific_hypothesis.get("family_id") != receipt.get(
                "trial_accounting", {}
            ).get("family_id"):
                raise OperationStateError(
                    "scientific receipt family differs from the active hypothesis"
                )
            if (
                receipt.get("outcome") == "evidence_gap"
                and promote_diagnostic_observation
            ):
                raise OperationStateError(
                    "scientific evidence gaps may not promote a diagnostic claim"
                )
            outcome = receipt.get("outcome")
            if outcome == "scientific_reject" and (
                exact_next_action.get("kind")
                != "record_hypothesis_disposition"
                or exact_next_action.get("stage") != "H"
                or exact_next_action.get("subject_id")
                != receipt.get("hypothesis_id")
                or evidence_id
                not in exact_next_action.get("prerequisite_receipt_ids", [])
            ):
                raise OperationStateError(
                    "scientific rejection must route to durable hypothesis disposition"
                )
            if outcome == "route_to_R" and (
                exact_next_action.get("kind") != "open_stage"
                or exact_next_action.get("stage") != "R"
                or evidence_id
                not in exact_next_action.get("prerequisite_receipt_ids", [])
            ):
                raise OperationStateError(
                    "scientific survivor must route through the R stage gate"
                )
            if outcome == "evidence_gap" and exact_next_action.get("kind") != "repair":
                raise OperationStateError(
                    "scientific evidence gap must route to repair"
                )
        occurred = utc_now()
        object_id = self.objects.put("evidence_receipt", receipt)
        ingredient_object_id: str | None = None
        research_map_object_id: str | None = None
        scientific_references: dict[str, list[str]] | None = None
        scientific_snapshot_seq: int | None = None
        material_row: dict[str, Any] | None = None
        if scientific_receipt:
            scientific = state["scientific"]
            scientific_references = self._scientific_references(scientific)
            if evidence_id in scientific_references["trial_receipt_ids"]:
                raise OperationStateError("scientific trial receipt is already indexed")
            scientific_references["trial_receipt_ids"].append(evidence_id)
            outcome = receipt.get("outcome")
            if outcome == "route_to_R":
                selected_rows = [
                    {
                        "fold_id": fold_id,
                        "role": receipt["selected_roles"][fold_id],
                        "bundle_sha256": receipt[
                            "selected_model_bundle_sha256s"
                        ][fold_id],
                        "configuration_sha256": receipt[
                            "selected_configuration_hashes"
                        ][fold_id],
                        "path_sha256": receipt["selected_path_hashes"][fold_id],
                    }
                    for fold_id in sorted(receipt["selected_roles"])
                ]
                ingredient_payload = {
                    "schema": "axiom_rift_v2_scientific_ingredient_v1",
                    "scientific_origin": "v2_current",
                    "root_mission_id": scientific["root_mission_id"],
                    "goal_id": receipt["goal_id"],
                    "scientific_epoch_id": scientific["epoch_id"],
                    "hypothesis_id": receipt["hypothesis_id"],
                    "evidence_id": evidence_id,
                    "receipt_object_id": object_id,
                    "family_id": scientific_hypothesis["family_id"],
                    "dominant_axis": scientific_hypothesis["dominant_axis"],
                    "source_stage": "S",
                    "status": "s_survivor",
                    "program_bundle_sha256": sha256_payload(
                        dict(sorted(receipt["bundle_role_hashes"].items()))
                    ),
                    "selection_rule_sha256": receipt["selection_rule_sha256"],
                    "selected_paths": selected_rows,
                    "claim_ceiling": "diagnostic_observation",
                }
                ingredient_object_id = self.objects.put(
                    "scientific_ingredient", ingredient_payload
                )
                scientific_references["ingredient_object_ids"].append(
                    ingredient_object_id
                )
                material_row = self._append_or_existing(
                    self.materials,
                    f"{evidence_id}_SCIENTIFIC_INGREDIENT",
                    "scientific_ingredient_recorded",
                    {
                        "goal_id": receipt["goal_id"],
                        "hypothesis_id": receipt["hypothesis_id"],
                        "scientific_epoch_id": scientific["epoch_id"],
                        "evidence_id": evidence_id,
                        "ingredient_object_id": ingredient_object_id,
                        "claim_ceiling": "diagnostic_observation",
                    },
                    occurred,
                )
            updated_map = research_map
            recent_axes = list(map_snapshot.get("recent_dominant_axes", []))
            if outcome in {"scientific_reject", "route_to_R"}:
                updated_map = research_map.with_axis_observation(
                    axis_id=scientific_hypothesis["dominant_axis"],
                    state=self._nonregressive_research_state(
                        research_map,
                        scientific_hypothesis["dominant_axis"],
                        "shallow",
                    ),
                    evidence_id=evidence_id,
                    observation=f"{evidence_id}:{outcome}",
                )
                recent_axes.append(scientific_hypothesis["dominant_axis"])
            scientific_snapshot_seq = scientific["research_map_snapshot_seq"] + 1
            research_map_object_id = self._put_research_map_snapshot(
                state=state,
                research_map=updated_map,
                snapshot_seq=scientific_snapshot_seq,
                parent_object_id=scientific["current_research_map_object_id"],
                trigger={
                    "kind": "scout_evidence_recorded",
                    "hypothesis_id": receipt["hypothesis_id"],
                    "evidence_id": evidence_id,
                    "outcome": outcome,
                    "negative_memory_object_id": None,
                    "ingredient_object_id": ingredient_object_id,
                },
                references=scientific_references,
                recent_dominant_axes=recent_axes,
            )
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
        if scientific_receipt:
            payload.update(
                {
                    "scientific_origin": "v2_current",
                    "scientific_epoch_id": state["scientific"]["epoch_id"],
                    "research_map_object_id": research_map_object_id,
                    "ingredient_object_id": ingredient_object_id,
                }
            )
        row = self._append_or_existing(
            self.evidence,
            evidence_id,
            record_type,
            payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            authoritative_objects = [object_id]
            if ingredient_object_id is not None:
                authoritative_objects.append(ingredient_object_id)
            if research_map_object_id is not None:
                authoritative_objects.append(research_map_object_id)
            self._add_authoritative_objects(draft, authoritative_objects)
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            if material_row is not None:
                draft["ledger_heads"]["material"] = {
                    "ledger_seq": material_row["ledger_seq"],
                    "row_sha256": material_row["row_sha256"],
                }
            completed = draft["reentry"].setdefault("completed_evidence_ids", [])
            if evidence_id not in completed:
                completed.append(evidence_id)
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[evidence_id] = object_id
            if ingredient_object_id is not None:
                hashes[f"{evidence_id}_SCIENTIFIC_INGREDIENT"] = (
                    ingredient_object_id
                )
            if research_map_object_id is not None:
                hashes["V2_SCIENTIFIC_RESEARCH_MAP"] = research_map_object_id
                scientific_state = draft["scientific"]
                scientific_state.update(scientific_references)
                scientific_state["current_research_map_object_id"] = (
                    research_map_object_id
                )
                scientific_state["research_map_snapshot_seq"] = (
                    scientific_snapshot_seq
                )
            if job_matched:
                draft["reentry"]["active_job"] = None
            self._set_next_action(draft, exact_next_action)
            if receipt.get("stage") == str(draft["cursor"].get("stage")):
                draft["cursor"]["stage_status"] = "completed"
                draft["cursor"]["stage_outcome"] = receipt.get("outcome")
            should_promote = promote_diagnostic_observation or (
                scientific_receipt
                and receipt.get("outcome") in {"scientific_reject", "route_to_R"}
            )
            if should_promote and draft["claim"]["current_level"] == "none":
                draft["claim"] = promote_claim(
                    draft["claim"], "diagnostic_observation", [evidence_id]
                )

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[
                object_id,
                *([ingredient_object_id] if ingredient_object_id is not None else []),
                *(
                    [research_map_object_id]
                    if research_map_object_id is not None
                    else []
                ),
            ],
        )

    def record_hypothesis_evidence_gap_disposition(
        self,
        *,
        hypothesis_id: str,
        evidence_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Close an unidentified Scout result without creating negative memory."""

        state = self.control.load()
        if not self._is_v2_state(state):
            raise OperationStateError(
                "scientific evidence-gap disposition requires control-state schema v2"
            )
        if self._already_applied(state, idempotency_key):
            return state
        self._require_reconciled(state)
        validate_identity("hypothesis", hypothesis_id)
        cursor = state.get("cursor", {})
        goal_id = cursor.get("active_goal_id")
        stage_id = cursor.get("stage_id")
        if (
            not isinstance(goal_id, str)
            or cursor.get("goal_status") != "open"
            or cursor.get("active_hypothesis_id") != hypothesis_id
            or cursor.get("stage") != "S"
            or not isinstance(stage_id, str)
            or cursor.get("stage_status") != "completed"
            or cursor.get("stage_outcome") != "evidence_gap"
        ):
            raise OperationStateError(
                "evidence-gap disposition requires the completed active Scout gap"
            )
        if state.get("reentry", {}).get("active_job") is not None:
            raise OperationStateError(
                "evidence-gap disposition requires no active evidence job"
            )
        claim = state.get("claim", {})
        if (
            claim.get("subject_id") != hypothesis_id
            or claim.get("current_level") != "none"
            or claim.get("claim_ceiling") != "none"
            or claim.get("basis_receipt_ids") != []
        ):
            raise OperationStateError(
                "evidence-gap disposition cannot close a promoted hypothesis claim"
            )
        action = cursor.get("next_action")
        if (
            not isinstance(action, Mapping)
            or action.get("kind") != "repair"
            or action.get("goal_id") != goal_id
            or action.get("stage") != "S"
            or action.get("subject_id") != stage_id
            or action.get("prerequisite_receipt_ids") != [evidence_id]
        ):
            raise OperationStateError(
                "evidence-gap disposition requires its exact pending repair action"
            )
        scientific = state.get("scientific")
        if (
            not isinstance(scientific, dict)
            or scientific.get("status") != "active"
            or scientific.get("binding_schema")
            != "axiom_rift_v2_scientific_index_binding_v1"
        ):
            raise OperationStateError(
                "evidence-gap disposition requires the bound active scientific index"
            )
        if (
            evidence_id not in scientific.get("trial_receipt_ids", [])
            or evidence_id
            not in state.get("reentry", {}).get("completed_evidence_ids", [])
        ):
            raise OperationStateError(
                "evidence-gap disposition basis is not a durable scientific trial"
            )
        evidence_row = next(
            (
                row
                for row in self.evidence.rows()
                if row.get("record_id") == evidence_id
            ),
            None,
        )
        evidence_payload = (
            evidence_row.get("payload", {})
            if isinstance(evidence_row, Mapping)
            else {}
        )
        receipt_object_id = evidence_payload.get("receipt_object_id")
        if (
            evidence_row is None
            or evidence_row.get("record_type") != "scientific_scout_completed"
            or evidence_payload.get("goal_id") != goal_id
            or evidence_payload.get("hypothesis_id") != hypothesis_id
            or evidence_payload.get("stage") != "S"
            or evidence_payload.get("stage_id") != stage_id
            or evidence_payload.get("outcome") != "evidence_gap"
            or not isinstance(receipt_object_id, str)
            or state.get("reentry", {})
            .get("current_artifact_hashes", {})
            .get(evidence_id)
            != receipt_object_id
        ):
            raise OperationStateError(
                "evidence-gap disposition basis does not match the active Scout"
            )
        receipt = self.validate_recorded_scientific_scout_receipt(
            receipt_object_id
        )
        metrics = receipt.get("metrics_summary")
        causal = receipt.get("causal_summary")
        unknown_cost = (
            metrics.get("unknown_cost_observation_count")
            if isinstance(metrics, Mapping)
            else None
        )
        kpi = metrics.get("kpi_evaluation") if isinstance(metrics, Mapping) else None
        verdict_rows = (
            kpi.get("metric_verdicts", []) if isinstance(kpi, Mapping) else []
        )
        evidence_gap_metrics = [
            {
                "name": row.get("name"),
                "dimension": row.get("dimension"),
                "status": row.get("status"),
                "reason_code": row.get("reason_code"),
                "value": row.get("value"),
            }
            for row in verdict_rows
            if isinstance(row, Mapping)
            and row.get("failure_effect") == "evidence_gap"
            and row.get("status") in {"fail", "censored", "not_evaluable"}
            and isinstance(row.get("name"), str)
        ]
        if not evidence_gap_metrics and isinstance(unknown_cost, int) and unknown_cost > 0:
            evidence_gap_metrics = [
                {
                    "name": "unknown_cost_observation_count",
                    "dimension": "integrity",
                    "status": "fail",
                    "reason_code": "outside_hard_boundary",
                    "value": unknown_cost,
                }
            ]
        if (
            receipt.get("goal_id") != goal_id
            or receipt.get("hypothesis_id") != hypothesis_id
            or receipt.get("stage") != "S"
            or receipt.get("stage_id") != stage_id
            or receipt.get("outcome") != "evidence_gap"
            or receipt.get("gate_passed") is not False
            or not isinstance(causal, Mapping)
            or causal.get("all_role_checks_passed") is not True
            or isinstance(unknown_cost, bool)
            or not isinstance(unknown_cost, int)
            or unknown_cost < 0
            or not isinstance(kpi, Mapping)
            or kpi.get("route") != "evidence_gap"
            or not evidence_gap_metrics
            or evidence_payload.get("result_sha256")
            != receipt.get("result_sha256")
        ):
            raise OperationStateError(
                "evidence-gap disposition requires a causal unidentified receipt"
            )
        (
            research_map,
            map_snapshot,
            scientific_hypothesis,
            _scientific_spec,
        ) = self._active_scientific_hypothesis_context(state)
        if any(
            evidence_id in axis.evidence_ids
            for axis in research_map.axes.values()
        ):
            raise OperationStateError(
                "evidence-gap trial may not already be a research-axis observation"
            )
        current_map_object_id = scientific.get("current_research_map_object_id")
        current_map_seq = scientific.get("research_map_snapshot_seq")
        gap_payload = {
            "schema": "axiom_rift_v2_scientific_evidence_gap_v1",
            "scientific_origin": "v2_current",
            "root_mission_id": scientific["root_mission_id"],
            "goal_id": goal_id,
            "scientific_epoch_id": scientific["epoch_id"],
            "hypothesis_id": hypothesis_id,
            "family_id": scientific_hypothesis["family_id"],
            "dominant_axis": scientific_hypothesis["dominant_axis"],
            "stage": "S",
            "stage_id": stage_id,
            "evidence_id": evidence_id,
            "receipt_object_id": receipt_object_id,
            "result_sha256": receipt["result_sha256"],
            "outcome": "evidence_gap",
            "disposition": "unidentified",
            "scientific_failure": False,
            "unknown_cost_observation_count": unknown_cost,
            "validation_unknown_cost_observation_count": metrics.get(
                "validation_unknown_cost_observation_count"
            ),
            "development_unknown_cost_observation_count": metrics.get(
                "development_unknown_cost_observation_count"
            ),
            "evidence_gap_metrics": evidence_gap_metrics,
            "unidentified_metric_names": [
                row["name"] for row in evidence_gap_metrics
            ],
            "reason_codes": list(kpi.get("reason_codes", [])),
            "gate_passed": False,
            "causal_checks_passed": True,
            "research_map_object_id": current_map_object_id,
            "research_map_snapshot_seq": current_map_seq,
            "negative_memory_object_id": None,
            "claim_ceiling": "none",
            "next_route": "preregister_distinct_hypothesis",
        }
        gap_object_id = self.objects.put("scientific_evidence_gap", gap_payload)
        disposition_payload = {
            "goal_id": goal_id,
            "hypothesis_id": hypothesis_id,
            "event_type": "disposition_recorded",
            "outcome": "evidence_gap",
            "disposition": "unidentified",
            "scientific_failure": False,
            "evidence_ids": [evidence_id],
            "evidence_gap_object_id": gap_object_id,
            "negative_memory_object_id": None,
            "claim_ceiling": "none",
            "scientific_origin": "v2_current",
            "scientific_epoch_id": scientific["epoch_id"],
            "family_id": scientific_hypothesis["family_id"],
            "dominant_axis": scientific_hypothesis["dominant_axis"],
            "research_map_object_id": current_map_object_id,
            "research_map_snapshot_seq": current_map_seq,
        }
        row = self._append_or_existing(
            self.hypotheses,
            f"{hypothesis_id}_DISPOSITION",
            "hypothesis_disposition_recorded",
            disposition_payload,
            utc_now(),
        )
        next_hypothesis_id = format_identity(
            "hypothesis", state["namespace"]["next_hypothesis"]
        )
        next_action = make_next_action(
            "preregister_hypothesis",
            goal_id=goal_id,
            stage="H",
            subject_id=next_hypothesis_id,
            prerequisite_receipt_ids=[evidence_id],
            summary=(
                "select and preregister a distinct hypothesis after an "
                "unidentified evidence gap"
            ),
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            self._add_authoritative_objects(draft, [gap_object_id])
            draft["reentry"]["current_artifact_hashes"][
                f"{hypothesis_id}_EVIDENCE_GAP"
            ] = gap_object_id
            draft["cursor"].update(
                {
                    "active_hypothesis_id": None,
                    "stage_status": "disposed",
                    "stage_outcome": "evidence_gap",
                }
            )
            self._set_next_action(draft, next_action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[receipt_object_id, gap_object_id],
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
        scientific_disposition = False
        research_map = None
        map_snapshot: dict[str, Any] | None = None
        scientific_hypothesis: dict[str, Any] | None = None
        scientific_references: dict[str, list[str]] | None = None
        scientific_snapshot_seq: int | None = None
        research_map_object_id: str | None = None
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
            scientific = state.get("scientific")
            scientific_disposition = (
                isinstance(scientific, dict)
                and scientific.get("status") == "active"
                and scientific.get("binding_schema")
                == "axiom_rift_v2_scientific_index_binding_v1"
            )
            if scientific_disposition:
                (
                    research_map,
                    map_snapshot,
                    scientific_hypothesis,
                    _scientific_spec,
                ) = self._active_scientific_hypothesis_context(state)
                if outcome != "scientific_reject":
                    raise OperationStateError(
                        "scientific negative memory requires a scientific rejection"
                    )
                if evidence_id not in scientific.get("trial_receipt_ids", []):
                    raise OperationStateError(
                        "scientific disposition evidence is not in durable trial accounting"
                    )
                receipt_object_id = evidence_row["payload"].get(
                    "receipt_object_id"
                )
                wrapped_receipt = self.objects.get(receipt_object_id)
                scientific_receipt = wrapped_receipt.get("payload")
                if (
                    wrapped_receipt.get("kind") != "evidence_receipt"
                    or not isinstance(scientific_receipt, dict)
                    or scientific_receipt.get("schema")
                    != "axiom_rift_v2_scientific_scout_receipt_v1"
                    or scientific_receipt.get("outcome") != "scientific_reject"
                    or scientific_receipt.get("hypothesis_id") != hypothesis_id
                ):
                    raise OperationStateError(
                        "scientific disposition basis is not a rejected Scout receipt"
                    )
                raw_path = Path(memory_path)
                if (
                    raw_path.is_absolute()
                    or "\\" in memory_path
                    or ".." in raw_path.parts
                    or not memory_path
                ):
                    raise OperationStateError(
                        "scientific negative-memory path must be repo-relative POSIX"
                    )
                project_root = self._scientific_project_root().resolve()
                resolved_memory = (project_root / raw_path).resolve()
                if (
                    project_root != resolved_memory.parent
                    and project_root not in resolved_memory.parents
                ):
                    raise OperationStateError(
                        "scientific negative-memory path escapes the project root"
                    )
                if not resolved_memory.is_file():
                    raise OperationStateError(
                        "scientific negative-memory file is missing"
                    )
                raw_memory = resolved_memory.read_bytes()
                try:
                    import yaml

                    parsed_memory = yaml.safe_load(raw_memory.decode("ascii"))
                except (UnicodeError, yaml.YAMLError) as exc:
                    raise OperationStateError(
                        f"scientific negative-memory file is invalid: {exc}"
                    ) from exc
                if parsed_memory != memory_payload:
                    raise OperationStateError(
                        "scientific negative-memory file differs from the writer payload"
                    )
                if hashlib.sha256(raw_memory).hexdigest() != memory_sha256:
                    raise OperationStateError(
                        "scientific negative-memory file hash differs"
                    )
                try:
                    from axiom_rift.v2.research.autonomy import ScopedNegativeMemory

                    memory = ScopedNegativeMemory.from_payload(memory_payload)
                except ValueError as exc:
                    raise OperationStateError(
                        f"scientific negative memory is invalid: {exc}"
                    ) from exc
                if memory.to_payload() != memory_payload:
                    raise OperationStateError(
                        "scientific negative-memory payload is not canonical"
                    )
                expected_hashes = sorted(
                    scientific_receipt["trial_accounting"]["configuration_hashes"]
                )
                if (
                    memory.hypothesis_id != hypothesis_id
                    or memory.family_id != scientific_hypothesis.get("family_id")
                    or list(memory.evidence_ids) != [evidence_id]
                    or dict(memory.tested_context)
                    != self._scientific_tested_context(scientific_receipt)
                    or list(memory.do_not_retry_hashes) != expected_hashes
                ):
                    raise OperationStateError(
                        "scientific negative memory differs from its durable evidence"
                    )
                if memory.strength == "family_refuted":
                    durable_context_hashes: set[str] = set()
                    for prior_object_id in scientific.get(
                        "negative_memory_object_ids", []
                    ):
                        prior_wrapped = self.objects.get(prior_object_id)
                        try:
                            prior_memory = ScopedNegativeMemory.from_payload(
                                prior_wrapped.get("payload")
                            )
                        except ValueError as exc:
                            raise OperationStateError(
                                f"durable negative memory is invalid: {exc}"
                            ) from exc
                        if prior_memory.family_id == memory.family_id:
                            durable_context_hashes.add(
                                sha256_payload(dict(prior_memory.tested_context))
                            )
                    identification_row = next(
                        (
                            row
                            for row in self.evidence.rows()
                            if row.get("record_id")
                            == memory.identification_receipt_id
                            and row.get("record_type")
                            == "scientific_identification_impossible"
                            and row.get("payload", {}).get("hypothesis_id")
                            == hypothesis_id
                            and row.get("payload", {}).get("outcome")
                            == "identification_impossible"
                        ),
                        None,
                    )
                    identification_receipt_valid = False
                    if identification_row is not None:
                        identification_object_id = identification_row.get(
                            "payload", {}
                        ).get("receipt_object_id")
                        if isinstance(identification_object_id, str):
                            identification_wrapped = self.objects.get(
                                identification_object_id
                            )
                            identification_payload = identification_wrapped.get(
                                "payload"
                            )
                            identification_receipt_valid = (
                                identification_wrapped.get("kind")
                                == "evidence_receipt"
                                and isinstance(identification_payload, Mapping)
                                and identification_payload.get("schema")
                                == "axiom_rift_v2_scientific_identification_receipt_v1"
                                and identification_payload.get("outcome")
                                == "identification_impossible"
                                and identification_payload.get("hypothesis_id")
                                == hypothesis_id
                            )
                    orthogonal_hashes = set(memory.orthogonal_context_hashes)
                    orthogonal_proven = (
                        len(orthogonal_hashes) >= 2
                        and orthogonal_hashes.issubset(durable_context_hashes)
                    )
                    identification_proven = (
                        memory.identification_impossible
                        and identification_receipt_valid
                    )
                    if not (orthogonal_proven or identification_proven):
                        raise OperationStateError(
                            "family refutation lacks durable orthogonal or identification evidence"
                        )
        elif exact_next_action is None:
            raise TransitionError("schema v1 disposition requires exact_next_action text")
        occurred = utc_now()
        object_id = self.objects.put("negative_memory", memory_payload)
        if scientific_disposition:
            scientific_references = self._scientific_references(state["scientific"])
            if object_id in scientific_references["negative_memory_object_ids"]:
                raise OperationStateError("scientific negative memory is already indexed")
            scientific_references["negative_memory_object_ids"].append(object_id)
            proposed_axis_state = (
                "refuted" if memory.strength == "family_refuted" else "shallow"
            )
            axis_state = self._nonregressive_research_state(
                research_map,
                scientific_hypothesis["dominant_axis"],
                proposed_axis_state,
            )
            updated_map = research_map.with_axis_observation(
                axis_id=scientific_hypothesis["dominant_axis"],
                state=axis_state,
                evidence_id=evidence_id,
                observation=f"{evidence_id}:{outcome}:{memory.strength}",
            )
            recent_axes = list(map_snapshot.get("recent_dominant_axes", []))
            scientific_snapshot_seq = (
                state["scientific"]["research_map_snapshot_seq"] + 1
            )
            research_map_object_id = self._put_research_map_snapshot(
                state=state,
                research_map=updated_map,
                snapshot_seq=scientific_snapshot_seq,
                parent_object_id=state["scientific"][
                    "current_research_map_object_id"
                ],
                trigger={
                    "kind": "hypothesis_disposition_recorded",
                    "hypothesis_id": hypothesis_id,
                    "evidence_id": evidence_id,
                    "outcome": outcome,
                    "negative_memory_object_id": object_id,
                    "ingredient_object_id": None,
                },
                references=scientific_references,
                recent_dominant_axes=recent_axes,
            )
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
        if scientific_disposition:
            payload.update(
                {
                    "scientific_origin": "v2_current",
                    "scientific_epoch_id": state["scientific"]["epoch_id"],
                    "family_id": scientific_hypothesis["family_id"],
                    "dominant_axis": scientific_hypothesis["dominant_axis"],
                    "research_map_object_id": research_map_object_id,
                }
            )
        row = self._append_or_existing(
            self.hypotheses,
            record_id,
            "hypothesis_disposition_recorded",
            payload,
            occurred,
        )
        def mutate(draft: dict[str, Any]) -> None:
            authoritative_objects = [object_id]
            if research_map_object_id is not None:
                authoritative_objects.append(research_map_object_id)
            self._add_authoritative_objects(draft, authoritative_objects)
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            hashes = draft["reentry"].setdefault(
                "current_artifact_hashes" if is_v2 else "artifact_hashes",
                {},
            )
            hashes[f"{hypothesis_id}_negative_memory"] = object_id
            if research_map_object_id is not None:
                hashes["V2_SCIENTIFIC_RESEARCH_MAP"] = research_map_object_id
                scientific_state = draft["scientific"]
                scientific_state.update(scientific_references)
                scientific_state["current_research_map_object_id"] = (
                    research_map_object_id
                )
                scientific_state["research_map_snapshot_seq"] = (
                    scientific_snapshot_seq
                )
                draft["cursor"].update(
                    {
                        "active_hypothesis_id": None,
                        "stage_status": "disposed",
                        "stage_outcome": outcome,
                    }
                )
                draft["claim"] = {
                    "subject_kind": "hypothesis",
                    "subject_id": hypothesis_id,
                    "current_level": "diagnostic_observation",
                    "claim_ceiling": "diagnostic_observation",
                    "identity_bundle_object_id": object_id,
                    "basis_receipt_ids": [evidence_id],
                    "blocked_by": [],
                }
            self._set_next_action(draft, exact_next_action)

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[
                object_id,
                *(
                    [research_map_object_id]
                    if research_map_object_id is not None
                    else []
                ),
            ],
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
