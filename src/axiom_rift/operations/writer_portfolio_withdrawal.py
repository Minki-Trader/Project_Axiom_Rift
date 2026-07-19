"""Pre-execution Portfolio Decision withdrawal transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.diagnosis_authority_context import (
    DiagnosisAuthorityContext,
    DiagnosisAuthorityContextError,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _record,
    _require_digest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class PortfolioWithdrawalWriterMixin:
    """Own typed Decision withdrawal; the facade commits atomically."""

    @staticmethod
    def _portfolio_decision_withdrawal(
        index: LocalIndex,
        decision_id: str,
    ) -> IndexRecord | None:
        stream = f"portfolio-decision-status:{decision_id}"
        head = index.event_head(stream)
        if head is None:
            return None
        record = index.get(head.record_kind, head.record_id)
        if (
            record is None
            or record.kind != "portfolio-decision-withdrawal"
            or record.status != "withdrawn_pre_execution"
            or record.event_stream != stream
            or record.event_sequence != 1
            or head.sequence != 1
            or record.payload.get("decision_id") != decision_id
        ):
            raise RecoveryRequired(
                "Portfolio Decision withdrawal status projection is invalid"
            )
        return record

    @staticmethod
    def _active_portfolio_decision(
        index: LocalIndex,
        decision_id: str,
    ) -> IndexRecord | None:
        decision = index.get("portfolio-decision", decision_id)
        withdrawal = PortfolioWithdrawalWriterMixin._portfolio_decision_withdrawal(index, decision_id)
        if withdrawal is None:
            return decision
        if (
            decision is None
            or withdrawal.subject != decision.subject
            or withdrawal.fingerprint != decision.fingerprint
        ):
            raise RecoveryRequired(
                "withdrawn Portfolio Decision lost its accepted provenance"
            )
        return None

    def withdraw_pending_portfolio_decision(
        self,
        *,
        manifest_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Withdraw an accepted but unstarted Decision whose basis was invalidated."""

        from axiom_rift.research.decision_withdrawal import (
            PortfolioDecisionWithdrawalManifest,
            PortfolioDecisionWithdrawalReason,
        )
        from axiom_rift.operations.architecture_review_direction import (
            ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
            ArchitectureReviewDirectionError,
            constraint_from_action,
            require_review_binding,
        )

        _require_digest(
            "Portfolio Decision withdrawal manifest",
            manifest_artifact_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(manifest_artifact_hash)
            manifest = PortfolioDecisionWithdrawalManifest.from_bytes(manifest_bytes)
            report_bytes = self.evidence.read_verified(manifest.report_artifact_hash)
            manifest.require_report(report_bytes)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "Portfolio Decision withdrawal lacks its exact canonical manifest"
            ) from exc
        if (
            manifest.reason_code
            is not PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
        ):
            raise TransitionError("Portfolio Decision withdrawal reason is unsupported")

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Portfolio Decision withdrawal requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            initiative_id = science.get("active_initiative")
            if type(mission_id) is not str or type(initiative_id) is not str:
                raise TransitionError(
                    "Portfolio Decision withdrawal requires active Mission work"
                )
            if any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal cannot bypass started work"
                )
            next_action = current.get("next_action")
            decision = index.get("portfolio-decision", manifest.decision_id)
            if (
                self._portfolio_decision_withdrawal(
                    index,
                    manifest.decision_id,
                )
                is not None
            ):
                raise TransitionError("Portfolio Decision is already withdrawn")
            if (
                not isinstance(next_action, dict)
                or next_action.get("kind") != "execute_portfolio_decision"
                or next_action.get("decision_id") != manifest.decision_id
                or decision is None
                or decision.subject != f"Mission:{mission_id}"
                or decision.payload.get("portfolio_snapshot_id")
                != next_action.get("portfolio_snapshot_id")
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal is not the exact unstarted action"
                )
            snapshot = index.get(
                "portfolio-snapshot",
                manifest.portfolio_snapshot_id,
            )
            axes = (
                ()
                if snapshot is None
                else tuple(snapshot.payload.get("axes", ()))
            )
            target_axes = tuple(
                axis
                for axis in axes
                if isinstance(axis, dict)
                and axis.get("axis_id") == manifest.target_axis_id
            )
            resolvable_axes = tuple(
                axis
                for axis in axes
                if isinstance(axis, dict)
                and isinstance(axis.get("axis_id"), str)
            )
            axis_resolutions = self._effective_axis_resolutions(
                index,
                resolvable_axes,
            )
            eligible_axis_ids = {
                axis["axis_id"]
                for axis, resolution in zip(
                    resolvable_axes,
                    axis_resolutions,
                    strict=True,
                )
                if resolution.selectable
            }
            chosen_options = tuple(
                option
                for option in decision.payload.get("options", ())
                if isinstance(option, dict)
                and option.get("option_id")
                == decision.payload.get("chosen_option_id")
            )
            baseline = decision.payload.get("baseline_executable")
            if not isinstance(baseline, Mapping):
                raise RecoveryRequired(
                    "Portfolio Decision source authority baseline is malformed"
                )
            bound_sources = self._source_authority_subject_ids(
                baseline,
                error_type=RecoveryRequired,
            )
            recorded_bound_sources = decision.payload.get(
                "source_authority_subject_ids"
            )
            if (
                recorded_bound_sources is not None
                and recorded_bound_sources != list(bound_sources)
            ):
                raise RecoveryRequired(
                    "Portfolio Decision source authority projection is malformed"
                )
            source_head = index.event_head(
                f"source:{manifest.source_contract_id}"
            )
            source_state = (
                None
                if source_head is None
                else index.get(source_head.record_kind, source_head.record_id)
            )
            if (
                snapshot is None
                or snapshot.record_id != decision.payload.get("portfolio_snapshot_id")
                or len(target_axes) != 1
                or len(chosen_options) != 1
                or chosen_options[0].get("target_id") != manifest.target_axis_id
                or target_axes[0].get("axis_identity")
                != manifest.target_axis_identity
                or decision.payload.get("target_axis_identity")
                != manifest.target_axis_identity
                or next_action.get("target_id") != manifest.target_axis_id
                or next_action.get("target_axis_identity")
                != manifest.target_axis_identity
                or decision.payload.get("baseline_executable_id")
                != manifest.baseline_executable_id
                or (
                    next_action.get("baseline_executable_id") is not None
                    and next_action.get("baseline_executable_id")
                    != manifest.baseline_executable_id
                )
                or manifest.source_contract_id not in bound_sources
                or source_head is None
                or source_state is None
                or source_head.record_id != manifest.source_state_record_id
                or source_state.subject
                != f"Source:{manifest.source_contract_id}"
                or source_state.fingerprint != manifest.source_contract_id
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal manifest does not bind its exact basis"
                )
            try:
                durable_manifest_bytes = self.evidence.read_verified(
                    manifest_artifact_hash
                )
                durable_report_bytes = self.evidence.read_verified(
                    manifest.report_artifact_hash
                )
                durable_manifest = PortfolioDecisionWithdrawalManifest.from_bytes(
                    durable_manifest_bytes
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "Portfolio Decision withdrawal evidence changed before commit"
                ) from exc
            if (
                durable_manifest_bytes != manifest_bytes
                or durable_report_bytes != report_bytes
                or durable_manifest != manifest
            ):
                raise RecoveryRequired(
                    "Portfolio Decision withdrawal evidence changed before commit"
                )
            post_holdout_development_id, _ = (
                self._require_post_holdout_decision_binding(
                    index,
                    science=science,
                    decision=decision,
                    next_action=next_action,
                )
            )
            body = self._body(current)
            replacement_action: dict[str, Any] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": decision.payload["portfolio_snapshot_id"],
            }
            if isinstance(post_holdout_development_id, str):
                replacement_action["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            constraints = decision.payload.get("scheduler_constraints")
            if constraints is not None:
                allowed_constraint_fields = {
                    "constraint_source_id",
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                    "required_target_axis_ids",
                } | set(ARCHITECTURE_CONTINUATION_ACTION_FIELDS)
                if (
                    not isinstance(constraints, dict)
                    or not constraints
                    or not set(constraints).issubset(allowed_constraint_fields)
                ):
                    raise RecoveryRequired(
                        "withdrawn Decision scheduler constraints are malformed"
                    )
                required = constraints.get("required_target_axis_ids")
                source = constraints.get("constraint_source_id")
                if required is not None:
                    if (
                        not isinstance(required, list)
                        or not required
                        or required != sorted(set(required))
                        or any(type(item) is not str for item in required)
                        or any(item not in eligible_axis_ids for item in required)
                        or manifest.target_axis_id not in required
                    ):
                        raise RecoveryRequired(
                            "withdrawn Decision target constraints are malformed"
                        )
                    replacement_action["required_target_axis_ids"] = list(required)
                if source is not None:
                    if (
                        type(source) is not str
                        or not source
                        or not source.isascii()
                    ):
                        raise RecoveryRequired(
                            "withdrawn Decision constraint source is malformed"
                        )
                    replacement_action["constraint_source_id"] = source
                if required is not None and source is None:
                    raise RecoveryRequired(
                        "withdrawn Decision constrained axes lack their source"
                    )
                for name in ARCHITECTURE_CONTINUATION_ACTION_FIELDS:
                    if name in constraints:
                        value = constraints[name]
                        replacement_action[name] = (
                            list(value) if isinstance(value, list) else value
                        )
                replay_constraints = self._replay_scheduler_constraints(
                    index,
                    mission_id=mission_id,
                )
                stored_replay = {
                    name: constraints.get(name)
                    for name in (
                        "pending_replay_obligation_ids",
                        "required_replay_priority",
                    )
                    if constraints.get(name) is not None
                }
                if stored_replay != (replay_constraints or {}):
                    raise RecoveryRequired(
                        "withdrawn Decision replay constraints are stale"
                    )
                replacement_action.update(stored_replay)
            try:
                diagnosis_authority = DiagnosisAuthorityContext.from_mapping(
                    decision.payload
                )
                diagnosis_authority.require_effective(
                    index,
                    mission_id=mission_id,
                )
            except DiagnosisAuthorityContextError as exc:
                raise RecoveryRequired(str(exc)) from exc
            replacement_action.update(
                diagnosis_authority.to_action_fields()
            )
            review_id = decision.payload.get("architecture_review_id")
            if isinstance(review_id, str):
                review = index.get("architecture-review", review_id)
                if review is None or review.payload.get("mission_id") != mission_id:
                    raise RecoveryRequired(
                        "withdrawn Decision architecture review is unavailable"
                    )
                replacement_action["architecture_review_id"] = review_id
                conclusion = review.payload.get("conclusion")
                if conclusion == "bounded_same_architecture":
                    try:
                        continuation = constraint_from_action(replacement_action)
                    except ArchitectureReviewDirectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    trigger = (
                        None
                        if continuation is None
                        else index.get(
                            "architecture-review-trigger",
                            continuation.trigger_record_id,
                        )
                    )
                    if continuation is None or trigger is None:
                        raise RecoveryRequired(
                            "withdrawn bounded architecture direction is unavailable"
                        )
                    try:
                        require_review_binding(
                            continuation,
                            review_record_id=review.record_id,
                            review_payload=review.payload,
                            trigger_payload=trigger.payload,
                        )
                    except ArchitectureReviewDirectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                elif conclusion == "rotate_architecture":
                    replacement_action["excluded_architecture_family"] = (
                        self._review_resolved_architecture_family(
                            index=index,
                            review=review,
                        )
                    )
                elif conclusion == "change_research_layer":
                    replacement_action["excluded_research_layers"] = sorted(
                        review.payload.get("primary_research_layers", [])
                    )
                else:
                    raise RecoveryRequired(
                        "withdrawn Decision architecture review is malformed"
                    )
            body["next_action"] = replacement_action
            record_id = canonical_digest(
                domain="portfolio-decision-withdrawal",
                payload={
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                },
            )
            record = _record(
                kind="portfolio-decision-withdrawal",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status="withdrawn_pre_execution",
                fingerprint=decision.fingerprint,
                payload={
                    "decision_id": manifest.decision_id,
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                    "replacement_next_action": replacement_action,
                },
                event_stream=(
                    f"portfolio-decision-status:{manifest.decision_id}"
                ),
                event_sequence=1,
            )
            return body, [record], {
                "decision_id": manifest.decision_id,
                "withdrawal_record_id": record_id,
            }

        return self._commit(
            event_kind="portfolio_decision_withdrawn",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={
                "manifest": manifest.to_identity_payload(),
                "manifest_artifact_hash": manifest_artifact_hash,
            },
            prepare=prepare,
        )

    def withdraw_unbound_execution_plan_portfolio_decision(
        self,
        *,
        manifest_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Withdraw one unstarted scientific action misbound to a mutation step."""

        from axiom_rift.research.decision_withdrawal import (
            PortfolioDecisionWithdrawalReason,
            PortfolioExecutionPlanWithdrawalManifest,
        )

        _require_digest(
            "execution-plan Portfolio Decision withdrawal manifest",
            manifest_artifact_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(manifest_artifact_hash)
            manifest = PortfolioExecutionPlanWithdrawalManifest.from_bytes(
                manifest_bytes
            )
            report_bytes = self.evidence.read_verified(
                manifest.report_artifact_hash
            )
            proposed_bytes = self.evidence.read_verified(
                manifest.proposed_snapshot_artifact_hash
            )
            proposed = parse_canonical(proposed_bytes)
            manifest.require_report(report_bytes)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "execution-plan Portfolio Decision withdrawal lacks exact evidence"
            ) from exc
        if (
            manifest.reason_code
            is not PortfolioDecisionWithdrawalReason.UNBOUND_STRUCTURAL_EXECUTION_PLAN
            or not isinstance(proposed, Mapping)
            or canonical_digest(
                domain="portfolio-snapshot",
                payload=dict(proposed),
            )
            != manifest.proposed_snapshot_id.removeprefix("portfolio:")
        ):
            raise TransitionError(
                "execution-plan Portfolio Decision withdrawal proposal is malformed"
            )

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "execution-plan Portfolio Decision withdrawal requires control"
                )
            science = current["scientific"]
            mission_id = science.get("active_mission")
            initiative_id = science.get("active_initiative")
            if type(mission_id) is not str or type(initiative_id) is not str:
                raise TransitionError(
                    "execution-plan Portfolio Decision withdrawal requires active work"
                )
            if any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "execution-plan Portfolio Decision withdrawal cannot bypass work"
                )
            next_action = current.get("next_action")
            decision = index.get("portfolio-decision", manifest.decision_id)
            decision_operation = index.get(
                "operation",
                manifest.decision_operation_id,
            )
            decision_operation_result = (
                None
                if decision_operation is None
                else decision_operation.payload.get("result")
            )
            snapshot = index.get(
                "portfolio-snapshot",
                manifest.portfolio_snapshot_id,
            )
            diagnosis = index.get(
                "study-diagnosis",
                manifest.study_diagnosis_id,
            )
            if (
                self._portfolio_decision_withdrawal(
                    index,
                    manifest.decision_id,
                )
                is not None
            ):
                raise TransitionError("Portfolio Decision is already withdrawn")
            chosen_options = (
                ()
                if decision is None
                else tuple(
                    option
                    for option in decision.payload.get("options", ())
                    if isinstance(option, Mapping)
                    and option.get("option_id")
                    == decision.payload.get("chosen_option_id")
                )
            )
            old_axes_value = (
                None if snapshot is None else snapshot.payload.get("axes")
            )
            proposed_axes_value = proposed.get("axes")
            if (
                type(old_axes_value) is not list
                or type(proposed_axes_value) is not list
                or any(not isinstance(axis, Mapping) for axis in old_axes_value)
                or any(
                    not isinstance(axis, Mapping)
                    for axis in proposed_axes_value
                )
            ):
                raise TransitionError(
                    "execution-plan withdrawal axes are malformed"
                )
            old_axes = {
                axis.get("axis_id"): dict(axis) for axis in old_axes_value
            }
            proposed_axes = {
                axis.get("axis_id"): dict(axis)
                for axis in proposed_axes_value
            }
            if (
                None in old_axes
                or None in proposed_axes
                or len(old_axes) != len(old_axes_value)
                or len(proposed_axes) != len(proposed_axes_value)
            ):
                raise TransitionError(
                    "execution-plan withdrawal axes are ambiguous"
                )
            added = set(proposed_axes) - set(old_axes)
            chosen = chosen_options[0] if len(chosen_options) == 1 else None
            target_axis = old_axes.get(manifest.target_axis_id)
            proposed_axis = proposed_axes.get(manifest.proposed_axis_id)
            execution_actions = {
                "complementary_sleeve",
                "contrast",
                "deepen",
                "recombine",
                "rotate",
                "synthesize",
            }
            scheduler_constraints = (
                None
                if decision is None
                else decision.payload.get("scheduler_constraints")
            )
            replay_constraints = self._replay_scheduler_constraints(
                index,
                mission_id=mission_id,
            )
            intended_study = index.get(
                "study-open",
                manifest.intended_study_id,
            )
            if (
                not isinstance(next_action, Mapping)
                or next_action.get("kind") != "execute_portfolio_decision"
                or next_action.get("decision_id") != manifest.decision_id
                or next_action.get("portfolio_snapshot_id")
                != manifest.portfolio_snapshot_id
                or next_action.get("target_id") != manifest.target_axis_id
                or next_action.get("target_axis_identity")
                != manifest.target_axis_identity
                or (
                    next_action.get("study_diagnosis_id")
                    != manifest.study_diagnosis_id
                    and not (
                        self.engineering_fixture
                        and next_action.get("study_diagnosis_id") is None
                    )
                )
                or current.get("revision")
                != manifest.decision_authority_revision
                or current.get("heads", {}).get("journal", {}).get("event_id")
                != manifest.decision_authority_event_id
                or decision_operation is None
                or decision_operation.status != "success"
                or decision_operation.payload.get("event_kind")
                != "portfolio_decision_recorded"
                or not isinstance(decision_operation_result, Mapping)
                or decision_operation_result.get("decision_id")
                != manifest.decision_id
                or decision_operation.authority_sequence
                != manifest.decision_authority_revision
                or decision_operation.authority_event_id
                != manifest.decision_authority_event_id
                or decision is None
                or decision.subject != f"Mission:{mission_id}"
                or decision.payload.get("portfolio_snapshot_id")
                != manifest.portfolio_snapshot_id
                or decision.payload.get("study_diagnosis_id")
                != manifest.study_diagnosis_id
                or decision.payload.get("proposed_axis") is not None
                or decision.payload.get("replay_obligation_ids", [])
                or chosen is None
                or chosen.get("action") != manifest.chosen_action
                or manifest.chosen_action not in execution_actions
                or chosen.get("target_id") != manifest.target_axis_id
                or decision.payload.get("target_axis_identity")
                != manifest.target_axis_identity
                or snapshot is None
                or snapshot.record_id != manifest.portfolio_snapshot_id
                or not isinstance(target_axis, Mapping)
                or target_axis.get("axis_identity")
                != manifest.target_axis_identity
                or diagnosis is None
                or diagnosis.subject != f"Study:{diagnosis.payload.get('study_id')}"
                or diagnosis.payload.get("mission_id") != mission_id
                or diagnosis.payload.get("portfolio_snapshot_id")
                != manifest.portfolio_snapshot_id
                or proposed.get("schema") != "portfolio_snapshot.v3"
                or proposed.get("mission_id") != mission_id
                or added != {manifest.proposed_axis_id}
                or set(old_axes) - set(proposed_axes)
                or any(
                    proposed_axes[axis_id] != axis
                    for axis_id, axis in old_axes.items()
                )
                or not isinstance(proposed_axis, Mapping)
                or proposed_axis.get("axis_identity")
                != manifest.proposed_axis_identity
                or proposed_axis.get("mechanism_family")
                in {axis.get("mechanism_family") for axis in old_axes.values()}
                or intended_study is not None
                or scheduler_constraints != replay_constraints
            ):
                raise TransitionError(
                    "execution-plan withdrawal does not bind its exact failure"
                )
            try:
                durable_manifest_bytes = self.evidence.read_verified(
                    manifest_artifact_hash
                )
                durable_report_bytes = self.evidence.read_verified(
                    manifest.report_artifact_hash
                )
                durable_proposed_bytes = self.evidence.read_verified(
                    manifest.proposed_snapshot_artifact_hash
                )
                durable_manifest = (
                    PortfolioExecutionPlanWithdrawalManifest.from_bytes(
                        durable_manifest_bytes
                    )
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "execution-plan Portfolio Decision evidence changed"
                ) from exc
            if (
                durable_manifest_bytes != manifest_bytes
                or durable_report_bytes != report_bytes
                or durable_proposed_bytes != proposed_bytes
                or durable_manifest != manifest
            ):
                raise RecoveryRequired(
                    "execution-plan Portfolio Decision evidence changed"
                )
            post_holdout_development_id, _ = (
                self._require_post_holdout_decision_binding(
                    index,
                    science=science,
                    decision=decision,
                    next_action=next_action,
                )
            )
            replacement_action: dict[str, Any] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": manifest.portfolio_snapshot_id,
                "study_diagnosis_id": manifest.study_diagnosis_id,
            }
            if isinstance(post_holdout_development_id, str):
                replacement_action["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            try:
                diagnosis_authority = DiagnosisAuthorityContext.from_mapping(
                    decision.payload
                )
                diagnosis_authority.require_effective(
                    index,
                    mission_id=mission_id,
                )
            except DiagnosisAuthorityContextError as exc:
                raise RecoveryRequired(str(exc)) from exc
            if (
                diagnosis_authority.study_diagnosis_id
                != manifest.study_diagnosis_id
            ):
                raise TransitionError(
                    "execution-plan withdrawal diagnosis authority drifted"
                )
            replacement_action.update(
                diagnosis_authority.to_action_fields()
            )
            if replay_constraints is not None:
                replacement_action.update(replay_constraints)
            body = self._body(current)
            body["next_action"] = replacement_action
            record_id = canonical_digest(
                domain="portfolio-decision-withdrawal",
                payload={
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                },
            )
            record = _record(
                kind="portfolio-decision-withdrawal",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status="withdrawn_pre_execution",
                fingerprint=decision.fingerprint,
                payload={
                    "decision_id": manifest.decision_id,
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                    "replacement_next_action": replacement_action,
                },
                event_stream=(
                    f"portfolio-decision-status:{manifest.decision_id}"
                ),
                event_sequence=1,
            )
            return body, [record], {
                "decision_id": manifest.decision_id,
                "withdrawal_record_id": record_id,
            }

        return self._commit(
            event_kind="portfolio_decision_withdrawn",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={
                "manifest_artifact_hash": manifest_artifact_hash,
                "manifest": manifest.to_identity_payload(),
            },
            prepare=prepare,
        )

    def withdraw_structurally_invalid_portfolio_decision(
        self,
        *,
        manifest_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Withdraw one unstarted structural Decision proved impossible as stated."""

        from axiom_rift.research.decision_withdrawal import (
            PortfolioDecisionWithdrawalReason,
            PortfolioStructuralDecisionWithdrawalManifest,
        )

        _require_digest(
            "structural Portfolio Decision withdrawal manifest",
            manifest_artifact_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(manifest_artifact_hash)
            manifest = PortfolioStructuralDecisionWithdrawalManifest.from_bytes(
                manifest_bytes
            )
            report_bytes = self.evidence.read_verified(
                manifest.report_artifact_hash
            )
            proposed_bytes = self.evidence.read_verified(
                manifest.proposed_snapshot_artifact_hash
            )
            proposed = parse_canonical(proposed_bytes)
            manifest.require_report(report_bytes)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "structural Portfolio Decision withdrawal lacks exact evidence"
            ) from exc
        if (
            manifest.reason_code
            is not PortfolioDecisionWithdrawalReason.NEW_MECHANISM_DUPLICATES_EXISTING_FAMILY
            or not isinstance(proposed, Mapping)
            or canonical_digest(
                domain="portfolio-snapshot",
                payload=dict(proposed),
            )
            != manifest.proposed_snapshot_id.removeprefix("portfolio:")
        ):
            raise TransitionError(
                "structural Portfolio Decision withdrawal proposal is malformed"
            )

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "structural Portfolio Decision withdrawal requires control"
                )
            science = current["scientific"]
            mission_id = science.get("active_mission")
            initiative_id = science.get("active_initiative")
            if type(mission_id) is not str or type(initiative_id) is not str:
                raise TransitionError(
                    "structural Portfolio Decision withdrawal requires active Mission work"
                )
            if any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "structural Portfolio Decision withdrawal cannot bypass started work"
                )
            next_action = current.get("next_action")
            decision = index.get("portfolio-decision", manifest.decision_id)
            decision_operation = index.get(
                "operation",
                manifest.decision_operation_id,
            )
            decision_operation_result = (
                None
                if decision_operation is None
                else decision_operation.payload.get("result")
            )
            snapshot = index.get(
                "portfolio-snapshot",
                manifest.portfolio_snapshot_id,
            )
            if (
                self._portfolio_decision_withdrawal(
                    index,
                    manifest.decision_id,
                )
                is not None
            ):
                raise TransitionError("Portfolio Decision is already withdrawn")
            chosen_options = (
                ()
                if decision is None
                else tuple(
                    option
                    for option in decision.payload.get("options", ())
                    if isinstance(option, Mapping)
                    and option.get("option_id")
                    == decision.payload.get("chosen_option_id")
                )
            )
            old_axes_value = (
                None if snapshot is None else snapshot.payload.get("axes")
            )
            proposed_axes_value = proposed.get("axes")
            if (
                type(old_axes_value) is not list
                or type(proposed_axes_value) is not list
                or any(not isinstance(axis, Mapping) for axis in old_axes_value)
                or any(
                    not isinstance(axis, Mapping) for axis in proposed_axes_value
                )
            ):
                raise TransitionError(
                    "structural Portfolio Decision withdrawal axes are malformed"
                )
            old_axes = {axis.get("axis_id"): dict(axis) for axis in old_axes_value}
            proposed_axes = {
                axis.get("axis_id"): dict(axis) for axis in proposed_axes_value
            }
            if (
                None in old_axes
                or None in proposed_axes
                or len(old_axes) != len(old_axes_value)
                or len(proposed_axes) != len(proposed_axes_value)
            ):
                raise TransitionError(
                    "structural Portfolio Decision withdrawal axes are ambiguous"
                )
            added = set(proposed_axes) - set(old_axes)
            chosen = chosen_options[0] if len(chosen_options) == 1 else None
            target_axis = old_axes.get(manifest.target_axis_id)
            proposed_axis = proposed_axes.get(manifest.proposed_axis_id)
            conflicting_axis = old_axes.get(manifest.conflicting_axis_id)
            scheduler_constraints = (
                None
                if decision is None
                else decision.payload.get("scheduler_constraints")
            )
            replay_constraints = self._replay_scheduler_constraints(
                index,
                mission_id=mission_id,
            )
            if (
                not isinstance(next_action, Mapping)
                or next_action.get("kind") != "record_portfolio_snapshot"
                or next_action.get("decision_id") != manifest.decision_id
                or next_action.get("action") != "new_mechanism"
                or next_action.get("portfolio_snapshot_id")
                != manifest.portfolio_snapshot_id
                or next_action.get("target_id") != manifest.target_axis_id
                or next_action.get("target_axis_identity")
                != manifest.target_axis_identity
                or current.get("revision")
                != manifest.decision_authority_revision
                or current.get("heads", {}).get("journal", {}).get("event_id")
                != manifest.decision_authority_event_id
                or decision_operation is None
                or decision_operation.status != "success"
                or decision_operation.payload.get("event_kind")
                != "portfolio_decision_recorded"
                or not isinstance(decision_operation_result, Mapping)
                or decision_operation_result.get("decision_id")
                != manifest.decision_id
                or decision_operation.authority_sequence
                != manifest.decision_authority_revision
                or decision_operation.authority_event_id
                != manifest.decision_authority_event_id
                or decision is None
                or decision.subject != f"Mission:{mission_id}"
                or decision.payload.get("portfolio_snapshot_id")
                != manifest.portfolio_snapshot_id
                or snapshot is None
                or snapshot.record_id != manifest.portfolio_snapshot_id
                or chosen is None
                or chosen.get("action") != "new_mechanism"
                or chosen.get("target_id") != manifest.target_axis_id
                or decision.payload.get("target_axis_identity")
                != manifest.target_axis_identity
                or not isinstance(target_axis, Mapping)
                or target_axis.get("axis_identity")
                != manifest.target_axis_identity
                or proposed.get("schema") != "portfolio_snapshot.v3"
                or proposed.get("mission_id") != mission_id
                or added != {manifest.proposed_axis_id}
                or set(old_axes) - set(proposed_axes)
                or any(proposed_axes[axis_id] != axis for axis_id, axis in old_axes.items())
                or not isinstance(proposed_axis, Mapping)
                or proposed_axis.get("axis_identity")
                != manifest.proposed_axis_identity
                or proposed_axis.get("mechanism_family")
                != manifest.duplicate_mechanism_family
                or not isinstance(conflicting_axis, Mapping)
                or conflicting_axis.get("axis_identity")
                != manifest.conflicting_axis_identity
                or conflicting_axis.get("mechanism_family")
                != manifest.duplicate_mechanism_family
                or proposed_axis.get("causal_question")
                != conflicting_axis.get("causal_question")
                or scheduler_constraints != replay_constraints
            ):
                raise TransitionError(
                    "structural Portfolio Decision withdrawal does not bind its exact failure"
                )
            if not self.engineering_fixture:
                from axiom_rift.operations.semantic_question_registry import (
                    SemanticQuestionRegistryError,
                    SemanticQuestionRegistryIntegrityError,
                    require_semantic_question_study_binding,
                )

                lineage = manifest.semantic_question_lineage
                try:
                    require_semantic_question_study_binding(
                        index,
                        study_id=lineage.predecessor_study_id,
                        core_id=lineage.predecessor_core_id,
                    )
                except SemanticQuestionRegistryIntegrityError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                except SemanticQuestionRegistryError as exc:
                    raise TransitionError(str(exc)) from exc
                if (
                    index.get("study-open", lineage.successor_study_id)
                    is not None
                    or any(
                        ":" not in reference
                        or index.get(*reference.split(":", 1)) is None
                        for reference in lineage.basis_record_ids
                    )
                ):
                    raise TransitionError(
                        "structural withdrawal semantic lineage is stale"
                    )
            replacement_action: dict[str, Any] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": manifest.portfolio_snapshot_id,
            }
            post_holdout_development_id, _ = (
                self._require_post_holdout_decision_binding(
                    index,
                    science=science,
                    decision=decision,
                    next_action=next_action,
                )
            )
            if isinstance(post_holdout_development_id, str):
                replacement_action["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            try:
                diagnosis_authority = DiagnosisAuthorityContext.from_mapping(
                    decision.payload
                )
                diagnosis_authority.require_effective(
                    index,
                    mission_id=mission_id,
                )
            except DiagnosisAuthorityContextError as exc:
                raise RecoveryRequired(str(exc)) from exc
            replacement_action.update(
                diagnosis_authority.to_action_fields()
            )
            if replay_constraints is not None:
                replacement_action.update(replay_constraints)
            try:
                durable_manifest_bytes = self.evidence.read_verified(
                    manifest_artifact_hash
                )
                durable_report_bytes = self.evidence.read_verified(
                    manifest.report_artifact_hash
                )
                durable_proposed_bytes = self.evidence.read_verified(
                    manifest.proposed_snapshot_artifact_hash
                )
                durable_manifest = (
                    PortfolioStructuralDecisionWithdrawalManifest.from_bytes(
                        durable_manifest_bytes
                    )
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "structural Portfolio Decision withdrawal evidence changed"
                ) from exc
            if (
                durable_manifest_bytes != manifest_bytes
                or durable_report_bytes != report_bytes
                or durable_proposed_bytes != proposed_bytes
                or durable_manifest != manifest
            ):
                raise RecoveryRequired(
                    "structural Portfolio Decision withdrawal evidence changed"
                )
            body = self._body(current)
            body["next_action"] = replacement_action
            record_id = canonical_digest(
                domain="portfolio-decision-withdrawal",
                payload={
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                },
            )
            record = _record(
                kind="portfolio-decision-withdrawal",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status="withdrawn_pre_execution",
                fingerprint=decision.fingerprint,
                payload={
                    "decision_id": manifest.decision_id,
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                    "replacement_next_action": replacement_action,
                },
                event_stream=(
                    f"portfolio-decision-status:{manifest.decision_id}"
                ),
                event_sequence=1,
            )
            return body, [record], {
                "decision_id": manifest.decision_id,
                "withdrawal_record_id": record_id,
            }

        return self._commit(
            event_kind="portfolio_decision_withdrawn",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={
                "manifest_artifact_hash": manifest_artifact_hash,
                "manifest": manifest.to_identity_payload(),
            },
            prepare=prepare,
        )
