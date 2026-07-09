"""Single-writer orchestration for V2 objects, ledgers, and control state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

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
from axiom_rift.v2.state.transitions import promote_claim, transition_stage


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MaterialRecord:
    material_id: str
    kind: str
    payload: dict[str, Any]


class V2OperationWriter:
    """Own all active V2 state mutations; research functions remain pure."""

    def __init__(self) -> None:
        self.objects = ObjectStore(V2_OBJECT_DIR)
        self.control = ControlStore(V2_CONTROL_STATE, object_store=self.objects)
        self.hypotheses = HashChainLedger(V2_HYPOTHESIS_LEDGER, "hypothesis")
        self.evidence = HashChainLedger(V2_EVIDENCE_LEDGER, "evidence")
        self.materials = HashChainLedger(V2_MATERIAL_LEDGER, "material")
        self.validation_receipts = HashChainLedger(
            V2_VALIDATION_RECEIPT_LEDGER, "validation_receipt"
        )

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
        current = list(state["cursor"].get("authoritative_object_ids", []))
        for object_id in object_ids:
            if object_id not in current:
                current.append(object_id)
        state["cursor"]["authoritative_object_ids"] = current

    def register_material_batch(
        self,
        records: tuple[MaterialRecord, ...],
        *,
        idempotency_key: str,
        exact_next_action: str,
        occurred_at_utc: str | None = None,
    ) -> dict[str, Any]:
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
        state = self.control.load()

        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, object_ids)
            draft["ledger_heads"]["material"] = {
                "ledger_seq": rows[-1]["ledger_seq"],
                "row_sha256": rows[-1]["row_sha256"],
            }
            artifact_hashes = draft["reentry"].setdefault("artifact_hashes", {})
            for record, object_id in zip(records, object_ids, strict=True):
                artifact_hashes[record.material_id] = object_id
            draft["cursor"]["exact_next_action"] = exact_next_action

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=object_ids,
        )

    def preregister_hypothesis(
        self,
        *,
        hypothesis_id: str,
        spec_path: str,
        spec_sha256: str,
        spec_payload: dict[str, Any],
        split_set_id: str,
        material_ids: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if hypothesis_id != "V2H0001":
            raise ValueError("bootstrap writer expects the first V2 hypothesis identity")
        occurred = utc_now()
        object_id = self.objects.put("hypothesis_spec", spec_payload)
        ledger_payload = {
            "goal_id": "V2G0001",
            "hypothesis_id": hypothesis_id,
            "spec_path": spec_path,
            "spec_sha256": spec_sha256,
            "hypothesis_object_id": object_id,
            "origin": "newly_originated_v2",
            "v1_evidence_inherited": False,
            "material_ids": material_ids,
            "split_set_id": split_set_id,
            "acceptance_profile_id": "V2SAP0001",
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
        state = self.control.load()

        def mutate(draft: dict[str, Any]) -> None:
            if draft["namespace"]["next_hypothesis"] != 1:
                raise ValueError("hypothesis namespace does not point to V2H0001")
            draft["namespace"]["next_hypothesis"] = 2
            draft["cursor"] = transition_stage(draft["cursor"], "H", hypothesis_id)
            draft["cursor"]["active_hypothesis_id"] = hypothesis_id
            draft["cursor"]["stage_status"] = "preregistered"
            draft["cursor"]["exact_next_action"] = "open_V2S0001_causal_scout"
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
            draft["reentry"]["active_slice_id"] = "V2SL0005_first_scout"
            draft["reentry"]["artifact_hashes"][hypothesis_id] = object_id

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
        )

    def open_scout(self, *, idempotency_key: str) -> dict[str, Any]:
        state = self.control.load()

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
        exact_next_action: str,
        promote_diagnostic_observation: bool = False,
    ) -> dict[str, Any]:
        occurred = utc_now()
        object_id = self.objects.put("evidence_receipt", receipt)
        payload = {
            "evidence_id": evidence_id,
            "goal_id": receipt.get("goal_id", "V2G0001"),
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
        state = self.control.load()

        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            completed = draft["reentry"].setdefault("completed_evidence_ids", [])
            if evidence_id not in completed:
                completed.append(evidence_id)
            draft["reentry"]["artifact_hashes"][evidence_id] = object_id
            draft["reentry"]["active_job"] = None
            draft["cursor"]["exact_next_action"] = exact_next_action
            if receipt.get("stage") == "S":
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
        exact_next_action: str,
    ) -> dict[str, Any]:
        occurred = utc_now()
        object_id = self.objects.put("negative_memory", memory_payload)
        record_id = f"{hypothesis_id}_DISPOSITION"
        payload = {
            "goal_id": "V2G0001",
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
        state = self.control.load()

        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["hypothesis"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            draft["reentry"]["artifact_hashes"][f"{hypothesis_id}_negative_memory"] = object_id
            draft["cursor"]["exact_next_action"] = exact_next_action

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
        exact_next_action: str,
    ) -> dict[str, Any]:
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
        state = self.control.load()
        validate_stage_basis(
            current_stage=str(state["cursor"]["stage"]),
            new_stage=new_stage,
            new_stage_id=stage_id,
            current_claim=str(state["claim"]["current_level"]),
            basis=receipt,
        )

        def mutate(draft: dict[str, Any]) -> None:
            draft["cursor"] = transition_stage(draft["cursor"], new_stage, stage_id)
            draft["cursor"]["exact_next_action"] = exact_next_action
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
        exact_next_action: str,
    ) -> dict[str, Any]:
        if receipt.get("outcome") not in {"pass", "fail"}:
            raise ValueError("validation receipt outcome must be pass or fail")
        occurred = utc_now()
        object_id = self.objects.put("validation_receipt", receipt)
        payload = {
            "validation_key": receipt["validation_key"],
            "outcome": receipt["outcome"],
            "receipt_object_id": object_id,
            "validator_id": receipt["validator_id"],
            "duration_seconds": receipt["duration_seconds"],
        }
        row = self._append_or_existing(
            self.validation_receipts,
            receipt_id,
            "validation_receipt_recorded",
            payload,
            occurred,
        )
        state = self.control.load()

        def mutate(draft: dict[str, Any]) -> None:
            self._add_authoritative_objects(draft, [object_id])
            draft["ledger_heads"]["validation_receipt"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            completed = draft["reentry"].setdefault("completed_receipt_ids", [])
            if receipt_id not in completed:
                completed.append(receipt_id)
            draft["reentry"]["artifact_hashes"][receipt_id] = object_id
            draft["cursor"]["exact_next_action"] = exact_next_action

        return self.control.commit(
            state["revision"],
            idempotency_key,
            mutate,
            referenced_object_ids=[object_id],
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
