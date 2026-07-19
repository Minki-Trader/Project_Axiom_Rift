"""Holdout seal, reveal, evaluation, and candidate-authority transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import yaml

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    Permit,
    PermitError,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer_support import (
    TransitionError,
    TransitionResult,
    _effective_completion_scope,
    _parse_utc,
    _record,
    _require_ascii,
    _require_digest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class HoldoutWriterMixin:
    """Own holdout access and post-reveal candidate authority transitions."""

    def record_holdout_seal(
        self,
        *,
        manifest: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Register sealed future data by semantic row/split identity without reading it."""

        from axiom_rift.runtime.guards import SealedHoldoutManifest

        if not isinstance(manifest, SealedHoldoutManifest):
            raise TransitionError("holdout seal requires SealedHoldoutManifest")
        artifact = self.evidence.verify(manifest.artifact_sha256)
        if artifact.size_bytes != manifest.size_bytes:
            raise TransitionError("holdout seal size differs from its artifact")
        starts_at = _parse_utc("holdout starts_at_utc", manifest.starts_at_utc)
        ends_at = _parse_utc("holdout ends_at_utc", manifest.ends_at_utc)
        if starts_at > ends_at:
            raise TransitionError("holdout time boundary is reversed")
        holdout_hash = manifest.identity.removeprefix("holdout:")
        _require_digest("holdout identity", holdout_hash)
        row_binding_id = canonical_digest(
            domain="holdout-row-binding", payload={"row_identity": manifest.row_identity}
        )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Foundation is not initialized")
            if index.get("holdout-row-binding", row_binding_id) is not None:
                raise TransitionError(
                    "semantic holdout rows are already sealed under another operation"
                )
            chain_head = index.event_head("holdout-chain")
            chain_latest = (
                None
                if chain_head is None
                else index.get(chain_head.record_kind, chain_head.record_id)
            )
            if chain_head is None:
                if manifest.predecessor_holdout_id is not None:
                    raise TransitionError(
                        "first holdout cannot name a predecessor"
                    )
                try:
                    exposure = yaml.safe_load(
                        (self.foundation_root / "foundation" / "data_exposure.yaml").read_text(
                            encoding="ascii"
                        )
                    )
                    boundary_text = exposure["forward_holdout"]["starts_after"]
                    boundary = datetime.fromisoformat(boundary_text).replace(
                        tzinfo=timezone.utc
                    )
                except (OSError, UnicodeError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
                    raise TransitionError(
                        "Foundation forward-holdout boundary is unavailable"
                    ) from exc
                if starts_at <= boundary:
                    raise TransitionError(
                        "first holdout is not strictly after the Foundation boundary"
                    )
            else:
                if (
                    chain_latest is None
                    or manifest.predecessor_holdout_id != chain_latest.record_id
                ):
                    raise TransitionError(
                        "new holdout must extend the single latest global chain"
                    )
                predecessor = index.get(
                    "holdout-seal", manifest.predecessor_holdout_id
                )
                if predecessor is None:
                    raise TransitionError("holdout predecessor seal is absent")
                reveal_head = index.event_head(
                    f"holdout-reveal:{manifest.predecessor_holdout_id}"
                )
                reveal_latest = (
                    None
                    if reveal_head is None
                    else index.get(reveal_head.record_kind, reveal_head.record_id)
                )
                if (
                    reveal_head is None
                    or reveal_head.sequence != 2
                    or reveal_latest is None
                    or reveal_latest.kind != "holdout-disposition"
                ):
                    raise TransitionError(
                        "new future holdout requires a disposed predecessor"
                    )
                predecessor_end = _parse_utc(
                    "predecessor ends_at_utc", predecessor.payload["ends_at_utc"]
                )
                if starts_at <= predecessor_end:
                    raise TransitionError(
                        "replacement holdout is not genuinely later future data"
                    )
            payload = {
                "artifact_sha256": manifest.artifact_sha256,
                "data_receipt_id": manifest.data_receipt_id,
                "ends_at_utc": manifest.ends_at_utc,
                "predecessor_holdout_id": manifest.predecessor_holdout_id,
                "row_identity": manifest.row_identity,
                "size_bytes": manifest.size_bytes,
                "split_identity": manifest.split_identity,
                "starts_at_utc": manifest.starts_at_utc,
                "value_exposed": False,
            }
            seal = _record(
                kind="holdout-seal",
                record_id=manifest.identity,
                subject=f"Data:{manifest.data_receipt_id}",
                status="sealed_unrevealed",
                fingerprint=holdout_hash,
                payload=payload,
                event_stream="holdout-chain",
                event_sequence=1 if chain_head is None else chain_head.sequence + 1,
            )
            row_binding = _record(
                kind="holdout-row-binding",
                record_id=row_binding_id,
                subject=f"Holdout:{manifest.identity}",
                status="sealed",
                fingerprint=holdout_hash,
                payload={"holdout_id": manifest.identity},
            )
            body = self._body(current)
            if body["next_action"].get("kind") == "await_new_future_holdout_data":
                if (
                    manifest.predecessor_holdout_id
                    != body["next_action"].get("predecessor_holdout_id")
                ):
                    raise TransitionError(
                        "replacement holdout differs from the required predecessor"
                    )
                body["scientific"]["required_future_holdout_id"] = manifest.identity
                body["next_action"] = {
                    "kind": "register_future_development_material",
                    "holdout_id": manifest.identity,
                    "mission_id": body["scientific"]["active_mission"],
                    "predecessor_holdout_id": manifest.predecessor_holdout_id,
                }
            return body, [seal, row_binding], {"holdout_id": manifest.identity}

        return self._commit(
            event_kind="holdout_sealed",
            operation_id=operation_id,
            subject=f"Holdout:{manifest.identity}",
            payload={"holdout_id": manifest.identity},
            prepare=prepare,
        )

    def register_future_development_material(
        self,
        *,
        material_receipt_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Admit new post-reveal development without reading successor values."""

        if self.engineering_fixture:
            raise TransitionError(
                "engineering fixtures cannot register scientific development material"
            )
        _require_digest("material_receipt_hash", material_receipt_hash)
        try:
            receipt = parse_canonical(
                self.evidence.read_verified(material_receipt_hash)
            )
        except ValueError as exc:
            raise TransitionError(
                "future development material receipt is not canonical"
            ) from exc
        required_receipt_fields = {
            "development_ends_at_utc",
            "development_starts_at_utc",
            "material_content_sha256",
            "material_identity",
            "mission_id",
            "predecessor_holdout_id",
            "schema",
            "split_identity",
            "successor_holdout_id",
            "successor_values_exposed",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != required_receipt_fields
            or receipt.get("schema") != "post_holdout_development_material.v1"
            or receipt.get("successor_values_exposed") is not False
        ):
            raise TransitionError(
                "future development material receipt schema is invalid"
            )
        for name in (
            "mission_id",
            "predecessor_holdout_id",
            "successor_holdout_id",
        ):
            _require_ascii(name, receipt[name])
        material_content_sha256 = _require_digest(
            "material_content_sha256", receipt["material_content_sha256"]
        )
        self.evidence.verify(material_content_sha256)
        material_identity = _require_digest(
            "material_identity", receipt["material_identity"]
        )
        split_identity = _require_digest("split_identity", receipt["split_identity"])
        development_start = _parse_utc(
            "development_starts_at_utc", receipt["development_starts_at_utc"]
        )
        development_end = _parse_utc(
            "development_ends_at_utc", receipt["development_ends_at_utc"]
        )
        if development_start > development_end:
            raise TransitionError("future development time boundary is reversed")
        expected_material_identity = canonical_digest(
            domain="post-holdout-development-material",
            payload={
                "development_ends_at_utc": receipt["development_ends_at_utc"],
                "development_starts_at_utc": receipt[
                    "development_starts_at_utc"
                ],
                "material_content_sha256": material_content_sha256,
                "predecessor_holdout_id": receipt["predecessor_holdout_id"],
                "successor_holdout_id": receipt["successor_holdout_id"],
            },
        )
        expected_split_identity = canonical_digest(
            domain="post-holdout-development-split",
            payload={
                "development_ends_at_utc": receipt["development_ends_at_utc"],
                "development_starts_at_utc": receipt[
                    "development_starts_at_utc"
                ],
                "material_identity": expected_material_identity,
                "predecessor_holdout_id": receipt["predecessor_holdout_id"],
                "successor_holdout_id": receipt["successor_holdout_id"],
            },
        )
        if (
            material_identity != expected_material_identity
            or split_identity != expected_split_identity
        ):
            raise TransitionError(
                "future development receipt material identity is invalid"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            mission_id = science["active_mission"]
            next_action = current["next_action"]
            successor_holdout_id = next_action.get("holdout_id")
            predecessor_holdout_id = next_action.get("predecessor_holdout_id")
            if (
                mission_id is None
                or next_action.get("kind")
                != "register_future_development_material"
                or next_action.get("mission_id") != mission_id
                or not isinstance(successor_holdout_id, str)
                or not isinstance(predecessor_holdout_id, str)
                or science.get("required_future_holdout_id")
                != successor_holdout_id
            ):
                raise TransitionError(
                    "future development registration is not the exact successor action"
                )
            if any(
                science[name] is not None
                for name in (
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_executable",
                    "active_release",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "future development registration requires disposed active work"
                )
            if (
                receipt["mission_id"] != mission_id
                or receipt["successor_holdout_id"] != successor_holdout_id
                or receipt["predecessor_holdout_id"] != predecessor_holdout_id
            ):
                raise TransitionError(
                    "future development receipt belongs to another successor boundary"
                )
            successor = index.get("holdout-seal", successor_holdout_id)
            predecessor = index.get("holdout-seal", predecessor_holdout_id)
            predecessor_reveal = index.event_record(
                f"holdout-reveal:{predecessor_holdout_id}", 1
            )
            predecessor_disposition = index.event_record(
                f"holdout-reveal:{predecessor_holdout_id}", 2
            )
            if (
                successor is None
                or successor.status != "sealed_unrevealed"
                or successor.payload.get("predecessor_holdout_id")
                != predecessor_holdout_id
                or index.event_head(f"holdout-reveal:{successor_holdout_id}")
                is not None
                or predecessor is None
                or predecessor_reveal is None
                or predecessor_reveal.kind != "holdout-reveal"
                or predecessor_disposition is None
                or predecessor_disposition.kind != "holdout-disposition"
            ):
                raise TransitionError(
                    "future development registration lacks an untouched successor chain"
                )
            if not predecessor_reveal.subject.startswith("Executable:executable:"):
                raise TransitionError(
                    "predecessor holdout lacks its Executable binding"
                )
            predecessor_executable_id = predecessor_reveal.subject.removeprefix(
                "Executable:"
            )
            predecessor_end = _parse_utc(
                "predecessor ends_at_utc", predecessor.payload["ends_at_utc"]
            )
            successor_start = _parse_utc(
                "successor starts_at_utc", successor.payload["starts_at_utc"]
            )
            if (
                development_start <= predecessor_end
                or development_end >= successor_start
                or material_content_sha256
                in {
                    predecessor.payload["artifact_sha256"],
                    successor.payload["artifact_sha256"],
                }
            ):
                raise TransitionError(
                    "development material is not a distinct post-reveal pre-successor surface"
                )
            receipt_id = canonical_digest(
                domain="post-holdout-development",
                payload={
                    "holdout_id": successor_holdout_id,
                    "material_identity": material_identity,
                    "mission_id": mission_id,
                },
            )
            authority_payload = {
                "holdout_id": successor_holdout_id,
                "material_identity": material_identity,
                "material_content_sha256": material_content_sha256,
                "material_receipt_hash": material_receipt_hash,
                "mission_id": mission_id,
                "predecessor_executable_id": predecessor_executable_id,
                "predecessor_holdout_id": predecessor_holdout_id,
                "split_identity": split_identity,
            }
            authority = _record(
                kind="post-holdout-development",
                record_id=receipt_id,
                subject=f"Material:{material_identity}",
                status="accepted",
                fingerprint=material_receipt_hash,
                payload=authority_payload,
            )
            material = _record(
                kind="development-material",
                record_id=material_identity,
                subject=f"Mission:{mission_id}",
                status="accepted",
                fingerprint=material_receipt_hash,
                payload={
                    **authority_payload,
                    "development_ends_at_utc": receipt[
                        "development_ends_at_utc"
                    ],
                    "development_starts_at_utc": receipt[
                        "development_starts_at_utc"
                    ],
                    "post_holdout_development_id": receipt_id,
                },
            )
            replay_constraints = self._replay_scheduler_constraints(
                index,
                mission_id=mission_id,
            )
            if science["active_initiative"] is None:
                body["next_action"] = {
                    "kind": "open_initiative",
                    "mission_id": mission_id,
                    "post_holdout_development_id": receipt_id,
                }
            else:
                portfolio_head = index.event_head(f"portfolio:{mission_id}")
                snapshot = (
                    None
                    if portfolio_head is None
                    else index.get(
                        portfolio_head.record_kind, portfolio_head.record_id
                    )
                )
                if snapshot is None or snapshot.kind != "portfolio-snapshot":
                    raise TransitionError(
                        "active Initiative lacks its Portfolio reentry boundary"
                    )
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "post_holdout_development_id": receipt_id,
                    "portfolio_snapshot_id": snapshot.record_id,
                }
            if replay_constraints is not None:
                body["next_action"].update(replay_constraints)
            return body, [authority, material], {
                "material_identity": material_identity,
                "post_holdout_development_id": receipt_id,
            }

        return self._commit(
            event_kind="future_development_registered",
            operation_id=operation_id,
            subject=f"Material:{material_identity}",
            payload={
                "material_receipt_hash": material_receipt_hash,
            },
            prepare=prepare,
        )

    def consume_holdout_permit(
        self,
        *,
        permit: Permit,
        executable_id: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("executable_id", executable_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_executable"] != executable_id:
                raise TransitionError("holdout permit is not candidate-executable bound")
            job = science.get("active_job")
            if not isinstance(job, dict) or job.get("status") != "running":
                raise TransitionError(
                    "holdout reveal requires its preregistered running evaluation Job"
                )
            declaration = index.get("job-declared", job["id"])
            holdout_id = f"holdout:{permit.input_hash}"
            if (
                declaration is None
                or declaration.payload["spec"].get("holdout_binding")
                != {"holdout_id": holdout_id}
                or declaration.payload["spec"].get("evidence_subject")
                != {"kind": "Executable", "id": executable_id}
            ):
                raise TransitionError("running Job is not bound to this holdout")
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.HOLDOUT,
                action="reveal_holdout",
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                required_scope=(
                    holdout_id,
                    f"executable:{executable_id}",
                ),
            )
            seal = index.get("holdout-seal", holdout_id)
            if seal is None or seal.status != "sealed_unrevealed":
                raise TransitionError("holdout semantic seal is unavailable")
            self.evidence.verify(seal.payload["artifact_sha256"])
            if index.event_head(f"holdout-reveal:{holdout_id}") is not None:
                raise TransitionError("holdout semantic identity was already revealed")
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            if candidate is None:
                raise TransitionError("holdout candidate activation is unavailable")
            science["holdout_reveals"] += 1
            science["active_holdout_evaluation"] = {
                "holdout_id": holdout_id,
                "candidate_id": candidate.record_id,
                "executable_id": executable_id,
                "job_id": job["id"],
                "status": "revealed_pending_evaluation",
            }
            body["next_action"] = {"kind": "evaluate_frozen_holdout", "executable_id": executable_id}
            consumption = self._permit_consumption_record(permit, operation_id)
            reveal_id = canonical_digest(
                domain="holdout-reveal",
                payload={
                    "candidate_id": candidate.record_id,
                    "holdout_id": holdout_id,
                    "job_id": job["id"],
                    "permit_id": permit.permit_id,
                },
            )
            reveal = _record(
                kind="holdout-reveal",
                record_id=reveal_id,
                subject=f"Executable:{executable_id}",
                status="revealed_once",
                fingerprint=seal.fingerprint,
                payload={
                    "artifact_sha256": seal.payload["artifact_sha256"],
                    "candidate_id": candidate.record_id,
                    "holdout_id": holdout_id,
                    "job_id": job["id"],
                    "reveal_delta": 1,
                    "retuning_allowed": False,
                },
                event_stream=f"holdout-reveal:{holdout_id}",
                event_sequence=1,
            )
            return body, [consumption, reveal], {
                "artifact_sha256": seal.payload["artifact_sha256"],
                "holdout_id": holdout_id,
                "reveal_count": science["holdout_reveals"],
                "reveal_record_id": reveal_id,
            }

        return self._commit(
            event_kind="holdout_revealed",
            operation_id=operation_id,
            subject=f"Executable:{executable_id}",
            payload={"permit_id": permit.permit_id, "executable_id": executable_id},
            prepare=prepare,
        )

    def reveal_holdout_values(
        self,
        *,
        permit: Permit,
        executable_id: str,
        operation_id: str,
    ) -> bytes:
        """Commit the one-time reveal before returning verified sealed values."""

        consumed = self.consume_holdout_permit(
            permit=permit,
            executable_id=executable_id,
            operation_id=operation_id,
        )
        if consumed.reused:
            raise PermitError("holdout reveal operation cannot return values twice")
        return self.evidence.read_verified(consumed.result["artifact_sha256"])

    def record_holdout_evaluation(
        self,
        *,
        completion_record_id: str,
        negative_memory_id: str | None,
        operation_id: str,
    ) -> TransitionResult:
        """Dispose the revealed final surface from validator-derived Job evidence."""

        _require_ascii("completion_record_id", completion_record_id)
        if negative_memory_id is not None:
            _require_ascii("negative_memory_id", negative_memory_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            active = science.get("active_holdout_evaluation")
            if not isinstance(active, dict):
                raise TransitionError("no revealed holdout awaits evaluation")
            if (
                active.get("status")
                != "evaluation_completed_pending_disposition"
                or active.get("completion_record_id")
                != completion_record_id
                or body.get("next_action")
                != {
                    "completion_record_id": completion_record_id,
                    "holdout_id": active.get("holdout_id"),
                    "job_id": active.get("job_id"),
                    "kind": "record_holdout_evaluation",
                }
            ):
                raise TransitionError(
                    "holdout evaluation is not its exact pending disposition"
                )
            completion = index.get("job-completed", completion_record_id)
            scientific = None if completion is None else completion.payload.get("scientific")
            effective_scope = (
                None
                if completion is None or not isinstance(scientific, dict)
                else _effective_completion_scope(index, completion)
            )
            if (
                completion is None
                or completion.payload.get("job_id") != active["job_id"]
                or not isinstance(scientific, dict)
                or scientific.get("executable_id") != active["executable_id"]
                or scientific.get("evidence_depth") != "confirmation"
                or effective_scope is None
                or effective_scope.scientific_eligible is not True
            ):
                raise TransitionError(
                    "holdout disposition lacks its validator-derived evaluation"
                )
            declaration = index.get("job-declared", active["job_id"])
            if (
                declaration is None
                or declaration.payload["spec"].get("holdout_binding")
                != {"holdout_id": active["holdout_id"]}
            ):
                raise TransitionError("holdout evaluation Job binding is unavailable")
            verdict = scientific.get("verdict")
            if verdict not in {"passed", "failed", "not_evaluable"}:
                raise TransitionError("holdout validator verdict is invalid")
            candidate_head = index.event_head(
                f"candidate:{active['executable_id']}"
            )
            candidate = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            if candidate is None or candidate.record_id != active["candidate_id"]:
                raise TransitionError("holdout candidate activation changed")
            if verdict == "passed":
                if effective_scope.candidate_eligible is not True:
                    raise TransitionError(
                        "passed holdout did not authorize the frozen candidate"
                    )
                if negative_memory_id is not None:
                    raise TransitionError("passed holdout cannot carry negative memory")
                next_action = {
                    "kind": "plan_candidate_bound_evidence",
                    "executable_id": active["executable_id"],
                }
                science["required_future_holdout_id"] = None
            else:
                if verdict == "failed":
                    memory = (
                        None
                        if negative_memory_id is None
                        else index.get("negative-memory", negative_memory_id)
                    )
                    if (
                        memory is None
                        or memory.subject != f"Executable:{active['executable_id']}"
                        or completion_record_id
                        not in memory.payload.get("evidence_references", [])
                    ):
                        raise TransitionError(
                            "failed holdout requires its durable negative memory"
                        )
                elif negative_memory_id is not None:
                    raise TransitionError(
                        "not-evaluable holdout is not scientific negative memory"
                    )
                candidate_disposition_id = canonical_digest(
                    domain="candidate-disposition",
                    payload={
                        "candidate_id": active["candidate_id"],
                        "disposition": "invalidated",
                        "reason": "final_holdout_" + verdict,
                    },
                )
                candidate_disposition = _record(
                    kind="candidate-disposition",
                    record_id=candidate_disposition_id,
                    subject=f"Executable:{active['executable_id']}",
                    status="invalidated",
                    fingerprint=candidate.fingerprint,
                    payload={
                        "candidate_id": active["candidate_id"],
                        "executable_id": active["executable_id"],
                        "mission_id": science["active_mission"],
                        "reason": "final_holdout_" + verdict,
                    },
                    event_stream=f"candidate:{active['executable_id']}",
                    event_sequence=candidate_head.sequence + 1,
                )
                science["active_executable"] = None
                self._drop_authorization(
                    body, SubjectKind.EXECUTABLE, active["executable_id"]
                )
                next_action = {
                    "kind": "await_new_future_holdout_data",
                    "predecessor_holdout_id": active["holdout_id"],
                }
            disposition_id = canonical_digest(
                domain="holdout-disposition",
                payload={
                    "completion_record_id": completion_record_id,
                    "holdout_id": active["holdout_id"],
                    "verdict": verdict,
                },
            )
            disposition = _record(
                kind="holdout-disposition",
                record_id=disposition_id,
                subject=f"Holdout:{active['holdout_id']}",
                status=verdict,
                fingerprint=active["holdout_id"].removeprefix("holdout:"),
                payload={
                    "completion_record_id": completion_record_id,
                    "negative_memory_id": negative_memory_id,
                    "retuning_allowed": False,
                },
                event_stream=f"holdout-reveal:{active['holdout_id']}",
                event_sequence=2,
            )
            candidate_holdout = _record(
                kind="candidate-holdout",
                record_id=active["candidate_id"],
                subject=f"Candidate:{active['candidate_id']}",
                status=verdict,
                fingerprint=active["holdout_id"].removeprefix("holdout:"),
                payload={
                    "completion_record_id": completion_record_id,
                    "executable_id": active["executable_id"],
                    "holdout_id": active["holdout_id"],
                    "mission_id": science["active_mission"],
                },
            )
            records = [disposition, candidate_holdout]
            if verdict != "passed":
                records.append(candidate_disposition)
            science["active_holdout_evaluation"] = None
            body["next_action"] = next_action
            return body, records, {
                "holdout_id": active["holdout_id"],
                "verdict": verdict,
            }

        return self._commit(
            event_kind="holdout_evaluated",
            operation_id=operation_id,
            subject="Holdout:active",
            payload={
                "completion_record_id": completion_record_id,
                "negative_memory_id": negative_memory_id,
            },
            prepare=prepare,
        )

    def dispose_revealed_holdout_engineering_gap(
        self,
        *,
        completion_record_id: str,
        operation_id: str,
    ) -> TransitionResult:
        """Fail closed a revealed holdout after an unrecovered engineering gap."""

        _require_digest("holdout engineering completion", completion_record_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            active = science.get("active_holdout_evaluation")
            if not isinstance(active, dict):
                raise TransitionError("no revealed holdout engineering gap is active")
            if (
                active.get("status")
                != "engineering_gap_pending_disposition"
                or active.get("completion_record_id")
                != completion_record_id
                or body.get("next_action")
                != {
                    "completion_record_id": completion_record_id,
                    "holdout_id": active.get("holdout_id"),
                    "job_id": active.get("job_id"),
                    "kind": "dispose_revealed_holdout_engineering_gap",
                }
            ):
                raise TransitionError(
                    "holdout engineering gap is not the exact pending disposition"
                )
            completion = index.get("job-completed", completion_record_id)
            failure = (
                None if completion is None else completion.payload.get("failure")
            )
            engineering = (
                None
                if completion is None
                else completion.payload.get("engineering_disposition")
            )
            declaration = (
                None
                if completion is None
                else index.get(
                    "job-declared",
                    completion.payload.get("job_id", ""),
                )
            )
            holdout_id = active.get("holdout_id")
            reveal_head = (
                None
                if not isinstance(holdout_id, str)
                else index.event_head(f"holdout-reveal:{holdout_id}")
            )
            reveal = (
                None
                if reveal_head is None
                else index.get(reveal_head.record_kind, reveal_head.record_id)
            )
            if (
                completion is None
                or completion.status != "failed"
                or completion.payload.get("job_id") != active.get("job_id")
                or not isinstance(failure, Mapping)
                or failure.get("failure_kind") != "engineering"
                or not isinstance(engineering, Mapping)
                or engineering.get("schema")
                != "engineering_failure_disposition.v1"
                or completion.payload.get("scientific") is not None
                or completion.payload.get("source") is not None
                or completion.payload.get("external") is not None
                or declaration is None
                or declaration.payload.get("spec", {}).get("holdout_binding")
                != {"holdout_id": holdout_id}
                or declaration.payload.get("spec", {}).get(
                    "evidence_subject"
                )
                != {
                    "kind": "Executable",
                    "id": active.get("executable_id"),
                }
                or reveal_head is None
                or reveal_head.sequence != 1
                or reveal is None
                or reveal.kind != "holdout-reveal"
                or reveal.status != "revealed_once"
                or reveal.payload.get("job_id") != active.get("job_id")
            ):
                raise TransitionError(
                    "holdout engineering gap lacks exact typed provenance"
                )
            executable_id = active["executable_id"]
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate = (
                None
                if candidate_head is None
                else index.get(
                    candidate_head.record_kind,
                    candidate_head.record_id,
                )
            )
            if (
                candidate is None
                or candidate.record_id != active.get("candidate_id")
                or candidate.status not in {"frozen", "bound_fixture"}
            ):
                raise TransitionError(
                    "holdout engineering gap lost its candidate activation"
                )
            disposition_payload = {
                "completion_record_id": completion_record_id,
                "engineering_disposition_hash": failure.get(
                    "repair_disposition_hash"
                ),
                "negative_memory_id": None,
                "retuning_allowed": False,
                "scientific_failure_delta": 0,
                "scientific_trial_delta": 0,
            }
            holdout_disposition_id = canonical_digest(
                domain="holdout-disposition",
                payload={
                    "completion_record_id": completion_record_id,
                    "holdout_id": holdout_id,
                    "verdict": "engineering_gap",
                },
            )
            holdout_disposition = _record(
                kind="holdout-disposition",
                record_id=holdout_disposition_id,
                subject=f"Holdout:{holdout_id}",
                status="engineering_gap",
                fingerprint=holdout_id.removeprefix("holdout:"),
                payload=disposition_payload,
                event_stream=f"holdout-reveal:{holdout_id}",
                event_sequence=2,
            )
            candidate_holdout = _record(
                kind="candidate-holdout",
                record_id=active["candidate_id"],
                subject=f"Candidate:{active['candidate_id']}",
                status="engineering_gap",
                fingerprint=holdout_id.removeprefix("holdout:"),
                payload={
                    "completion_record_id": completion_record_id,
                    "executable_id": executable_id,
                    "holdout_id": holdout_id,
                    "mission_id": science["active_mission"],
                    "scientific_failure_delta": 0,
                },
            )
            candidate_disposition_id = canonical_digest(
                domain="candidate-disposition",
                payload={
                    "candidate_id": active["candidate_id"],
                    "disposition": "invalidated",
                    "reason": "final_holdout_engineering_gap",
                },
            )
            candidate_disposition = _record(
                kind="candidate-disposition",
                record_id=candidate_disposition_id,
                subject=f"Executable:{executable_id}",
                status="invalidated",
                fingerprint=candidate.fingerprint,
                payload={
                    "candidate_id": active["candidate_id"],
                    "executable_id": executable_id,
                    "mission_id": science["active_mission"],
                    "reason": "final_holdout_engineering_gap",
                    "scientific_failure_delta": 0,
                },
                event_stream=f"candidate:{executable_id}",
                event_sequence=candidate_head.sequence + 1,
            )
            science["active_holdout_evaluation"] = None
            science["active_executable"] = None
            self._drop_authorization(
                body,
                SubjectKind.EXECUTABLE,
                executable_id,
            )
            body["next_action"] = {
                "kind": "await_new_future_holdout_data",
                "predecessor_holdout_id": holdout_id,
            }
            return body, [
                holdout_disposition,
                candidate_holdout,
                candidate_disposition,
            ], {
                "candidate_id": active["candidate_id"],
                "completion_record_id": completion_record_id,
                "holdout_id": holdout_id,
                "verdict": "engineering_gap",
            }

        return self._commit(
            event_kind="holdout_engineering_gap_disposed",
            operation_id=operation_id,
            subject="Holdout:active",
            payload={"completion_record_id": completion_record_id},
            prepare=prepare,
        )

    @staticmethod
    def _resolved_candidate_disposition_for_completion(
        index: LocalIndex,
        *,
        completion: IndexRecord,
        mission_id: str,
    ) -> str | None:
        """Return the exact terminal candidate-stream head for one positive.

        Candidate eligibility is authority to enter the candidate lifecycle,
        not a permanent ban on an honest axis disposition.  It is resolved only
        when the Writer-created candidate binds this exact completion and the
        latest executable stream head is its later typed disposition.
        """

        scientific = completion.payload.get("scientific")
        effective_scope = (
            None
            if not isinstance(scientific, dict)
            else _effective_completion_scope(index, completion)
        )
        executable_id = (
            None
            if not isinstance(scientific, dict)
            else scientific.get("executable_id")
        )
        if (
            completion.status != "success"
            or not isinstance(scientific, dict)
            or effective_scope is None
            or effective_scope.scientific_eligible is not True
            or effective_scope.candidate_eligible is not True
            or not isinstance(executable_id, str)
        ):
            return None
        head = index.event_head(f"candidate:{executable_id}")
        disposition = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        candidate_id = (
            None
            if disposition is None
            else disposition.payload.get("candidate_id")
        )
        candidate = (
            None
            if not isinstance(candidate_id, str)
            else index.get("candidate", candidate_id)
        )
        evidence_refs = (
            None if candidate is None else candidate.payload.get("evidence_refs")
        )
        reason = (
            None if disposition is None else disposition.payload.get("reason")
        )
        expected_candidate_id = (
            None
            if not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) for item in evidence_refs)
            else "candidate:"
            + canonical_digest(
                domain="mission-candidate",
                payload={
                    "evidence_refs": sorted(evidence_refs),
                    "executable_id": executable_id,
                    "mission_id": mission_id,
                },
            )
        )
        expected_disposition_id = (
            None
            if disposition is None
            or not isinstance(reason, str)
            or disposition.status
            not in {
                "invalidated",
                "rejected",
                "returned_to_library",
                "superseded",
            }
            else canonical_digest(
                domain="candidate-disposition",
                payload={
                    "candidate_id": candidate_id,
                    "disposition": disposition.status,
                    "reason": reason,
                },
            )
        )
        candidate_stream = f"candidate:{executable_id}"
        if (
            head is None
            or disposition is None
            or disposition.kind != "candidate-disposition"
            or disposition.event_stream != candidate_stream
            or disposition.event_sequence != head.sequence
            or disposition.record_id != expected_disposition_id
            or disposition.subject != f"Executable:{executable_id}"
            or disposition.payload.get("candidate_id") != candidate_id
            or disposition.payload.get("executable_id") != executable_id
            or disposition.payload.get("mission_id") != mission_id
            or candidate is None
            or candidate.record_id != expected_candidate_id
            or candidate.status != "frozen"
            or candidate.event_stream != candidate_stream
            or candidate.event_sequence is None
            or candidate.event_sequence + 1 != disposition.event_sequence
            or candidate.subject != f"Executable:{executable_id}"
            or candidate.fingerprint != executable_id.removeprefix("executable:")
            or disposition.fingerprint != candidate.fingerprint
            or candidate.payload.get("mission_id") != mission_id
            or not isinstance(evidence_refs, list)
            or len(set(evidence_refs)) != len(evidence_refs)
            or evidence_refs != sorted(evidence_refs)
            or completion.record_id not in evidence_refs
            or completion.authority_sequence is None
            or candidate.authority_sequence is None
            or disposition.authority_sequence is None
            or candidate.authority_sequence <= completion.authority_sequence
            or disposition.authority_sequence <= candidate.authority_sequence
        ):
            return None
        return disposition.record_id

    @classmethod
    def _candidate_authority_for_axis_bindings(
        cls,
        index: LocalIndex,
        *,
        references: Sequence[Any],
        bindings: Sequence[Any],
        mission_id: str,
    ) -> tuple[list[dict[str, str]], tuple[str, ...]]:
        resolved: list[dict[str, str]] = []
        unresolved: list[str] = []
        for reference, binding in zip(references, bindings, strict=True):
            if not binding.candidate_eligible:
                continue
            completion = (
                None
                if getattr(reference.kind, "value", None) != "job-completed"
                else index.get("job-completed", reference.record_id)
            )
            disposition_id = (
                None
                if completion is None
                else cls._resolved_candidate_disposition_for_completion(
                    index,
                    completion=completion,
                    mission_id=mission_id,
                )
            )
            if disposition_id is None:
                unresolved.append(reference.record_id)
            else:
                resolved.append(
                    {
                        "candidate_disposition_record_id": disposition_id,
                        "completion_record_id": reference.record_id,
                    }
                )
        return (
            sorted(
                resolved,
                key=lambda item: (
                    item["completion_record_id"],
                    item["candidate_disposition_record_id"],
                ),
            ),
            tuple(sorted(unresolved)),
        )
