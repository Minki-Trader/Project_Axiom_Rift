"""Historical replay, audit correction, and adjudication transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.historical_family_binding import HistoricalFamilyAuthority
from axiom_rift.operations.writer_lifecycle import _STUDY_OUTCOMES
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _record,
    _require_digest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.state import WriterLock
from axiom_rift.storage.study_kpi import validate_study_id


class HistoricalReplayWriterMixin:
    """Own historical correction and replay transitions; the facade commits."""

    def _require_historical_validity_override(
        self,
        index: LocalIndex,
        *,
        override: Any,
        completion_record_id: str,
        executable_id: str,
        declaration: IndexRecord,
    ) -> None:
        """Verify that an additive validity override is an exact dependency fact."""

        from axiom_rift.research.historical_adjudication import (
            HistoricalValidityOverride,
            HistoricalValidityReason,
        )
        from axiom_rift.research.source_authority import (
            AUTHORITY_TRANSITION_EVIDENCE,
            SourceAuthorityAuditManifest,
            SourceAuthorityInvalidation,
            SourceAuthorityLatch,
        )

        if not isinstance(override, HistoricalValidityOverride):
            raise TransitionError("historical validity override is unsupported")

        if (
            override.reason
            is HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
        ):
            from axiom_rift.operations.completion_validity_projection import (
                CompletionValidityProjectionError,
                current_completion_validity_invalidation,
            )

            if override.subject_id != completion_record_id:
                raise TransitionError(
                    "historical validity override targets another completion"
                )
            try:
                head = current_completion_validity_invalidation(
                    index, completion_record_id
                )
            except CompletionValidityProjectionError as exc:
                raise TransitionError(
                    "historical completion validity head is malformed"
                ) from exc
            if (
                head is None
                or head.invalidation_record_id != override.evidence_record_id
                or head.completion_record_id != completion_record_id
                or head.executable_id != executable_id
                or head.invalidation.job_id != declaration.record_id
                or head.invalidation.study_id
                != declaration.payload.get("study_id")
            ):
                raise TransitionError(
                    "historical validity override does not bind the canonical "
                    "completion correction"
                )
            return

        if override.reason is not HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED:
            raise TransitionError("historical validity override is unsupported")

        source_id = override.subject_id
        correction = index.get(
            "source-authority-invalidation", override.evidence_record_id
        )
        if correction is None:
            raise TransitionError(
                "historical validity override evidence is unavailable"
            )
        try:
            invalidation = SourceAuthorityInvalidation.from_identity_payload(
                correction.payload["invalidation"]
            )
            manifest = SourceAuthorityAuditManifest.from_mapping(
                correction.payload["audit_manifest"]
            )
            latch = SourceAuthorityLatch.from_mapping(correction.payload["latch"])
            expected_latch = SourceAuthorityLatch.bind(
                invalidation=invalidation,
                manifest=manifest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransitionError(
                "historical validity override evidence is malformed"
            ) from exc

        correction_head = index.event_head(f"source-authority:{source_id}")
        if (
            invalidation.identity != override.evidence_record_id
            or invalidation.source_contract_id != source_id
            or correction.subject != f"Source:{source_id}"
            or correction.status != "confirmed_and_suspended"
            or correction.fingerprint
            != override.evidence_record_id.removeprefix(
                "source-authority-invalidation:"
            )
            or correction.event_stream != f"source-authority:{source_id}"
            or correction.event_sequence != 1
            or correction_head is None
            or correction_head.record_kind != correction.kind
            or correction_head.record_id != correction.record_id
            or correction_head.sequence != correction.event_sequence
            or latch != expected_latch
            or latch.source_contract_id != source_id
            or latch.invalidation_id != override.evidence_record_id
            or latch.audit_manifest_hash != invalidation.audit_artifact_hash
        ):
            raise TransitionError(
                "historical validity override does not bind the canonical correction"
            )

        try:
            durable_manifest = SourceAuthorityAuditManifest.from_bytes(
                self.evidence.read_verified(latch.audit_manifest_hash)
            )
            durable_report = self.evidence.read_verified(
                latch.report_artifact_hash
            )
            durable_manifest.require_report(durable_report)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "historical validity override audit evidence is unavailable"
            ) from exc
        if durable_manifest != manifest:
            raise TransitionError(
                "historical validity override audit manifest has drifted"
            )

        original_state = index.get(
            "source-state", invalidation.source_state_record_id
        )
        replacement_id = correction.payload.get("replacement_state_record_id")
        replacement_state = (
            None
            if not isinstance(replacement_id, str)
            else index.get("source-state", replacement_id)
        )
        prior_active_id = correction.payload.get(
            "prior_active_source_state_record_id"
        )
        prior_active_state = (
            None
            if not isinstance(prior_active_id, str)
            else index.get("source-state", prior_active_id)
        )
        source_head = index.event_head(f"source:{source_id}")
        preserved_receipt_id = correction.payload.get("preserved_receipt_id")
        ordinary_suspended = (
            original_state is not None
            and prior_active_state is not None
            and original_state.record_id != prior_active_state.record_id
        )
        if (
            original_state is None
            or original_state.subject != f"Source:{source_id}"
            or original_state.status != "runtime_eligible"
            or original_state.fingerprint != source_id
            or original_state.event_stream != f"source:{source_id}"
            or replacement_state is None
            or replacement_state.subject != f"Source:{source_id}"
            or replacement_state.status != "suspended"
            or replacement_state.fingerprint != source_id
            or replacement_state.event_stream != f"source:{source_id}"
            or original_state.event_sequence is None
            or prior_active_state is None
            or prior_active_state.event_sequence is None
            or replacement_state.event_sequence
            != prior_active_state.event_sequence + 1
            or source_head is None
            or source_head.record_kind != "source-state"
            or source_head.record_id != replacement_state.record_id
            or source_head.sequence != replacement_state.event_sequence
            or replacement_state.payload.get("transition_evidence")
            != AUTHORITY_TRANSITION_EVIDENCE
            or replacement_state.payload.get("source_authority_latch")
            != latch.to_identity_payload()
            or correction.payload.get("eligible_source_state_record_id")
            != original_state.record_id
            or replacement_state.payload.get("eligible_source_state_record_id")
            != original_state.record_id
            or replacement_state.payload.get(
                "prior_active_source_state_record_id"
            )
            != prior_active_state.record_id
            or replacement_state.payload.get("evidence_receipt_id")
            != preserved_receipt_id
            or original_state.payload.get("evidence_receipt_id")
            != preserved_receipt_id
            or replacement_state.payload.get("receipt")
            != original_state.payload.get("receipt")
            or (
                ordinary_suspended
                and (
                    prior_active_state.status != "suspended"
                    or prior_active_state.event_sequence
                    != original_state.event_sequence + 1
                    or prior_active_state.payload.get("transition_evidence")
                    != "drift"
                    or prior_active_state.payload.get("source_authority_latch")
                    is not None
                    or any(
                        prior_active_state.payload.get(field)
                        != original_state.payload.get(field)
                        for field in (
                            "availability_identity",
                            "clock_identity",
                            "contract",
                            "contract_hash",
                            "field_identity",
                            "mapping_identity",
                            "schema_identity",
                        )
                    )
                )
            )
        ):
            raise TransitionError(
                "historical validity override source suspension is not durable"
            )

        spec = declaration.payload.get("spec")
        trial = index.get("trial", executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        sources = (
            None if not isinstance(executable, dict) else executable.get("source_contracts")
        )
        if (
            not isinstance(spec, dict)
            or spec.get("evidence_subject")
            != {"kind": "Executable", "id": executable_id}
            or trial is None
            or trial.record_id != executable_id
            or trial.status != "evaluated"
            or not isinstance(executable, dict)
            or canonical_digest(domain="executable", payload=executable)
            != executable_id.removeprefix("executable:")
            or not isinstance(sources, list)
            or source_id not in sources
        ):
            raise TransitionError(
                "historical validity override is not bound to the completed trial"
            )

    def record_historical_scientific_validity_invalidations(
        self,
        *,
        invalidations: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Remove authority from exact historical completions additively.

        The completion, Study close, trial, adjudication, and negative-memory
        records remain immutable.  Each new stream head is backed by one exact
        ASCII audit finding row and receives no scientific or lifecycle credit.
        """

        from axiom_rift.operations.completion_validity_projection import (
            CompletionValidityProjectionError,
            completion_validity_invalidation_record,
            completion_validity_stream,
            validate_completion_validity_invalidation_binding,
        )
        from axiom_rift.research.historical_scientific_validity import (
            AUTHORITY_DELTA_ZERO,
            HistoricalScientificValidityInvalidation,
        )

        normalized = tuple(invalidations)
        if (
            not normalized
            or any(
                not isinstance(item, HistoricalScientificValidityInvalidation)
                for item in normalized
            )
            or len({item.completion_record_id for item in normalized})
            != len(normalized)
            or len({item.identity for item in normalized}) != len(normalized)
        ):
            raise TransitionError(
                "historical scientific validity correction requires unique "
                "typed completion invalidations"
            )
        normalized = tuple(
            sorted(normalized, key=lambda item: item.completion_record_id)
        )

        def require_audit_finding(
            invalidation: HistoricalScientificValidityInvalidation,
            document: bytes,
        ) -> None:
            try:
                lines = document.decode("ascii").splitlines()
            except UnicodeDecodeError as exc:
                raise TransitionError(
                    "historical scientific validity audit must be ASCII"
                ) from exc
            heading = f"- {invalidation.audit_finding_id}:"
            starts = [position for position, line in enumerate(lines) if line == heading]
            if len(starts) != 1:
                raise TransitionError(
                    "historical scientific validity audit finding is not unique"
                )
            start = starts[0]
            end = len(lines)
            for position in range(start + 1, len(lines)):
                if lines[position].startswith("- AX-") and lines[position].endswith(":"):
                    end = position
                    break
            finding = lines[start:end]
            required = (
                f"  reason {invalidation.reason.value}",
                (
                    f"  {invalidation.study_id} {invalidation.executable_id} "
                    f"completion {invalidation.completion_record_id}"
                ),
            )
            if any(finding.count(line) != 1 for line in required):
                raise TransitionError(
                    "historical scientific validity audit lacks the exact "
                    "completion finding slice"
                )

        audit_documents: dict[str, bytes] = {}
        for invalidation in normalized:
            try:
                document = self.evidence.read_verified(
                    invalidation.audit_artifact_hash
                )
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "historical scientific validity audit evidence is unavailable"
                ) from exc
            require_audit_finding(invalidation, document)
            prior_document = audit_documents.setdefault(
                invalidation.audit_artifact_hash, document
            )
            if prior_document != document:
                raise TransitionError(
                    "historical scientific validity audit evidence is inconsistent"
                )
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "historical scientific validity correction requires control"
                )
            science = current["scientific"]
            if (
                not isinstance(science.get("active_mission"), str)
                or not isinstance(science.get("active_initiative"), str)
                or current.get("next_action", {}).get("kind")
                != "portfolio_decision"
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "historical scientific validity correction requires the "
                    "active stable Portfolio boundary"
                )

            records: list[IndexRecord] = []
            inventory: list[dict[str, str]] = []
            for invalidation in normalized:
                try:
                    durable_document = self.evidence.read_verified(
                        invalidation.audit_artifact_hash
                    )
                except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "historical scientific validity audit evidence changed "
                        "before commit"
                    ) from exc
                if durable_document != audit_documents[invalidation.audit_artifact_hash]:
                    raise RecoveryRequired(
                        "historical scientific validity audit evidence changed "
                        "before commit"
                    )
                require_audit_finding(invalidation, durable_document)
                stream = completion_validity_stream(
                    invalidation.completion_record_id
                )
                if index.event_head(stream) is not None:
                    raise TransitionError(
                        "historical scientific validity completion already has a head"
                    )
                try:
                    validate_completion_validity_invalidation_binding(
                        index, invalidation
                    )
                    record = completion_validity_invalidation_record(
                        invalidation,
                        sequence=1,
                    )
                except (CompletionValidityProjectionError, TypeError, ValueError) as exc:
                    raise TransitionError(
                        "historical scientific validity binding is invalid"
                    ) from exc
                records.append(record)
                inventory.append(
                    {
                        "completion_record_id": invalidation.completion_record_id,
                        "invalidation_record_id": invalidation.identity,
                    }
                )
            return self._body(current), records, {
                "authority_delta": dict(AUTHORITY_DELTA_ZERO),
                "invalidations": inventory,
            }

        return self._commit(
            event_kind="historical_scientific_validity_invalidations_recorded",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "invalidations": [
                    item.to_identity_payload() for item in normalized
                ],
            },
            prepare=prepare,
        )

    def record_historical_cost_semantics_latch(
        self,
        *,
        manifest_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Activate the one frozen completed-period spread-cost qualification.

        The canonical manifest and its exact ASCII report are content-addressed
        evidence.  The Writer independently rederives the complete bounded
        inventory from the authenticated index before recording a zero-credit,
        sequence-one latch without changing control or scientific state.
        """

        from axiom_rift.operations.historical_cost_semantics_projection import (
            LATCH_EVENT_KIND,
            LATCH_RECORD_KIND,
            LATCH_STREAM,
            HistoricalCostSemanticsProjectionError,
            build_historical_spread_semantics_audit_manifest,
            historical_cost_semantics_activation_records,
            validate_historical_cost_semantics_latch_binding,
        )
        from axiom_rift.research.historical_cost_semantics import (
            AUTHORITY_DELTA_ZERO,
            HistoricalCostSemanticsError,
            HistoricalCostSemanticsLatch,
            HistoricalSpreadSemanticsAuditManifest,
        )

        _require_digest(
            "historical spread semantics audit manifest",
            manifest_artifact_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(manifest_artifact_hash)
            manifest = HistoricalSpreadSemanticsAuditManifest.from_bytes(
                manifest_bytes
            )
            if manifest.artifact_hash != manifest_artifact_hash:
                raise HistoricalCostSemanticsError(
                    "canonical manifest hash differs from its evidence identity"
                )
            report_bytes = self.evidence.read_verified(
                manifest.audit_artifact_hash
            )
            manifest.require_report(report_bytes)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "historical cost semantics latch lacks its exact canonical evidence"
            ) from exc

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "historical cost semantics latch requires control"
                )
            science = current["scientific"]
            mission_id = science.get("active_mission")
            initiative_id = science.get("active_initiative")
            next_action = current.get("next_action")
            snapshot_id = (
                next_action.get("portfolio_snapshot_id")
                if isinstance(next_action, Mapping)
                else None
            )
            snapshot = (
                index.get("portfolio-snapshot", snapshot_id)
                if type(snapshot_id) is str
                else None
            )
            if (
                type(mission_id) is not str
                or type(initiative_id) is not str
                or not isinstance(next_action, Mapping)
                or next_action.get("kind") != "portfolio_decision"
                or type(snapshot_id) is not str
                or snapshot is None
                or snapshot.subject != f"Mission:{mission_id}"
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "historical cost semantics latch requires the active stable "
                    "Portfolio boundary"
                )
            if index.event_head(LATCH_STREAM) is not None or index.count_by_kind(
                LATCH_RECORD_KIND
            ):
                raise TransitionError(
                    "historical cost semantics latch already has a frozen head"
                )

            try:
                durable_manifest_bytes = self.evidence.read_verified(
                    manifest_artifact_hash
                )
                durable_report_bytes = self.evidence.read_verified(
                    manifest.audit_artifact_hash
                )
                durable_manifest = HistoricalSpreadSemanticsAuditManifest.from_bytes(
                    durable_manifest_bytes
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "historical cost semantics evidence changed before commit"
                ) from exc
            if (
                durable_manifest_bytes != manifest_bytes
                or durable_report_bytes != report_bytes
                or durable_manifest != manifest
            ):
                raise RecoveryRequired(
                    "historical cost semantics evidence changed before commit"
                )

            try:
                expected_manifest = (
                    build_historical_spread_semantics_audit_manifest(
                        index,
                        audit_artifact_hash=manifest.audit_artifact_hash,
                    )
                )
                if (
                    expected_manifest != manifest
                    or canonical_bytes(expected_manifest.to_payload())
                    != manifest_bytes
                ):
                    raise HistoricalCostSemanticsProjectionError(
                        "current inventory differs from the canonical audit manifest"
                )
                latch = HistoricalCostSemanticsLatch.from_audit_manifest(manifest)
                audit_slice = validate_historical_cost_semantics_latch_binding(
                    index,
                    latch,
                    manifest,
                )
                records = historical_cost_semantics_activation_records(
                    latch,
                    audit_slice,
                )
            except (
                HistoricalCostSemanticsError,
                HistoricalCostSemanticsProjectionError,
                TypeError,
                ValueError,
            ) as exc:
                raise TransitionError(
                    "historical cost semantics manifest cannot be rederived exactly"
                ) from exc

            return self._body(current), list(records), {
                "audit_manifest_hash": manifest.artifact_hash,
                "authority_delta": dict(AUTHORITY_DELTA_ZERO),
                "latch_record_id": latch.identity,
            }

        return self._commit(
            event_kind=LATCH_EVENT_KIND,
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "audit_manifest_hash": manifest.artifact_hash,
                "audit_manifest_identity": manifest.identity,
                "audit_report_hash": manifest.audit_artifact_hash,
            },
            prepare=prepare,
        )

    def _writer_derived_historical_validity_overrides(
        self,
        index: LocalIndex,
        *,
        completion_record_id: str,
        executable_id: str,
        declaration: IndexRecord,
        prior: IndexRecord | None,
    ) -> tuple[Any, ...]:
        """Derive the monotone validity facts for one legacy completion.

        A request may describe these facts, but it cannot create, omit, or
        withdraw them.  Durable source-authority and completion-validity heads,
        plus any prior additive overlay, are the only inputs to this projection.
        """

        from axiom_rift.research.historical_adjudication import (
            HistoricalValidityOverride,
            HistoricalValidityReason,
        )

        trial = index.get("trial", executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        sources = (
            None
            if not isinstance(executable, dict)
            else executable.get("source_contracts")
        )
        if (
            trial is None
            or trial.record_id != executable_id
            or trial.status != "evaluated"
            or not isinstance(executable, dict)
            or canonical_digest(domain="executable", payload=executable)
            != executable_id.removeprefix("executable:")
            or not isinstance(sources, list)
            or any(type(source_id) is not str for source_id in sources)
            or len(sources) != len(set(sources))
        ):
            raise TransitionError(
                "historical validity projection lacks the exact completed trial"
            )

        overrides_by_subject: dict[str, Any] = {}
        if prior is not None:
            raw_prior = prior.payload.get("validity_overrides")
            if not isinstance(raw_prior, list):
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                )
            try:
                prior_overrides = tuple(
                    HistoricalValidityOverride(
                        reason=HistoricalValidityReason(item["reason"]),
                        subject_id=item["subject_id"],
                        evidence_record_id=item["evidence_record_id"],
                    )
                    for item in raw_prior
                    if isinstance(item, dict)
                    and set(item)
                    == {"evidence_record_id", "reason", "subject_id"}
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                ) from exc
            if len(prior_overrides) != len(raw_prior):
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                )
            for override in prior_overrides:
                self._require_historical_validity_override(
                    index,
                    override=override,
                    completion_record_id=completion_record_id,
                    executable_id=executable_id,
                    declaration=declaration,
                )
                previous = overrides_by_subject.setdefault(
                    override.subject_id, override
                )
                if previous != override:
                    raise RecoveryRequired(
                        "prior historical validity projection conflicts"
                    )

        for source_id in sorted(sources):
            correction_head = index.event_head(f"source-authority:{source_id}")
            if correction_head is None:
                continue
            if correction_head.record_kind != "source-authority-invalidation":
                raise RecoveryRequired(
                    "source authority correction head is malformed"
                )
            try:
                override = HistoricalValidityOverride(
                    reason=(
                        HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
                    ),
                    subject_id=source_id,
                    evidence_record_id=correction_head.record_id,
                )
            except (TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "source authority correction identity is malformed"
                ) from exc
            self._require_historical_validity_override(
                index,
                override=override,
                completion_record_id=completion_record_id,
                executable_id=executable_id,
                declaration=declaration,
            )
            previous = overrides_by_subject.setdefault(source_id, override)
            if previous != override:
                raise RecoveryRequired(
                    "historical validity correction cannot be replaced"
                )

        from axiom_rift.operations.completion_validity_projection import (
            CompletionValidityProjectionError,
            current_completion_validity_invalidation,
        )

        try:
            completion_head = current_completion_validity_invalidation(
                index, completion_record_id
            )
        except CompletionValidityProjectionError as exc:
            raise RecoveryRequired(
                "completion validity correction head is malformed"
            ) from exc
        if completion_head is not None:
            try:
                override = HistoricalValidityOverride(
                    reason=(
                        HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
                    ),
                    subject_id=completion_record_id,
                    evidence_record_id=completion_head.invalidation_record_id,
                )
            except (TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "completion validity correction identity is malformed"
                ) from exc
            self._require_historical_validity_override(
                index,
                override=override,
                completion_record_id=completion_record_id,
                executable_id=executable_id,
                declaration=declaration,
            )
            previous = overrides_by_subject.setdefault(
                completion_record_id, override
            )
            if previous != override:
                raise RecoveryRequired(
                    "historical completion validity correction cannot be replaced"
                )

        return tuple(
            sorted(
                overrides_by_subject.values(),
                key=lambda item: (
                    item.reason.value,
                    item.subject_id,
                    item.evidence_record_id,
                ),
            )
        )

    def plan_historical_replay_correction(
        self,
        *,
        adjudication_record_ids: Sequence[str],
        replay_study_id: str,
    ) -> dict[str, Any]:
        """Build a read-only explicit complete-history correction audit plan."""

        normalized_ids = tuple(sorted(adjudication_record_ids))
        if (
            not normalized_ids
            or len(normalized_ids) != len(set(normalized_ids))
            or any(type(item) is not str for item in normalized_ids)
        ):
            raise TransitionError("replay correction adjudication ids are invalid")
        validate_study_id(replay_study_id)
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                mission_id = current["scientific"].get("active_mission")
                if not isinstance(mission_id, str):
                    raise TransitionError(
                        "replay correction plan requires an active Mission"
                    )
                from axiom_rift.operations.replay_projection import (
                    ReplayProjectionError,
                    ReplayTransitionError,
                    build_explicit_historical_replay_correction_audit_plan,
                )

                try:
                    return build_explicit_historical_replay_correction_audit_plan(
                        index,
                        mission_id=mission_id,
                        adjudication_record_ids=normalized_ids,
                        replay_study_id=replay_study_id,
                    )
                except ReplayProjectionError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                except ReplayTransitionError as exc:
                    raise TransitionError(str(exc)) from exc

    def record_historical_replay_correction(
        self,
        *,
        adjudication_record_ids: Sequence[str],
        satisfactions: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Backfill replay streams and bind already-completed audit-only replay."""

        from axiom_rift.research.replay_obligation import ReplaySatisfaction
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_correction,
        )

        normalized_ids = tuple(sorted(adjudication_record_ids))
        normalized_satisfactions = tuple(
            sorted(satisfactions, key=lambda item: getattr(item, "obligation_id", ""))
        )
        if (
            not normalized_ids
            or len(normalized_ids) != len(set(normalized_ids))
            or any(type(item) is not str for item in normalized_ids)
            or not normalized_satisfactions
            or any(
                not isinstance(item, ReplaySatisfaction)
                for item in normalized_satisfactions
            )
            or len(
                {item.obligation_id for item in normalized_satisfactions}
            )
            != len(normalized_satisfactions)
        ):
            raise TransitionError("historical replay correction request is invalid")
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("historical replay correction requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            if not isinstance(mission_id, str) or any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError(
                    "historical replay correction requires a stable Mission boundary"
                )
            try:
                records, constraints, result = prepare_correction(
                    index,
                    mission_id=mission_id,
                    adjudication_record_ids=normalized_ids,
                    satisfactions=normalized_satisfactions,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                body["next_action"], constraints
            )
            return body, records, result

        return self._commit(
            event_kind="historical_replay_correction_recorded",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "adjudication_record_ids": list(normalized_ids),
                "satisfactions": [
                    item.to_identity_payload()
                    for item in normalized_satisfactions
                ],
            },
            prepare=prepare,
        )

    def plan_historical_replay_satisfaction_invalidation(
        self,
        *,
        obligation_id: str,
    ) -> dict[str, Any]:
        """Derive a read-only audit artifact for one invalid satisfied head."""

        if (
            type(obligation_id) is not str
            or not obligation_id.startswith("historical-replay-obligation:")
        ):
            raise TransitionError(
                "replay satisfaction invalidation obligation is malformed"
            )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            build_satisfaction_invalidation_plan,
        )

        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                mission_id = current["scientific"].get("active_mission")
                if not isinstance(mission_id, str):
                    raise TransitionError(
                        "replay satisfaction invalidation requires an active Mission"
                    )
                try:
                    return build_satisfaction_invalidation_plan(
                        index,
                        mission_id=mission_id,
                        obligation_id=obligation_id,
                    )
                except ReplayProjectionError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                except ReplayTransitionError as exc:
                    raise TransitionError(str(exc)) from exc

    def invalidate_historical_replay_satisfaction(
        self,
        *,
        obligation_id: str,
        audit_manifest_hash: str,
        operation_id: str,
        historical_family_authority: HistoricalFamilyAuthority | None = None,
    ) -> TransitionResult:
        """Revoke one reproducibly invalid satisfaction and requeue it."""

        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_satisfaction_invalidation,
            scheduler_constraints,
        )
        from axiom_rift.research.replay_satisfaction_invalidation import (
            replay_satisfaction_invalidation_manifest_from_bytes,
        )
        from axiom_rift.operations.historical_family_authority_admission import (
            HistoricalFamilyAuthorityAdmissionError,
            prepare_historical_family_authority_record,
        )

        if (
            type(obligation_id) is not str
            or not obligation_id.startswith("historical-replay-obligation:")
        ):
            raise TransitionError(
                "replay satisfaction invalidation obligation is malformed"
            )
        _require_digest(
            "replay satisfaction invalidation audit manifest",
            audit_manifest_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(audit_manifest_hash)
            manifest = replay_satisfaction_invalidation_manifest_from_bytes(
                manifest_bytes
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "replay satisfaction invalidation lacks its exact canonical manifest"
            ) from exc
        if manifest.obligation_id != obligation_id:
            raise TransitionError(
                "replay satisfaction invalidation artifact targets another obligation"
            )
        family_authority = historical_family_authority
        if family_authority is not None and not isinstance(
            family_authority,
            HistoricalFamilyAuthority,
        ):
            raise TransitionError(
                "historical family correction authority is not typed"
            )

        def require_family_authority(
            index: LocalIndex,
        ) -> IndexRecord | None:
            if family_authority is None:
                return None
            if family_authority.replay_obligation_id != obligation_id:
                raise TransitionError(
                    "historical family authority targets another obligation"
                )
            try:
                return prepare_historical_family_authority_record(
                    repository_root=self.root,
                    index=index,
                    authority=family_authority,
                )
            except HistoricalFamilyAuthorityAdmissionError as exc:
                raise TransitionError(str(exc)) from exc
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "replay satisfaction invalidation requires control"
                )
            science = current["scientific"]
            mission_id = science.get("active_mission")
            next_action = current.get("next_action")
            if (
                not isinstance(mission_id, str)
                or not isinstance(next_action, dict)
                or next_action.get("kind")
                not in {
                    "choose_next_initiative_or_terminal",
                    "portfolio_decision",
                }
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "replay satisfaction invalidation requires a stable scheduler boundary"
                )
            current_constraints = scheduler_constraints(
                index,
                mission_id=mission_id,
            )
            projected_constraints = {
                name: next_action.get(name)
                for name in (
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                )
                if next_action.get(name) is not None
            }
            if projected_constraints != (current_constraints or {}):
                raise TransitionError(
                    "replay satisfaction invalidation scheduler authority is stale"
                )
            try:
                durable_bytes = self.evidence.read_verified(audit_manifest_hash)
                durable_manifest = (
                    replay_satisfaction_invalidation_manifest_from_bytes(
                        durable_bytes
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "replay satisfaction invalidation evidence changed before commit"
                ) from exc
            if durable_bytes != manifest_bytes or durable_manifest != manifest:
                raise RecoveryRequired(
                    "replay satisfaction invalidation manifest changed before commit"
                )
            try:
                records, constraints, result = prepare_satisfaction_invalidation(
                    index,
                    mission_id=mission_id,
                    obligation_id=obligation_id,
                    manifest=durable_manifest,
                    audit_manifest_hash=audit_manifest_hash,
                )
                family_record = require_family_authority(index)
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                next_action,
                constraints,
            )
            if family_record is not None:
                records.append(family_record)
                result = {
                    **result,
                    "historical_family_authority_id": family_record.record_id,
                }
            return body, records, result

        event_payload = {
            "audit_manifest_hash": audit_manifest_hash,
            "obligation_id": obligation_id,
            "satisfaction_record_id": manifest.satisfaction_record_id,
        }
        if family_authority is not None:
            event_payload["historical_family_authority"] = (
                family_authority.to_identity_payload()
            )
        return self._commit(
            event_kind="historical_replay_satisfaction_invalidated",
            operation_id=operation_id,
            subject="Mission:active",
            payload=event_payload,
            prepare=prepare,
        )

    @staticmethod
    def _require_replay_scheduler_boundary(
        current: Mapping[str, Any] | None,
        index: LocalIndex,
        *,
        operation_name: str,
    ) -> tuple[str, Mapping[str, Any]]:
        """Authenticate one idle Mission scheduler boundary without mutation."""

        from axiom_rift.operations.replay_projection import scheduler_constraints

        if current is None:
            raise TransitionError(f"{operation_name} requires control")
        science = current["scientific"]
        mission_id = science.get("active_mission")
        next_action = current.get("next_action")
        if (
            not isinstance(mission_id, str)
            or not isinstance(next_action, Mapping)
            or next_action.get("kind")
            not in {
                "choose_next_initiative_or_terminal",
                "portfolio_decision",
            }
            or any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            )
        ):
            raise TransitionError(
                f"{operation_name} requires a stable scheduler boundary"
            )
        current_constraints = scheduler_constraints(
            index,
            mission_id=mission_id,
        )
        projected_constraints = {
            name: next_action.get(name)
            for name in (
                "pending_replay_obligation_ids",
                "required_replay_priority",
            )
            if next_action.get(name) is not None
        }
        if projected_constraints != (current_constraints or {}):
            raise TransitionError(
                f"{operation_name} scheduler authority is stale"
            )
        return mission_id, next_action

    def register_historical_replay_family_authorities(
        self,
        *,
        historical_family_authorities: Sequence[HistoricalFamilyAuthority],
        operation_id: str,
    ) -> TransitionResult:
        """Register exact pending-member family authority without research credit."""

        from axiom_rift.operations.historical_family_authority_admission import (
            HistoricalFamilyAuthorityAdmissionError,
            prepare_historical_family_authority_record,
        )
        from axiom_rift.operations.replay_projection import obligation_heads

        normalized = tuple(
            sorted(
                historical_family_authorities,
                key=lambda item: getattr(item, "replay_obligation_id", ""),
            )
        )
        obligation_ids = tuple(
            item.replay_obligation_id
            for item in normalized
            if isinstance(item, HistoricalFamilyAuthority)
        )
        if (
            not normalized
            or len(obligation_ids) != len(normalized)
            or len(set(obligation_ids)) != len(obligation_ids)
        ):
            raise TransitionError(
                "historical family authority registration request is invalid"
            )
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            mission_id, _next_action = self._require_replay_scheduler_boundary(
                current,
                index,
                operation_name="historical family authority registration",
            )
            heads = {
                obligation.identity: head
                for obligation, head in obligation_heads(
                    index,
                    mission_id=mission_id,
                )
            }
            if any(
                heads.get(obligation_id) is None
                or heads[obligation_id].status != "pending"
                for obligation_id in obligation_ids
            ):
                raise TransitionError(
                    "historical family authority target is not exactly pending"
                )
            try:
                records = [
                    prepare_historical_family_authority_record(
                        repository_root=self.root,
                        index=index,
                        authority=authority,
                    )
                    for authority in normalized
                ]
            except HistoricalFamilyAuthorityAdmissionError as exc:
                raise TransitionError(str(exc)) from exc
            return self._body(current), records, {
                "candidate_delta": 0,
                "historical_family_authority_ids": [
                    record.record_id for record in records
                ],
                "holdout_reveal_delta": 0,
                "replay_obligation_ids": list(obligation_ids),
                "scientific_claim_delta": 0,
                "scientific_trial_delta": 0,
            }

        return self._commit(
            event_kind="historical_replay_family_authorities_registered",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "historical_family_authorities": [
                    item.to_identity_payload() for item in normalized
                ]
            },
            prepare=prepare,
        )

    def resolve_historical_replay_obligations(
        self,
        *,
        satisfactions: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Resolve exact in-progress replay after its mandatory Study diagnosis."""

        from axiom_rift.research.replay_obligation import ReplaySatisfaction
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_resolution,
        )

        normalized = tuple(
            sorted(satisfactions, key=lambda item: getattr(item, "obligation_id", ""))
        )
        if (
            not normalized
            or any(not isinstance(item, ReplaySatisfaction) for item in normalized)
            or len({item.obligation_id for item in normalized}) != len(normalized)
        ):
            raise TransitionError("replay resolution request is invalid")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("replay resolution requires control")
            mission_id = current["scientific"].get("active_mission")
            next_action = current.get("next_action")
            if not isinstance(mission_id, str) or not isinstance(next_action, dict):
                raise TransitionError("replay resolution requires an active Mission")
            try:
                records, constraints, result = prepare_resolution(
                    index,
                    mission_id=mission_id,
                    next_action=next_action,
                    satisfactions=normalized,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                next_action["resume_next_action"], constraints
            )
            return body, records, result

        return self._commit(
            event_kind="historical_replay_obligations_resolved",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "satisfactions": [item.to_identity_payload() for item in normalized]
            },
            prepare=prepare,
        )

    def recertify_historical_replay_sibling_evidence(
        self,
        *,
        source_satisfaction_ids: Sequence[str],
        historical_family_authorities: Sequence[HistoricalFamilyAuthority],
        operation_id: str,
    ) -> TransitionResult:
        """Credit omitted exact siblings without new trials or caller verdicts."""

        from axiom_rift.operations.historical_family_authority_admission import (
            HistoricalFamilyAuthorityAdmissionError,
            prepare_historical_family_authority_record,
            require_sibling_recertification_family_core,
        )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_sibling_evidence_recertification,
        )

        normalized_sources = tuple(sorted(set(source_satisfaction_ids)))
        normalized_authorities = tuple(
            sorted(
                historical_family_authorities,
                key=lambda item: getattr(item, "replay_obligation_id", ""),
            )
        )
        obligation_ids = tuple(
            item.replay_obligation_id
            for item in normalized_authorities
            if isinstance(item, HistoricalFamilyAuthority)
        )
        if (
            not normalized_sources
            or len(normalized_sources) != len(source_satisfaction_ids)
            or not normalized_authorities
            or len(obligation_ids) != len(normalized_authorities)
            or len(set(obligation_ids)) != len(obligation_ids)
        ):
            raise TransitionError(
                "historical sibling recertification request is invalid"
            )
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            mission_id, next_action = self._require_replay_scheduler_boundary(
                current,
                index,
                operation_name="historical sibling recertification",
            )
            try:
                (
                    _derived_satisfactions,
                    satisfaction_records,
                    constraints,
                    result,
                ) = prepare_sibling_evidence_recertification(
                    index,
                    mission_id=mission_id,
                    source_satisfaction_ids=normalized_sources,
                    obligation_ids=obligation_ids,
                )
                family_records = [
                    prepare_historical_family_authority_record(
                        repository_root=self.root,
                        index=index,
                        authority=authority,
                    )
                    for authority in normalized_authorities
                ]
                authority_by_obligation = {
                    authority.replay_obligation_id: authority
                    for authority in normalized_authorities
                }
                for satisfaction in _derived_satisfactions:
                    target_authority = authority_by_obligation.get(
                        satisfaction.obligation_id
                    )
                    if target_authority is None:
                        raise HistoricalFamilyAuthorityAdmissionError(
                            "sibling recertification target authority is absent"
                        )
                    require_sibling_recertification_family_core(
                        index,
                        target_authority=target_authority,
                        source_replay_study_id=satisfaction.replay_study_id,
                    )
            except HistoricalFamilyAuthorityAdmissionError as exc:
                raise TransitionError(str(exc)) from exc
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                next_action,
                constraints,
            )
            return body, [*family_records, *satisfaction_records], {
                **result,
                "historical_family_authority_ids": [
                    record.record_id for record in family_records
                ],
            }

        return self._commit(
            event_kind="historical_replay_sibling_evidence_recertified",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "historical_family_authorities": [
                    item.to_identity_payload()
                    for item in normalized_authorities
                ],
                "source_satisfaction_ids": list(normalized_sources),
            },
            prepare=prepare,
        )

    def defer_historical_replay_obligations(
        self,
        *,
        deferrals: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Defer replay only against durable basis and one exact resume condition."""

        from axiom_rift.research.replay_obligation import ReplayDeferral
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_deferral,
        )

        normalized = tuple(
            sorted(deferrals, key=lambda item: getattr(item, "obligation_id", ""))
        )
        if (
            not normalized
            or any(not isinstance(item, ReplayDeferral) for item in normalized)
            or len({item.obligation_id for item in normalized}) != len(normalized)
        ):
            raise TransitionError("replay deferral request is invalid")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("replay deferral requires control")
            mission_id = current["scientific"].get("active_mission")
            if not isinstance(mission_id, str):
                raise TransitionError("replay deferral requires an active Mission")
            try:
                records, constraints, result = prepare_deferral(
                    index,
                    mission_id=mission_id,
                    deferrals=normalized,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            deferred_ids = {item.obligation_id for item in normalized}
            action = current["next_action"]
            if (
                action.get("kind") == "resolve_historical_replay_obligations"
                and set(action.get("replay_obligation_ids", ())) == deferred_ids
                and isinstance(action.get("resume_next_action"), dict)
            ):
                action = action["resume_next_action"]
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                action, constraints
            )
            return body, records, result

        return self._commit(
            event_kind="historical_replay_obligations_deferred",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "deferrals": [item.to_identity_payload() for item in normalized]
            },
            prepare=prepare,
        )

    def return_historical_replay_obligations_for_scientific_change(
        self,
        *,
        obligation_ids: Sequence[str],
        operation_id: str,
    ) -> TransitionResult:
        """Restore an exact stopped family after a typed Study-level change."""

        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_scientific_change_return,
        )

        normalized = tuple(sorted(set(obligation_ids)))
        if (
            not normalized
            or len(normalized) != len(obligation_ids)
            or any(type(item) is not str for item in normalized)
        ):
            raise TransitionError(
                "scientific-change replay return request is invalid"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "scientific-change replay return requires control"
                )
            mission_id = current["scientific"].get("active_mission")
            next_action = current.get("next_action")
            if not isinstance(mission_id, str) or not isinstance(
                next_action, dict
            ):
                raise TransitionError(
                    "scientific-change replay return requires an active Mission"
                )
            try:
                records, constraints, result = prepare_scientific_change_return(
                    index,
                    mission_id=mission_id,
                    next_action=next_action,
                    obligation_ids=normalized,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            resume_next_action = next_action.get("resume_next_action")
            if not isinstance(resume_next_action, dict):
                raise RecoveryRequired(
                    "scientific-change replay return lost its resume action"
                )
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                resume_next_action,
                constraints,
            )
            return body, records, result

        return self._commit(
            event_kind=(
                "historical_replay_obligations_returned_for_scientific_change"
            ),
            operation_id=operation_id,
            subject="Mission:active",
            payload={"replay_obligation_ids": list(normalized)},
            prepare=prepare,
        )

    def dispose_historical_replay_obligations(
        self,
        *,
        satisfactions: Sequence[Any],
        deferrals: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Atomically satisfy completed members and defer unresolved peers."""

        from axiom_rift.research.replay_obligation import (
            ReplayDeferral,
            ReplaySatisfaction,
        )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_disposition,
        )

        normalized_satisfactions = tuple(
            sorted(
                satisfactions,
                key=lambda item: getattr(item, "obligation_id", ""),
            )
        )
        normalized_deferrals = tuple(
            sorted(
                deferrals,
                key=lambda item: getattr(item, "obligation_id", ""),
            )
        )
        satisfaction_ids = {
            item.obligation_id
            for item in normalized_satisfactions
            if isinstance(item, ReplaySatisfaction)
        }
        deferral_ids = {
            item.obligation_id
            for item in normalized_deferrals
            if isinstance(item, ReplayDeferral)
        }
        if (
            not normalized_satisfactions
            or not normalized_deferrals
            or len(satisfaction_ids) != len(normalized_satisfactions)
            or len(deferral_ids) != len(normalized_deferrals)
            or satisfaction_ids.intersection(deferral_ids)
        ):
            raise TransitionError("mixed replay disposition request is invalid")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("mixed replay disposition requires control")
            mission_id = current["scientific"].get("active_mission")
            next_action = current.get("next_action")
            if not isinstance(mission_id, str) or not isinstance(
                next_action,
                dict,
            ):
                raise TransitionError(
                    "mixed replay disposition requires an active Mission"
                )
            try:
                records, constraints, result = prepare_disposition(
                    index,
                    mission_id=mission_id,
                    next_action=next_action,
                    satisfactions=normalized_satisfactions,
                    deferrals=normalized_deferrals,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                next_action["resume_next_action"],
                constraints,
            )
            return body, records, result

        return self._commit(
            event_kind="historical_replay_obligations_disposed",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "deferrals": [
                    item.to_identity_payload()
                    for item in normalized_deferrals
                ],
                "satisfactions": [
                    item.to_identity_payload()
                    for item in normalized_satisfactions
                ],
            },
            prepare=prepare,
        )

    def resume_historical_replay_obligations(
        self,
        *,
        resumes: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Requeue exact deferred replay after one stored finite trigger."""

        from axiom_rift.research.replay_obligation import (
            ReplayRepairBasisKind,
            ReplayRepairProvenance,
            ReplayResumeEvidence,
        )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            prepare_resume,
            scheduler_constraints,
        )

        normalized = tuple(
            sorted(resumes, key=lambda item: getattr(item, "obligation_id", ""))
        )
        if (
            not normalized
            or any(not isinstance(item, ReplayResumeEvidence) for item in normalized)
            or len({item.obligation_id for item in normalized}) != len(normalized)
        ):
            raise TransitionError("replay resume request is invalid")
        self._require_study_close_delivery_guard()

        def repair_provenance(
            index: LocalIndex,
            previous_completion: IndexRecord,
            previous_declaration: IndexRecord,
            declaration: IndexRecord,
            diagnosis: IndexRecord,
        ) -> ReplayRepairProvenance:
            previous_spec = previous_declaration.payload.get("spec")
            spec = declaration.payload.get("spec")
            failure = previous_completion.payload.get("failure")
            if not isinstance(previous_spec, Mapping) or not isinstance(spec, Mapping):
                raise TransitionError(
                    "replay repair Job provenance is malformed"
                )
            previous_manifest = self._require_job_implementation_evidence(
                previous_spec,
                _index=index,
            )
            repaired_manifest = self._require_job_implementation_evidence(
                spec,
                _index=index,
            )
            changed_proof = spec.get("changed_cause_proof_hash")
            if not isinstance(changed_proof, str):
                raise TransitionError(
                    "replay repair changed-cause provenance is absent"
                )
            _require_digest("replay changed-cause proof", changed_proof)
            try:
                changed_manifest = parse_canonical(
                    self.evidence.read_verified(changed_proof)
                )
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "replay repair changed-cause proof is unavailable"
                ) from exc
            previous_identity = previous_spec.get("implementation_identity")
            repaired_identity = spec.get("implementation_identity")
            new_evidence = (
                None
                if not isinstance(changed_manifest, Mapping)
                else changed_manifest.get("new_evidence_hashes")
            )
            common_invalid = (
                not isinstance(changed_manifest, Mapping)
                or changed_manifest.get("changed_dimension") != "implementation"
                or changed_manifest.get("previous_implementation_identity")
                != previous_identity
                or changed_manifest.get("new_implementation_identity")
                != repaired_identity
                or previous_identity == repaired_identity
                or type(changed_manifest.get("explanation")) is not str
                or not changed_manifest["explanation"]
                or not changed_manifest["explanation"].isascii()
                or not isinstance(new_evidence, list)
                or not new_evidence
                or any(type(item) is not str for item in new_evidence)
                or len(new_evidence) != len(set(new_evidence))
                or repaired_identity not in new_evidence
                or previous_spec.get("changed_cause_proof_hash") == changed_proof
            )
            basis_kind: ReplayRepairBasisKind
            failure_signature: str | None
            invalid_criterion_ids: tuple[str, ...]
            prior_reproduction: set[str]
            if previous_completion.status == "failed":
                reproduction = (
                    None
                    if not isinstance(failure, Mapping)
                    else failure.get("minimum_reproduction_evidence")
                )
                failure_signature = (
                    None
                    if not isinstance(failure, Mapping)
                    else failure.get("failure_signature")
                )
                legacy_changed_cause_fields = {
                    "changed_dimension",
                    "explanation",
                    "new_evidence_hashes",
                    "new_implementation_identity",
                    "prior_failure_signature",
                    "previous_implementation_identity",
                    "schema",
                }
                validated_changed_cause_fields = {
                    *legacy_changed_cause_fields,
                    "result_artifact_hashes",
                    "validation_plan_hash",
                    "validator_id",
                }
                changed_cause_fields = (
                    frozenset(changed_manifest)
                    if isinstance(changed_manifest, Mapping)
                    else frozenset()
                )
                production_retry_family = declaration.payload.get(
                    "retry_family_fingerprint"
                )
                retry_basis_record_ids = declaration.payload.get(
                    "retry_basis_record_ids"
                )
                if (
                    common_invalid
                    or changed_cause_fields
                    not in {
                        frozenset(legacy_changed_cause_fields),
                        frozenset(validated_changed_cause_fields),
                    }
                    or (
                        isinstance(production_retry_family, str)
                        and (
                            changed_cause_fields
                            != validated_changed_cause_fields
                            or not isinstance(retry_basis_record_ids, list)
                            or len(retry_basis_record_ids) != 1
                            or type(retry_basis_record_ids[0]) is not str
                        )
                    )
                    or changed_manifest.get("schema") != "job_changed_cause.v1"
                    or not isinstance(failure_signature, str)
                    or changed_manifest.get("prior_failure_signature")
                    != failure_signature
                    or not isinstance(reproduction, list)
                    or any(type(item) is not str for item in reproduction)
                    or changed_proof in reproduction
                ):
                    raise TransitionError(
                        "replay repair changed-cause proof does not bind the exact failure"
                    )
                if changed_cause_fields == validated_changed_cause_fields:
                    validation_plan_hash = changed_manifest.get(
                        "validation_plan_hash"
                    )
                    validation_results = changed_manifest.get(
                        "result_artifact_hashes"
                    )
                    validator_id = changed_manifest.get("validator_id")
                    if (
                        type(validation_plan_hash) is not str
                        or not isinstance(validation_results, list)
                        or not validation_results
                        or validation_results
                        != sorted(set(validation_results))
                        or any(
                            type(item) is not str
                            for item in validation_results
                        )
                        or validation_plan_hash in validation_results
                        or type(validator_id) is not str
                        or not validator_id.startswith("validator:")
                    ):
                        raise TransitionError(
                            "replay repair engineering validation binding is malformed"
                        )
                    _require_digest(
                        "replay repair engineering validation plan",
                        validation_plan_hash,
                    )
                    _require_digest(
                        "replay repair engineering validator",
                        validator_id.removeprefix("validator:"),
                    )
                    for validation_hash in (
                        validation_plan_hash,
                        *validation_results,
                    ):
                        try:
                            self.evidence.verify(validation_hash)
                        except (
                            FileNotFoundError,
                            OSError,
                            RuntimeError,
                            ValueError,
                        ) as exc:
                            raise TransitionError(
                                "replay repair engineering validation evidence is unavailable"
                            ) from exc
                _require_digest(
                    "replay prior failure signature", failure_signature
                )
                basis_kind = ReplayRepairBasisKind.OPERATIONAL_FAILURE
                invalid_criterion_ids = ()
                prior_reproduction = set(reproduction)
            elif previous_completion.status == "success":
                raw_invalid = (
                    None
                    if not isinstance(changed_manifest, Mapping)
                    else changed_manifest.get("invalid_criterion_ids")
                )
                if (
                    common_invalid
                    or set(changed_manifest) != {
                        "changed_dimension",
                        "explanation",
                        "invalid_criterion_ids",
                        "new_evidence_hashes",
                        "new_implementation_identity",
                        "previous_implementation_identity",
                        "prior_completion_record_id",
                        "schema",
                        "study_diagnosis_id",
                        "validation_plan_hash",
                    }
                    or changed_manifest.get("schema")
                    != "replay_scientific_repair.v1"
                    or changed_manifest.get("prior_completion_record_id")
                    != previous_completion.record_id
                    or changed_manifest.get("study_diagnosis_id")
                    != diagnosis.record_id
                    or not isinstance(raw_invalid, list)
                    or not raw_invalid
                    or any(type(item) is not str for item in raw_invalid)
                    or len(raw_invalid) != len(set(raw_invalid))
                ):
                    raise TransitionError(
                        "replay scientific repair proof does not bind exact invalid evidence"
                    )
                basis_kind = ReplayRepairBasisKind.SCIENTIFIC_INVALIDITY
                failure_signature = None
                invalid_criterion_ids = tuple(sorted(raw_invalid))
                prior_reproduction = set()
            else:
                raise TransitionError(
                    "replay repair basis is neither failed nor scientifically invalid"
                )
            if (
                not isinstance(changed_manifest, Mapping)
                or not isinstance(new_evidence, list)
            ):
                raise TransitionError(
                    "replay repair changed-cause proof is malformed"
                )
            for evidence_hash in new_evidence:
                _require_digest("replay changed-cause evidence", evidence_hash)
                try:
                    self.evidence.verify(evidence_hash)
                except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                    raise TransitionError(
                        "replay repair changed-cause evidence is unavailable"
                    ) from exc
                if evidence_hash in prior_reproduction:
                    raise TransitionError(
                        "replay repair reuses prior failure reproduction evidence"
                    )
            if any(
                artifact_hash not in new_evidence
                for artifact_hash in repaired_manifest["artifact_hashes"]
            ):
                raise TransitionError(
                    "replay repair proof omits implementation artifact bytes"
                )
            protocol = repaired_manifest.get("protocol")
            if previous_manifest.get("protocol") != protocol:
                raise TransitionError(
                    "replay repair changes its implementation protocol"
                )
            scientific_binding = spec.get("scientific_binding")
            if (
                not isinstance(scientific_binding, Mapping)
                or scientific_binding != previous_spec.get("scientific_binding")
            ):
                raise TransitionError(
                    "replay repair changes its scientific binding"
                )
            plan_hash = scientific_binding.get("validation_plan_hash")
            if not isinstance(plan_hash, str):
                raise TransitionError(
                    "replay repair validation plan is absent"
                )
            _require_digest("replay repair validation plan", plan_hash)
            try:
                plan = parse_canonical(self.evidence.read_verified(plan_hash))
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "replay repair validation plan is unavailable"
                ) from exc
            criteria = None if not isinstance(plan, Mapping) else plan.get("criteria")
            evidence_subject = spec.get("evidence_subject")
            criterion_ids = (
                ()
                if not isinstance(criteria, list)
                else tuple(
                    item.get("criterion_id")
                    for item in criteria
                    if isinstance(item, Mapping)
                )
            )
            if (
                not isinstance(plan, Mapping)
                or plan.get("schema") != "scientific_validation_plan.v2"
                or plan.get("mission_id") != declaration.payload.get("mission_id")
                or not isinstance(evidence_subject, Mapping)
                or plan.get("executable_id") != evidence_subject.get("id")
                or not criterion_ids
                or len(criterion_ids) != len(criteria)
                or any(type(item) is not str for item in criterion_ids)
                or len(criterion_ids) != len(set(criterion_ids))
                or any(item not in criterion_ids for item in invalid_criterion_ids)
                or (
                    basis_kind is ReplayRepairBasisKind.SCIENTIFIC_INVALIDITY
                    and changed_manifest.get("validation_plan_hash") != plan_hash
                )
            ):
                raise TransitionError(
                    "replay repair validation plan is not subject-bound"
                )
            return ReplayRepairProvenance(
                basis_kind=basis_kind,
                prior_completion_record_id=previous_completion.record_id,
                study_diagnosis_id=diagnosis.record_id,
                protocol_id=protocol,
                validation_plan_hash=plan_hash,
                criterion_ids=tuple(criterion_ids),
                previous_implementation_identity=previous_identity,
                repaired_implementation_identity=repaired_identity,
                changed_cause_proof_hash=changed_proof,
                prior_failure_signature=failure_signature,
                invalid_criterion_ids=invalid_criterion_ids,
                new_evidence_hashes=tuple(new_evidence),
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("replay resume requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            next_action = current.get("next_action")
            if (
                not isinstance(mission_id, str)
                or not isinstance(next_action, dict)
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
                or next_action.get("kind")
                in {
                    "close_mission",
                    "diagnose_study",
                    "resolve_historical_replay_obligations",
                    "review_architecture",
                }
            ):
                raise TransitionError(
                    "replay resume requires a stable schedulable Mission boundary"
                )
            current_constraints = scheduler_constraints(
                index, mission_id=mission_id
            )
            projected_constraints = {
                name: next_action.get(name)
                for name in (
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                )
                if next_action.get(name) is not None
            }
            if projected_constraints != (current_constraints or {}):
                raise TransitionError(
                    "replay resume scheduler authority is absent or stale"
                )
            try:
                records, constraints, result = prepare_resume(
                    index,
                    mission_id=mission_id,
                    resumes=normalized,
                    repair_provenance=(
                        lambda *items: repair_provenance(index, *items)
                    ),
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = self._with_replay_scheduler_constraints(
                next_action, constraints
            )
            return body, records, result

        return self._commit(
            event_kind="historical_replay_obligations_resumed",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "resumes": [item.to_identity_payload() for item in normalized]
            },
            prepare=prepare,
        )

    def record_historical_scientific_adjudications(
        self,
        *,
        requests: Sequence[Any],
        audit_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Add claim-scoped interpretations without rewriting legacy evidence."""

        from axiom_rift.research.historical_adjudication import (
            HistoricalAdjudicationRequest,
            HistoricalScientificAdjudication,
            ReplayPriority,
            derive_historical_adjudication,
            profile_manifest,
        )
        from axiom_rift.research.adjudication import AdjudicationProfile
        from axiom_rift.research.replay_obligation import (
            ReplayObligationStatus,
            ReplayPriorityEscalation,
            derive_historical_replay_obligation,
        )
        from axiom_rift.operations.completion_validity_projection import (
            CompletionValidityProjectionError,
            current_completion_validity_invalidation,
        )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            build_satisfaction_invalidation_plan,
            constraints_for_pending,
            effective_replay_priority,
            initial_obligation_record,
            replay_priority_escalation_record,
            replay_priority_stream,
        )

        _require_digest("historical audit artifact", audit_artifact_hash)
        self.evidence.verify(audit_artifact_hash)
        normalized = tuple(requests)
        if (
            not normalized
            or any(
                not isinstance(item, HistoricalAdjudicationRequest)
                for item in normalized
            )
            or len({item.completion_record_id for item in normalized})
            != len(normalized)
        ):
            raise TransitionError(
                "historical adjudication requires unique typed completion requests"
            )
        normalized = tuple(
            sorted(normalized, key=lambda item: item.completion_record_id)
        )
        request_manifest = [
            {
                "completion_record_id": item.completion_record_id,
                "disposition": item.disposition.value,
                "profile": profile_manifest(item.profile),
                "reason_codes": list(item.reason_codes),
                "replay_priority": item.replay_priority.value,
                "validity_overrides": [
                    override.manifest() for override in item.validity_overrides
                ],
            }
            for item in normalized
        ]
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("historical adjudication requires control")
            science = current["scientific"]
            if (
                not isinstance(science.get("active_mission"), str)
                or not isinstance(science.get("active_initiative"), str)
                or current.get("next_action", {}).get("kind")
                != "portfolio_decision"
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "historical adjudication requires the active stable Portfolio boundary"
                )

            memory_by_subject: dict[tuple[str, str], list[str]] = {}
            for memory in index.records_by_kind("negative-memory"):
                study_id = memory.payload.get("study_id")
                executable_id = memory.subject.removeprefix("Executable:")
                if isinstance(study_id, str) and isinstance(executable_id, str):
                    memory_by_subject.setdefault(
                        (study_id, executable_id), []
                    ).append(memory.record_id)

            obligation_heads = self._historical_replay_obligation_heads(
                index,
                mission_id=science["active_mission"],
            )
            obligation_by_completion: dict[str, tuple[Any, IndexRecord]] = {}
            for obligation, obligation_head in obligation_heads:
                previous = obligation_by_completion.setdefault(
                    obligation.original_completion_record_id,
                    (obligation, obligation_head),
                )
                if previous != (obligation, obligation_head):
                    raise RecoveryRequired(
                        "historical completion has duplicate replay obligations"
                    )

            records: list[IndexRecord] = []
            derived: list[HistoricalScientificAdjudication] = []
            new_replay_obligations: list[Any] = []
            reused_replay_obligation_ids: list[str] = []
            priority_escalations: list[ReplayPriorityEscalation] = []
            for request in normalized:
                new_priority_escalation: ReplayPriorityEscalation | None = None
                completion = index.get(
                    "job-completed", request.completion_record_id
                )
                scientific = (
                    None
                    if completion is None
                    else completion.payload.get("scientific")
                )
                declaration = (
                    None
                    if completion is None
                    else index.get(
                        "job-declared", completion.payload.get("job_id", "")
                    )
                )
                if (
                    completion is None
                    or completion.status not in {
                        "failed",
                        "not_evaluable",
                        "success",
                    }
                    or not isinstance(scientific, dict)
                    or declaration is None
                ):
                    raise TransitionError(
                        "historical adjudication completion is unavailable"
                    )
                if "adjudication" in scientific:
                    raise TransitionError(
                        "historical adjudication is restricted to legacy completions "
                        "without rich v2 adjudication"
                    )
                study_id = declaration.payload.get("study_id")
                executable_id = scientific.get("executable_id")
                plan_hash = scientific.get("validation_plan_hash")
                measurement_hashes = scientific.get(
                    "measurement_artifact_hashes"
                )
                verdict = scientific.get("verdict")
                if (
                    not isinstance(study_id, str)
                    or not isinstance(executable_id, str)
                    or not isinstance(plan_hash, str)
                    or not isinstance(measurement_hashes, list)
                    or len(measurement_hashes) != 1
                    or not isinstance(measurement_hashes[0], str)
                    or verdict not in {"passed", "failed", "not_evaluable"}
                ):
                    raise TransitionError(
                        "historical adjudication scientific provenance is malformed"
                    )
                measurement_hash = measurement_hashes[0]
                _require_digest("historical validation plan", plan_hash)
                _require_digest("historical measurement", measurement_hash)
                outputs = completion.payload.get("outputs")
                spec = declaration.payload.get("spec")
                if (
                    not isinstance(outputs, dict)
                    or plan_hash not in outputs.values()
                    or measurement_hash not in outputs.values()
                    or not isinstance(spec, dict)
                    or plan_hash not in spec.get("input_hashes", [])
                ):
                    raise TransitionError(
                        "historical adjudication artifacts are not completion-bound"
                    )
                try:
                    plan = parse_canonical(self.evidence.read_verified(plan_hash))
                    measurement = parse_canonical(
                        self.evidence.read_verified(measurement_hash)
                    )
                except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                    raise TransitionError(
                        "historical adjudication evidence is unavailable"
                    ) from exc
                if not isinstance(plan, dict) or not isinstance(measurement, dict):
                    raise TransitionError(
                        "historical adjudication evidence is not a mapping"
                    )
                if (
                    plan.get("schema") != "scientific_validation_plan.v1"
                    or measurement.get("schema") != "scientific_measurement.v1"
                ):
                    raise TransitionError(
                        "historical adjudication requires exact legacy v1 artifacts"
                    )
                if (
                    plan.get("executable_id") != executable_id
                    or measurement.get("executable_id") != executable_id
                    or plan.get("mission_id")
                    != declaration.payload.get("mission_id")
                    or measurement.get("mission_id")
                    != declaration.payload.get("mission_id")
                ):
                    raise TransitionError(
                        "historical adjudication subject binding is invalid"
                    )
                fixed_profile = AdjudicationProfile()
                if request.profile != fixed_profile:
                    raise TransitionError(
                        "historical adjudication profile differs from the "
                        "Writer-derived fixed legacy audit profile"
                    )
                stream = f"historical-adjudication:{completion.record_id}"
                head = index.event_head(stream)
                prior = (
                    None
                    if head is None
                    else index.get(head.record_kind, head.record_id)
                )
                if head is not None and (
                    prior is None
                    or prior.kind != "historical-scientific-adjudication"
                    or prior.event_stream != stream
                    or prior.event_sequence != head.sequence
                ):
                    raise RecoveryRequired(
                        "historical adjudication stream head is malformed"
                    )
                derived_overrides = (
                    self._writer_derived_historical_validity_overrides(
                        index,
                        completion_record_id=completion.record_id,
                        executable_id=executable_id,
                        declaration=declaration,
                        prior=prior,
                    )
                )
                if request.validity_overrides != derived_overrides:
                    raise TransitionError(
                        "historical validity overrides differ from "
                        "Writer-derived durable invalidity heads"
                    )
                study = index.get("study-open", study_id)
                close_records = tuple(
                    record
                    for outcome in _STUDY_OUTCOMES
                    for record in index.records_by_subject_status(
                        f"Study:{study_id}", outcome
                    )
                    if record.kind == "study-close"
                )
                if study is None or len(close_records) != 1:
                    raise TransitionError(
                        "historical adjudication Study close is unavailable"
                    )
                close = close_records[0]
                try:
                    item = derive_historical_adjudication(
                        audit_artifact_hash=audit_artifact_hash,
                        study_id=study_id,
                        study_close_record_id=close.record_id,
                        completion_record_id=completion.record_id,
                        executable_id=executable_id,
                        validation_plan_hash=plan_hash,
                        measurement_artifact_hash=measurement_hash,
                        original_job_status=completion.status,
                        original_scientific_verdict=verdict,
                        plan=plan,
                        measurement=measurement,
                        request=request,
                        negative_memory_ids=tuple(
                            memory_by_subject.get(
                                (study_id, executable_id), ()
                            )
                        ),
                    )
                except ValueError as exc:
                    raise TransitionError(
                        "historical adjudication derivation failed"
                    ) from exc
                if item.adjudication.legacy_verdict != verdict:
                    raise TransitionError(
                        "historical adjudication does not reproduce the legacy verdict"
                    )
                sequence = 1 if head is None else head.sequence + 1
                prior_record_id = None if head is None else head.record_id
                payload = {
                    **item.to_identity_payload(),
                    "supersedes_record_id": prior_record_id,
                    "trial_delta": 0,
                    "holdout_delta": 0,
                    "candidate_delta": 0,
                    "claim_authority": "additive_qualification_only",
                    "profile_authority": "writer_derived_fixed_legacy_v1",
                    "validity_override_authority": (
                        "writer_derived_durable_invalidity_heads"
                    ),
                }
                new_obligation_record: IndexRecord | None = None
                if item.disposition.value == "replay_required":
                    existing = obligation_by_completion.get(
                        completion.record_id
                    )
                    if existing is not None:
                        obligation, obligation_head = existing
                        cursor = prior
                        found_origin = False
                        seen_adjudications: set[str] = set()
                        while cursor is not None:
                            if cursor.record_id in seen_adjudications:
                                raise RecoveryRequired(
                                    "historical adjudication supersession is cyclic"
                                )
                            seen_adjudications.add(cursor.record_id)
                            if (
                                cursor.record_id
                                == obligation.historical_adjudication_id
                            ):
                                found_origin = True
                                break
                            superseded_id = cursor.payload.get(
                                "supersedes_record_id"
                            )
                            if superseded_id is None:
                                cursor = None
                            elif not isinstance(superseded_id, str):
                                raise RecoveryRequired(
                                    "historical adjudication supersession is malformed"
                                )
                            else:
                                cursor = index.get(
                                    "historical-scientific-adjudication",
                                    superseded_id,
                                )
                        if (
                            not found_origin
                            or obligation.original_executable_id != executable_id
                            or obligation.original_study_id != study_id
                            or obligation.original_study_close_record_id
                            != close.record_id
                            or obligation.governing_mission_id
                            != science["active_mission"]
                        ):
                            raise RecoveryRequired(
                                "historical replay obligation is outside the "
                                "adjudication supersession lineage"
                            )
                        payload["replay_obligation_id"] = obligation.identity
                        payload["replay_obligation_origin_adjudication_id"] = (
                            obligation.historical_adjudication_id
                        )
                        payload["replay_obligation_authority"] = (
                            "reused_existing_lineage"
                        )
                        reused_replay_obligation_ids.append(obligation.identity)
                        try:
                            current_effective_priority = effective_replay_priority(
                                index, obligation
                            )
                        except ReplayProjectionError as exc:
                            raise RecoveryRequired(str(exc)) from exc
                        if item.replay_priority is current_effective_priority:
                            pass
                        elif (
                            obligation.replay_priority is ReplayPriority.P1
                            and current_effective_priority is ReplayPriority.P1
                            and item.replay_priority is ReplayPriority.P0
                        ):
                            if (
                                "accepted_replay_satisfaction_revocation_pending"
                                not in item.reason_codes
                                or obligation_head.status
                                != ReplayObligationStatus.SATISFIED.value
                                or obligation_head.kind
                                != "historical-replay-obligation-resolution"
                                or not obligation_head.record_id.startswith(
                                    "historical-replay-satisfaction:"
                                )
                                or obligation_head.payload.get("obligation_id")
                                != obligation.identity
                            ):
                                raise TransitionError(
                                    "replay priority escalation requires the exact "
                                    "accepted satisfaction pending revocation"
                                )
                            try:
                                invalidation = (
                                    current_completion_validity_invalidation(
                                        index,
                                        completion.record_id,
                                    )
                                )
                            except CompletionValidityProjectionError as exc:
                                raise RecoveryRequired(
                                    "replay priority escalation completion "
                                    "validity is malformed"
                                ) from exc
                            if invalidation is None:
                                raise TransitionError(
                                    "replay priority escalation requires the "
                                    "current completion invalidation"
                                )
                            try:
                                invalidation_plan = (
                                    build_satisfaction_invalidation_plan(
                                        index,
                                        mission_id=science["active_mission"],
                                        obligation_id=obligation.identity,
                                    )
                                )
                            except ReplayProjectionError as exc:
                                raise RecoveryRequired(str(exc)) from exc
                            except ReplayTransitionError as exc:
                                raise TransitionError(str(exc)) from exc
                            audit_manifest = invalidation_plan.get(
                                "audit_manifest"
                            )
                            if (
                                invalidation_plan.get("schema")
                                != "replay_satisfaction_invalidation_plan.v1"
                                or invalidation_plan.get("operation")
                                != "invalidate_historical_replay_satisfaction"
                                or not isinstance(audit_manifest, dict)
                                or audit_manifest.get("obligation_id")
                                != obligation.identity
                                or audit_manifest.get("satisfaction_record_id")
                                != obligation_head.record_id
                                or audit_manifest.get("governing_mission_id")
                                != science["active_mission"]
                            ):
                                raise RecoveryRequired(
                                    "replay priority escalation invalidation "
                                    "plan is not exact"
                                )
                            if index.event_head(
                                replay_priority_stream(obligation.identity)
                            ) is not None:
                                raise RecoveryRequired(
                                    "replay priority escalation already exists"
                                )
                            try:
                                escalation = ReplayPriorityEscalation(
                                    governing_mission_id=science["active_mission"],
                                    obligation_id=obligation.identity,
                                    superseding_historical_adjudication_id=(
                                        item.identity
                                    ),
                                    completion_validity_invalidation_id=(
                                        invalidation.invalidation_record_id
                                    ),
                                    accepted_satisfaction_record_id=(
                                        obligation_head.record_id
                                    ),
                                    audit_artifact_hash=audit_artifact_hash,
                                    reason_codes=item.reason_codes,
                                )
                            except ValueError as exc:
                                raise RecoveryRequired(
                                    "replay priority escalation derivation failed"
                                ) from exc
                            new_priority_escalation = escalation
                            priority_escalations.append(escalation)
                        else:
                            raise TransitionError(
                                "an immutable replay obligation priority cannot "
                                "be demoted or otherwise rewritten"
                            )
                    else:
                        if prior is not None and prior.status == "replay_required":
                            raise RecoveryRequired(
                                "prior replay adjudication lost its obligation"
                            )
                        try:
                            obligation = derive_historical_replay_obligation(
                                governing_mission_id=science["active_mission"],
                                historical_adjudication_id=item.identity,
                                adjudication_payload=item.to_identity_payload(),
                            )
                        except ValueError as exc:
                            raise RecoveryRequired(
                                "derived historical replay obligation is malformed"
                            ) from exc
                        if index.get(
                            "historical-replay-obligation", obligation.identity
                        ) is not None:
                            raise RecoveryRequired(
                                "historical replay obligation identity already exists"
                            )
                        payload["replay_obligation_id"] = obligation.identity
                        payload["replay_obligation_origin_adjudication_id"] = (
                            item.identity
                        )
                        payload["replay_obligation_authority"] = "derived_new"
                        new_obligation_record = initial_obligation_record(
                            obligation
                        )
                        new_replay_obligations.append(obligation)
                records.append(
                    _record(
                        kind="historical-scientific-adjudication",
                        record_id=item.identity,
                        subject=f"Study:{study_id}",
                        status=item.disposition.value,
                        fingerprint=item.identity.removeprefix(
                            "historical-adjudication:"
                        ),
                        payload=payload,
                        event_stream=stream,
                        event_sequence=sequence,
                    )
                )
                if new_obligation_record is not None:
                    records.append(new_obligation_record)
                if new_priority_escalation is not None:
                    records.append(
                        replay_priority_escalation_record(
                            new_priority_escalation
                        )
                    )
                derived.append(item)
            body = self._body(current)
            existing_pending = [
                obligation
                for obligation, head in obligation_heads
                if head.status == "pending"
            ]
            combined_pending = [*existing_pending, *new_replay_obligations]
            try:
                effective_priorities = {
                    obligation.identity: effective_replay_priority(
                        index, obligation
                    )
                    for obligation in existing_pending
                }
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            effective_priorities.update(
                {
                    obligation.identity: obligation.replay_priority
                    for obligation in new_replay_obligations
                }
            )
            replay_constraints = constraints_for_pending(
                combined_pending,
                effective_priorities=effective_priorities,
            )
            if replay_constraints is not None:
                body["next_action"] = self._with_replay_scheduler_constraints(
                    body["next_action"],
                    replay_constraints,
                )
            return body, records, {
                "adjudication_record_ids": [item.identity for item in derived],
                "replay_obligation_ids": [
                    item.identity for item in new_replay_obligations
                ],
                "reused_replay_obligation_ids": sorted(
                    reused_replay_obligation_ids
                ),
                "replay_priority_escalation_ids": sorted(
                    item.identity for item in priority_escalations
                ),
                "audit_artifact_hash": audit_artifact_hash,
                "candidate_delta": 0,
                "holdout_delta": 0,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="historical_scientific_adjudications_recorded",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "audit_artifact_hash": audit_artifact_hash,
                "requests": request_manifest,
            },
            prepare=prepare,
        )

