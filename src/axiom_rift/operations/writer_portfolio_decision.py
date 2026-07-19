"""Portfolio snapshot, axis-reopen, and Decision transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.operations.diagnosis_authority_context import (
    DiagnosisAuthorityContext,
    DiagnosisAuthorityContextError,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _digest,
    _record,
    _require_digest,
)
from axiom_rift.storage.index import LocalIndex


class PortfolioDecisionWriterMixin:
    """Own Portfolio scheduling transitions; the facade commits atomically."""

    def record_portfolio_snapshot(
        self,
        *,
        snapshot: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import PortfolioSnapshot
        from axiom_rift.operations.architecture_review_direction import (
            ArchitectureReviewDirectionError,
            constraint_from_action,
            eligible_new_mechanism_axes,
            require_review_binding,
        )
        from axiom_rift.operations.prospective_architecture_projection import (
            PROJECTION_FIELD,
            ProspectiveArchitectureProjectionError,
            derive_axis_families,
            projection_payload,
        )

        self._require_study_close_delivery_guard()
        if not isinstance(snapshot, PortfolioSnapshot):
            raise TransitionError("snapshot must be a PortfolioSnapshot")
        try:
            derived_axis_families = derive_axis_families(snapshot)
        except ProspectiveArchitectureProjectionError as exc:
            raise TransitionError(str(exc)) from exc

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            if science["active_mission"] != snapshot.mission_id:
                raise TransitionError("Portfolio snapshot belongs to another Mission")
            if science["active_initiative"] is None:
                raise TransitionError("Portfolio snapshot requires an active Initiative")
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("Portfolio snapshot cannot bypass active work")
            head = index.event_head(f"portfolio:{snapshot.mission_id}")
            sequence = 1 if head is None else head.sequence + 1
            required_target_axis_ids: list[str] = []
            constraint_source_id: str | None = None
            continuation = None
            post_holdout_development_id: str | None = None
            replay_scheduler_projection_recovered = False
            prior_architecture_projection: object = None
            replay_constraints = self._replay_scheduler_constraints(
                index,
                mission_id=snapshot.mission_id,
            )
            if head is None:
                standard = snapshot.exhaustion_standard_value()
                if not self.engineering_fixture and not isinstance(standard, dict):
                    raise TransitionError(
                        "scientific Portfolio requires a preregistered exhaustion standard"
                    )
                if isinstance(standard, dict):
                    if not self.engineering_fixture and any(
                        axis.architecture_chassis is None for axis in snapshot.axes
                    ):
                        raise TransitionError(
                            "scientific Portfolio axes require canonical architecture chassis"
                        )
                    families = {axis.mechanism_family for axis in snapshot.axes}
                    research_layers = {
                        axis.primary_research_layer.value for axis in snapshot.axes
                    }
                    architecture_families = {
                        axis.architecture_chassis.identity
                        for axis in snapshot.axes
                        if axis.architecture_chassis is not None
                    }
                    if (
                        len(snapshot.axes) < standard["minimum_axes"]
                        or len(families) < standard["minimum_mechanism_families"]
                        or len(research_layers)
                        < standard["minimum_primary_research_layers"]
                        or len(architecture_families)
                        < standard["minimum_system_architecture_families"]
                    ):
                        raise TransitionError(
                            "initial Portfolio is smaller than its exhaustion standard"
                        )
                intake = (
                    None
                    if not isinstance(snapshot.research_intake_id, str)
                    else index.get("research-intake", snapshot.research_intake_id)
                )
                if (
                    current["next_action"].get("kind") != "build_portfolio"
                    or current["next_action"].get("initiative_id")
                    != science["active_initiative"]
                    or (
                        not self.engineering_fixture
                        and (
                            current["next_action"].get("research_intake_id")
                            != snapshot.research_intake_id
                            or intake is None
                            or intake.subject != f"Mission:{snapshot.mission_id}"
                            or intake.status != "accepted"
                        )
                    )
                ):
                    raise TransitionError(
                        "initial Portfolio snapshot is not the exact Initiative action"
                    )
            else:
                prior = index.get(head.record_kind, head.record_id)
                if prior is None or prior.kind != "portfolio-snapshot":
                    raise TransitionError("current Portfolio snapshot is unavailable")
                prior_architecture_projection = prior.payload.get(
                    PROJECTION_FIELD
                )
                next_action = current["next_action"]
                try:
                    continuation = constraint_from_action(next_action)
                except ArchitectureReviewDirectionError as exc:
                    raise TransitionError(str(exc)) from exc
                decision_id = next_action.get("decision_id")
                decision = (
                    None
                    if not isinstance(decision_id, str)
                    else self._active_portfolio_decision(index, decision_id)
                )
                if (
                    next_action.get("kind") != "record_portfolio_snapshot"
                    or decision is None
                    or decision.payload.get("portfolio_snapshot_id") != prior.record_id
                ):
                    raise TransitionError(
                        "Portfolio snapshot mutation requires the current structural Decision"
                    )
                post_holdout_development_id, _ = (
                    self._require_post_holdout_decision_binding(
                        index,
                        science=science,
                        decision=decision,
                        next_action=next_action,
                    )
                )
                from axiom_rift.operations.replay_projection import (
                    ReplayTransitionError,
                    validate_snapshot_scheduler_projection,
                )

                try:
                    replay_scheduler_projection_recovered = (
                        validate_snapshot_scheduler_projection(
                            next_action=next_action,
                            decision_payload=decision.payload,
                            constraints=replay_constraints,
                        )
                    )
                except ReplayTransitionError as exc:
                    raise TransitionError(str(exc)) from exc
                old_axes = {axis["axis_id"]: axis for axis in prior.payload["axes"]}
                if continuation is not None:
                    review = index.get(
                        "architecture-review",
                        continuation.architecture_review_id,
                    )
                    trigger = index.get(
                        "architecture-review-trigger",
                        continuation.trigger_record_id,
                    )
                    if review is None or trigger is None:
                        raise RecoveryRequired(
                            "bounded architecture continuation authority is unavailable"
                        )
                    try:
                        require_review_binding(
                            continuation,
                            review_record_id=review.record_id,
                            review_payload=review.payload,
                            trigger_payload=trigger.payload,
                        )
                        if self._review_resolved_architecture_family(
                            index=index,
                            review=review,
                        ) != continuation.required_architecture_family:
                            raise ArchitectureReviewDirectionError(
                                "bounded architecture review family is no longer current"
                            )
                    except ArchitectureReviewDirectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                new_payload = snapshot.to_identity_payload()
                new_axes = {axis["axis_id"]: axis for axis in new_payload["axes"]}
                if (
                    new_payload.get("exhaustion_standard")
                    != prior.payload.get("exhaustion_standard")
                ):
                    raise TransitionError(
                        "Portfolio exhaustion standard is immutable within a Mission"
                    )
                if (
                    new_payload.get("research_intake_id")
                    != prior.payload.get("research_intake_id")
                ):
                    raise TransitionError(
                        "Portfolio research intake is immutable within a Mission"
                    )
                if not set(old_axes).issubset(new_axes):
                    raise TransitionError("Portfolio axes cannot be silently removed")
                added_axis_ids = set(new_axes) - set(old_axes)
                action = next_action.get("action")
                target_id = next_action.get("target_id")
                protocol_revision = None
                if action == "revise_protocol":
                    from axiom_rift.research.axis_protocol_revision import (
                        AxisProtocolRevisionProposal,
                    )

                    try:
                        protocol_revision = (
                            AxisProtocolRevisionProposal.from_mapping(
                                decision.payload.get("protocol_revision")
                            )
                        )
                    except (TypeError, ValueError) as exc:
                        raise RecoveryRequired(
                            "accepted protocol revision authority is malformed"
                        ) from exc
                    if (
                        decision.payload.get("protocol_revision_id")
                        != protocol_revision.identity
                        or next_action.get("protocol_revision_id")
                        != protocol_revision.identity
                    ):
                        raise RecoveryRequired(
                            "protocol revision identity is not exact"
                        )
                if not self.engineering_fixture and any(
                    new_axes[axis_id].get("architecture_chassis_identity") is None
                    for axis_id in added_axis_ids
                ):
                    raise TransitionError(
                        "new scientific Portfolio axes require canonical architecture chassis"
                    )
                pruned_reopen_axis_ids: list[str] = []
                for axis_id, old_axis in old_axes.items():
                    if (
                        not (
                            protocol_revision is not None
                            and axis_id == target_id
                        )
                        and new_axes[axis_id]["axis_identity"]
                        != old_axis["axis_identity"]
                    ):
                        raise TransitionError(
                            "Portfolio axis meaning is immutable within a Mission"
                        )
                    if old_axis["status"] == "pruned" and new_axes[axis_id]["status"] != "pruned":
                        pruned_reopen_axis_ids.append(axis_id)
                if pruned_reopen_axis_ids:
                    from axiom_rift.research.effective_axis import (
                        AxisReopenAuthority,
                        axis_reopen_evidence,
                    )

                    if (
                        pruned_reopen_axis_ids != [target_id]
                        or action != "preserve"
                        or new_axes[target_id]["status"] != "preserved"
                    ):
                        raise TransitionError(
                            "a pruned Portfolio axis requires its exact preserve authority"
                        )
                    resolution = self._effective_axis_resolution(
                        index, old_axes[target_id]
                    )
                    reopen_evidence = axis_reopen_evidence(resolution)
                    expected_authority = AxisReopenAuthority(
                        mission_id=snapshot.mission_id,
                        portfolio_snapshot_id=prior.record_id,
                        portfolio_decision_id=decision.record_id,
                        axis_id=target_id,
                        axis_identity=old_axes[target_id]["axis_identity"],
                        replay_resolution_record_ids=(
                            reopen_evidence.replay_resolution_record_ids
                        ),
                        evidence_scope_overlay_ids=(
                            reopen_evidence.evidence_scope_overlay_ids
                        ),
                        historical_cost_completion_ids=(
                            reopen_evidence.historical_cost_completion_ids
                        ),
                        historical_cost_latch_ids=(
                            reopen_evidence.historical_cost_latch_ids
                        ),
                        historical_cost_negative_memory_ids=(
                            reopen_evidence.historical_cost_negative_memory_ids
                        ),
                    )
                    authority_id = next_action.get(
                        "axis_reopen_authority_id"
                    )
                    authority = (
                        None
                        if not isinstance(authority_id, str)
                        else index.get("axis-reopen-authority", authority_id)
                    )
                    authority_stream = (
                        f"axis-reopen:{snapshot.mission_id}:"
                        f"{old_axes[target_id]['axis_identity']}"
                    )
                    authority_head = index.event_head(authority_stream)
                    if (
                        authority_id != expected_authority.identity
                        or authority is None
                        or authority.kind != "axis-reopen-authority"
                        or authority.status != "authorized"
                        or authority.subject
                        != f"Axis:{old_axes[target_id]['axis_identity']}"
                        or authority.fingerprint
                        != expected_authority.identity.removeprefix(
                            "axis-reopen-authority:"
                        )
                        or authority.payload.get("authority")
                        != expected_authority.to_identity_payload()
                        or authority.payload.get("effective_axis")
                        != resolution.to_projection_payload()
                        or authority.event_stream != authority_stream
                        or authority_head is None
                        or authority_head.record_id != authority.record_id
                        or authority.event_sequence != authority_head.sequence
                        or prior.authority_sequence is None
                        or decision.authority_sequence is None
                        or authority.authority_sequence is None
                        or decision.authority_sequence <= prior.authority_sequence
                        or authority.authority_sequence
                        <= decision.authority_sequence
                    ):
                        raise TransitionError(
                            "pruned Portfolio axis lacks its exact one-shot reopen authority"
                        )
                elif next_action.get("axis_reopen_authority_id") is not None:
                    raise TransitionError(
                        "axis reopen authority cannot authorize an unrelated snapshot"
                    )
                if action in {"preserve", "prune"}:
                    if set(new_axes) != set(old_axes) or target_id not in old_axes:
                        raise TransitionError(
                            "axis disposition snapshot may change one declared target only"
                        )
                    expected_status = "preserved" if action == "preserve" else "pruned"
                    for axis_id, old_axis in old_axes.items():
                        wanted = expected_status if axis_id == target_id else old_axis["status"]
                        if new_axes[axis_id]["status"] != wanted:
                            raise TransitionError(
                                "Portfolio snapshot differs from its structural Decision"
                            )
                elif action == "revise_protocol":
                    assert protocol_revision is not None
                    old_target = old_axes.get(target_id)
                    new_target = new_axes.get(target_id)
                    old_target_architecture_authority = (
                        None
                        if not isinstance(old_target, Mapping)
                        else self._axis_architecture_authority_identity(
                            index,
                            old_target,
                        )
                    )
                    immutable_fields = set(old_target or {}).difference(
                        {
                            "architecture_chassis",
                            "architecture_chassis_identity",
                            "axis_identity",
                            "system_architecture_family",
                            "why_now",
                        }
                    )
                    if (
                        continuation is not None
                        or set(new_axes) != set(old_axes)
                        or target_id != protocol_revision.axis_id
                        or not isinstance(old_target, Mapping)
                        or not isinstance(new_target, Mapping)
                        or any(
                            new_axes[axis_id] != old_axis
                            for axis_id, old_axis in old_axes.items()
                            if axis_id != target_id
                        )
                        or any(
                            new_target.get(field) != old_target.get(field)
                            for field in immutable_fields
                        )
                        or old_target.get("axis_identity")
                        != protocol_revision.predecessor_axis_identity
                        or new_target.get("axis_identity")
                        != protocol_revision.successor_axis_identity
                        or old_target.get("mechanism_family")
                        != protocol_revision.mechanism_family
                        or new_target.get("mechanism_family")
                        != protocol_revision.mechanism_family
                        or old_target_architecture_authority
                        != protocol_revision.predecessor_architecture_family
                        or new_target.get("architecture_chassis_identity")
                        != protocol_revision.successor_architecture_family
                        or new_target.get("system_architecture_family")
                        != protocol_revision.successor_architecture_family
                        or not isinstance(
                            new_target.get("architecture_chassis"),
                            Mapping,
                        )
                    ):
                        raise TransitionError(
                            "protocol revision must replace one exact axis chassis only"
                        )
                elif action == "new_mechanism":
                    added = set(new_axes) - set(old_axes)
                    old_families = {
                        axis["mechanism_family"] for axis in old_axes.values()
                    }
                    proposed_axis = decision.payload.get("proposed_axis")
                    proposed_axis_identity = decision.payload.get(
                        "proposed_axis_identity"
                    )
                    if (
                        not added
                        or any(
                            new_axes[axis_id]["status"] != old_axis["status"]
                            for axis_id, old_axis in old_axes.items()
                        )
                        or not any(
                            new_axes[axis_id]["mechanism_family"] not in old_families
                            for axis_id in added
                        )
                    ):
                        raise TransitionError(
                            "new_mechanism must add a genuinely distinct untouched axis"
                        )
                    if proposed_axis is not None and (
                        not isinstance(proposed_axis, Mapping)
                        or not isinstance(proposed_axis_identity, str)
                        or added != {proposed_axis.get("axis_id")}
                        or new_axes.get(proposed_axis.get("axis_id"))
                        != dict(proposed_axis)
                        or proposed_axis.get("axis_identity")
                        != proposed_axis_identity
                    ):
                        raise TransitionError(
                            "new mechanism differs from its exact proposed axis"
                        )
                    if continuation is not None:
                        added_axes = {
                            axis_id: new_axes[axis_id] for axis_id in added
                        }
                        resolved_families = {
                            axis_id: (
                                derived_axis_families.get(
                                    axis["axis_identity"]
                                )
                                or self._axis_resolved_architecture_family(
                                    index=index,
                                    axis=axis,
                                )
                            )
                            for axis_id, axis in added_axes.items()
                        }
                        try:
                            required_target_axis_ids = list(
                                eligible_new_mechanism_axes(
                                    continuation,
                                    added_axes=added_axes,
                                    resolved_architecture_families=resolved_families,
                                )
                            )
                        except ArchitectureReviewDirectionError as exc:
                            raise TransitionError(str(exc)) from exc
                        constraint_source_id = continuation.architecture_review_id
                    else:
                        required_layers = set(
                            next_action.get("required_followup_layers", [])
                        )
                        excluded_layers = set(
                            next_action.get("excluded_research_layers", [])
                        )
                        excluded_architecture = next_action.get(
                            "excluded_architecture_family"
                        )
                        constrained = bool(
                            required_layers
                            or excluded_layers
                            or isinstance(excluded_architecture, str)
                        )
                    if continuation is None and constrained:
                        required_target_axis_ids = sorted(
                            axis_id
                            for axis_id in added
                            if (
                                not required_layers
                                or new_axes[axis_id]["primary_research_layer"]
                                in required_layers
                            )
                            and new_axes[axis_id]["primary_research_layer"]
                            not in excluded_layers
                            and (
                                not isinstance(excluded_architecture, str)
                                or (
                                    isinstance(
                                        new_axes[axis_id].get(
                                            "architecture_chassis_identity"
                                        ),
                                        str,
                                    )
                                    and new_axes[axis_id][
                                        "architecture_chassis_identity"
                                    ]
                                    != excluded_architecture
                                )
                            )
                        )
                        if not required_target_axis_ids:
                            raise TransitionError(
                                "new mechanism does not satisfy its diagnosis or architecture constraint"
                            )
                        source = next_action.get("constraint_source_id")
                        if not isinstance(source, str):
                            raise TransitionError(
                                "constrained Portfolio mutation lacks its source"
                            )
                        constraint_source_id = source
                else:
                    raise TransitionError(
                        "Portfolio Decision does not authorize snapshot mutation"
                    )
            body = self._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": snapshot.identity,
            }
            if isinstance(post_holdout_development_id, str):
                body["next_action"]["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            if continuation is not None:
                body["next_action"].update(
                    continuation.with_materialized_targets(
                        tuple(required_target_axis_ids)
                    ).to_action_fields()
                )
            elif required_target_axis_ids:
                body["next_action"].update(
                    {
                        "constraint_source_id": constraint_source_id,
                        "required_target_axis_ids": required_target_axis_ids,
                    }
                )
            if replay_constraints is not None:
                body["next_action"].update(replay_constraints)
            record_payload = snapshot.to_identity_payload()
            current_axis_identities = {
                axis["axis_identity"] for axis in record_payload["axes"]
            }
            try:
                record_payload[PROJECTION_FIELD] = projection_payload(
                    current_axis_identities=current_axis_identities,
                    derived_families=derived_axis_families,
                    prior_payload=prior_architecture_projection,
                )
            except ProspectiveArchitectureProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            record = _record(
                kind="portfolio-snapshot",
                record_id=snapshot.identity,
                subject=f"Mission:{snapshot.mission_id}",
                status=(
                    "closed"
                    if all(axis.status == "pruned" for axis in snapshot.axes)
                    else "current"
                ),
                fingerprint=snapshot.identity.removeprefix("portfolio:"),
                payload=record_payload,
                event_stream=f"portfolio:{snapshot.mission_id}",
                event_sequence=sequence,
            )
            result = {"portfolio_snapshot_id": snapshot.identity}
            if replay_scheduler_projection_recovered:
                result["replay_scheduler_projection_recovered"] = True
            return body, [record], result

        return self._commit(
            event_kind="portfolio_snapshot_recorded",
            operation_id=operation_id,
            subject=f"Mission:{snapshot.mission_id}",
            payload={"portfolio_snapshot_id": snapshot.identity},
            prepare=prepare,
        )

    def record_axis_reopen_authority(
        self,
        *,
        operation_id: str,
    ) -> TransitionResult:
        """Authorize exactly one audit-deferred historical prune to be preserved."""

        from axiom_rift.research.effective_axis import (
            AxisReopenAuthority,
            axis_reopen_evidence,
        )

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("axis reopen authority requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            if (
                not isinstance(mission_id, str)
                or science.get("active_initiative") is None
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
                    "axis reopen authority requires a stable Initiative boundary"
                )
            next_action = current.get("next_action")
            if (
                not isinstance(next_action, Mapping)
                or next_action.get("kind")
                != "record_axis_reopen_authority"
            ):
                raise TransitionError(
                    "no exact audit-deferred axis reopen is pending"
                )
            snapshot_id = next_action.get("portfolio_snapshot_id")
            decision_id = next_action.get("decision_id")
            target_id = next_action.get("target_id")
            target_identity = next_action.get("target_axis_identity")
            portfolio_head = index.event_head(f"portfolio:{mission_id}")
            snapshot = (
                None
                if not isinstance(snapshot_id, str)
                else index.get("portfolio-snapshot", snapshot_id)
            )
            decision = (
                None
                if not isinstance(decision_id, str)
                else self._active_portfolio_decision(index, decision_id)
            )
            axes = (
                {}
                if snapshot is None
                else {
                    axis.get("axis_id"): axis
                    for axis in snapshot.payload.get("axes", ())
                    if isinstance(axis, Mapping)
                    and isinstance(axis.get("axis_id"), str)
                }
            )
            axis = axes.get(target_id)
            if (
                portfolio_head is None
                or portfolio_head.record_id != snapshot_id
                or snapshot is None
                or snapshot.subject != f"Mission:{mission_id}"
                or decision is None
                or decision.subject != f"Mission:{mission_id}"
                or decision.payload.get("portfolio_snapshot_id") != snapshot_id
                or decision.payload.get("target_axis_identity")
                != target_identity
                or decision.status != "preserve"
                or next_action.get("action") != "preserve"
                or axis is None
                or axis.get("axis_identity") != target_identity
                or axis.get("status") != "pruned"
            ):
                raise TransitionError(
                    "axis reopen authority lost its exact Decision and snapshot"
                )
            post_holdout_development_id, _ = (
                self._require_post_holdout_decision_binding(
                    index,
                    science=science,
                    decision=decision,
                    next_action=next_action,
                )
            )
            resolution = self._effective_axis_resolution(index, axis)
            reopen_evidence = axis_reopen_evidence(resolution)
            if decision.payload.get("effective_axis") != (
                resolution.to_projection_payload()
            ):
                raise TransitionError(
                    "axis reopen Decision authority is stale"
                )
            expected_action: dict[str, Any] = {
                "action": "preserve",
                "decision_id": decision.record_id,
                "kind": "record_axis_reopen_authority",
                "portfolio_snapshot_id": snapshot.record_id,
                "target_axis_identity": target_identity,
                "target_id": target_id,
            }
            if isinstance(post_holdout_development_id, str):
                expected_action["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            expected_action.update(reopen_evidence.to_action_fields())
            decision_obligations = decision.payload.get(
                "replay_obligation_ids"
            )
            if isinstance(decision_obligations, list) and decision_obligations:
                expected_action["replay_obligation_ids"] = list(
                    decision_obligations
                )
            expected_action = self._with_replay_scheduler_constraints(
                expected_action,
                self._replay_scheduler_constraints(
                    index,
                    mission_id=mission_id,
                ),
            )
            if dict(next_action) != expected_action:
                raise TransitionError(
                    "axis reopen action differs from its exact audit evidence"
                )
            authority = AxisReopenAuthority(
                mission_id=mission_id,
                portfolio_snapshot_id=snapshot.record_id,
                portfolio_decision_id=decision.record_id,
                axis_id=target_id,
                axis_identity=target_identity,
                replay_resolution_record_ids=(
                    reopen_evidence.replay_resolution_record_ids
                ),
                evidence_scope_overlay_ids=(
                    reopen_evidence.evidence_scope_overlay_ids
                ),
                historical_cost_completion_ids=(
                    reopen_evidence.historical_cost_completion_ids
                ),
                historical_cost_latch_ids=(
                    reopen_evidence.historical_cost_latch_ids
                ),
                historical_cost_negative_memory_ids=(
                    reopen_evidence.historical_cost_negative_memory_ids
                ),
            )
            stream = f"axis-reopen:{mission_id}:{target_identity}"
            stream_head = index.event_head(stream)
            record = _record(
                kind="axis-reopen-authority",
                record_id=authority.identity,
                subject=f"Axis:{target_identity}",
                status="authorized",
                fingerprint=authority.identity.removeprefix(
                    "axis-reopen-authority:"
                ),
                payload={
                    "authority": authority.to_identity_payload(),
                    "candidate_delta": 0,
                    "claim_delta": "none",
                    "effective_axis": resolution.to_projection_payload(),
                    "holdout_delta": 0,
                    "scientific_credit": 0,
                    "trial_delta": 0,
                },
                event_stream=stream,
                event_sequence=(
                    1 if stream_head is None else stream_head.sequence + 1
                ),
            )
            body = self._body(current)
            snapshot_action = dict(next_action)
            snapshot_action["kind"] = "record_portfolio_snapshot"
            snapshot_action["axis_reopen_authority_id"] = authority.identity
            for field in reopen_evidence.to_action_fields():
                snapshot_action.pop(field)
            body["next_action"] = snapshot_action
            return body, [record], {
                "axis_id": target_id,
                "axis_reopen_authority_id": authority.identity,
                "candidate_delta": 0,
                "claim_delta": "none",
                "holdout_delta": 0,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="axis_reopen_authority_recorded",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={"transition": "audit_deferred_prune_reopen"},
            prepare=prepare,
        )

    def record_portfolio_decision(
        self,
        *,
        decision: Any,
        operation_id: str,
        replacement_replay_batch_spec: Any | None = None,
        replacement_replay_implementation_request: Any | None = None,
        replacement_replay_study_payload: Mapping[str, Any] | None = None,
        replacement_semantic_question_lineage: Any | None = None,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import PortfolioAction, PortfolioDecision
        from axiom_rift.operations.architecture_review_direction import (
            ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
            ArchitectureReviewDirectionError,
            constraint_from_action,
            require_decision_direction,
            require_existing_axis_binding,
            require_review_binding,
            required_quant_team_basis,
        )
        from axiom_rift.operations.prospective_architecture_projection import (
            ProspectiveArchitectureProjectionError,
            family_for_axis,
        )

        self._require_study_close_delivery_guard()

        if not isinstance(decision, PortfolioDecision):
            raise TransitionError("decision must be a PortfolioDecision")
        decision_hash = decision.identity.removeprefix("decision:")
        _require_digest("decision hash", decision_hash)

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("Portfolio Decision requires an active Mission")
            science = current["scientific"]
            if science["active_initiative"] is None:
                raise TransitionError("Portfolio Decision requires an active Initiative")
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("Portfolio Decision cannot bypass active work")
            portfolio_head = _index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            snapshot = (
                None
                if portfolio_head is None
                else _index.get(portfolio_head.record_kind, portfolio_head.record_id)
            )
            if snapshot is None or snapshot.kind != "portfolio-snapshot":
                raise TransitionError("Portfolio Decision requires a current snapshot")
            review = decision.quant_team_review
            review_basis: set[tuple[str, str]] = set()
            if (
                not self.engineering_fixture
                and review is None
            ):
                raise TransitionError(
                    "real Portfolio Decision requires a plural quant-team review"
                )
            if review is not None:
                review_basis = {
                    (basis.kind, basis.record_id)
                    for assessment in review.assessments
                    for basis in assessment.basis_records
                }
                if any(
                    _index.get(kind, record_id) is None
                    for kind, record_id in review_basis
                ):
                    raise TransitionError(
                        "quant-team review cites unavailable durable evidence"
                    )
                if ("portfolio-snapshot", snapshot.record_id) not in review_basis:
                    raise TransitionError(
                        "quant-team review does not bind the current Portfolio"
                    )
            next_action = current["next_action"]
            try:
                continuation = constraint_from_action(next_action)
            except ArchitectureReviewDirectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            if (
                next_action.get("kind") != "portfolio_decision"
                or (
                    next_action.get("portfolio_snapshot_id") is not None
                    and next_action.get("portfolio_snapshot_id") != snapshot.record_id
                )
            ):
                raise TransitionError("Portfolio Decision is not the exact next action")
            post_holdout_development_id = next_action.get(
                "post_holdout_development_id"
            )
            if post_holdout_development_id is not None:
                required_holdout_id = science.get("required_future_holdout_id")
                if (
                    science.get("holdout_reveals", 0) < 1
                    or not isinstance(required_holdout_id, str)
                    or not isinstance(post_holdout_development_id, str)
                ):
                    raise TransitionError(
                        "Portfolio Decision post-holdout authority is malformed"
                    )
                self._require_post_holdout_development_authority(
                    _index,
                    mission_id=science["active_mission"],
                    record_id=post_holdout_development_id,
                    required_holdout_id=required_holdout_id,
                )
                if review is None or (
                    "post-holdout-development",
                    post_holdout_development_id,
                ) not in review_basis:
                    raise TransitionError(
                        "quant-team review omits post-holdout development authority"
                    )
            axis_values = tuple(snapshot.payload["axes"])
            axes_by_id = {axis["axis_id"]: axis for axis in axis_values}
            axis_resolutions = self._effective_axis_resolutions(
                _index,
                axis_values,
            )
            effective_axes = {
                axis["axis_id"]: resolution
                for axis, resolution in zip(
                    axis_values,
                    axis_resolutions,
                    strict=True,
                )
            }
            option_eligible_targets = {
                axis_id
                for axis_id, resolution in effective_axes.items()
                if resolution.decision_option_eligible
            }
            if any(
                option.target_id not in option_eligible_targets
                for option in decision.options
            ):
                raise TransitionError(
                    "Portfolio Decision names an undeclared or effectively blocked target axis"
                )
            chosen_effective_axis = effective_axes[decision.chosen.target_id]
            diagnosis_binding = chosen_effective_axis.diagnosis_binding
            generic_portfolio_boundary = (
                not isinstance(
                    next_action.get("study_diagnosis_id"),
                    str,
                )
                and continuation is None
                and not isinstance(
                    next_action.get("architecture_review_id"),
                    str,
                )
                and not isinstance(post_holdout_development_id, str)
            )
            if chosen_effective_axis.requires_reopen and decision.chosen.action not in {
                PortfolioAction.PRESERVE,
                PortfolioAction.PRUNE,
            }:
                raise TransitionError(
                    "deferred Portfolio axis requires an exact preserve/reopen "
                    "Decision before scientific work"
                )
            if (
                not chosen_effective_axis.selectable
                and not chosen_effective_axis.requires_reopen
            ):
                raise TransitionError(
                    "Portfolio Decision chosen axis is effectively blocked"
                )
            required_target_axis_ids = next_action.get("required_target_axis_ids")
            if required_target_axis_ids is not None and (
                not isinstance(required_target_axis_ids, list)
                or not required_target_axis_ids
                or required_target_axis_ids != sorted(set(required_target_axis_ids))
                or any(type(item) is not str for item in required_target_axis_ids)
                or any(
                    item not in option_eligible_targets
                    for item in required_target_axis_ids
                )
            ):
                raise TransitionError(
                    "Portfolio Decision bypasses its admitted constrained axis"
                )
            if (
                continuation is None
                and required_target_axis_ids is not None
                and decision.chosen.target_id not in required_target_axis_ids
            ):
                raise TransitionError(
                    "Portfolio Decision bypasses its admitted constrained axis"
                )
            constraint_source_id = next_action.get("constraint_source_id")
            if constraint_source_id is not None and (
                type(constraint_source_id) is not str
                or not constraint_source_id
                or not constraint_source_id.isascii()
            ):
                raise TransitionError("Portfolio Decision constraint source is invalid")
            if required_target_axis_ids is not None and constraint_source_id is None:
                raise TransitionError(
                    "Portfolio Decision constrained axes lack their exact source"
                )
            work_actions = {
                PortfolioAction.COMPLEMENTARY_SLEEVE,
                PortfolioAction.CONTRAST,
                PortfolioAction.DEEPEN,
                PortfolioAction.RECOMBINE,
                PortfolioAction.ROTATE,
                PortfolioAction.SYNTHESIZE,
            }
            from axiom_rift.operations.replay_projection import (
                ReplayProjectionError,
                ReplayTransitionError,
                is_exact_replay_protocol_revision_selection,
                validate_decision_selection,
                validate_replay_review_basis,
            )

            try:
                replay_constraints = validate_decision_selection(
                    _index,
                    mission_id=science["active_mission"],
                    next_action=next_action,
                    replay_obligation_ids=decision.replay_obligation_ids,
                    action=decision.chosen.action.value,
                    target_axis_id=decision.chosen.target_id,
                    work_actions=frozenset(item.value for item in work_actions),
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            from axiom_rift.operations.portfolio_decision_guard import (
                PortfolioDecisionGuardError,
                StructuralAxisSignature,
                require_replay_forest_alternative,
            )

            option_signatures: dict[
                str, StructuralAxisSignature | None
            ] = {}
            for option in decision.options:
                option_axis = axes_by_id[option.target_id]
                option_family = self._axis_prospective_architecture_family(
                    index=_index,
                    axis=option_axis,
                    baseline_override=(
                        decision.baseline_executable
                        if option.option_id == decision.chosen_option_id
                        and decision.baseline_executable is not None
                        else None
                    ),
                )
                if option_family is None:
                    try:
                        option_family = family_for_axis(
                            snapshot.payload,
                            option_axis,
                        )
                    except ProspectiveArchitectureProjectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                option_signatures[option.option_id] = StructuralAxisSignature(
                    axis_identity=option_axis["axis_identity"],
                    primary_research_layer=option_axis[
                        "primary_research_layer"
                    ],
                    semantic_architecture_family=option_family,
                )
            try:
                require_replay_forest_alternative(
                    decision,
                    replay_bound=replay_constraints is not None,
                    option_signatures=option_signatures,
                )
            except PortfolioDecisionGuardError as exc:
                raise TransitionError(str(exc)) from exc
            if review is not None:
                try:
                    validate_replay_review_basis(
                        constraints=replay_constraints,
                        selected_obligation_ids=decision.replay_obligation_ids,
                        review_basis=review_basis,
                    )
                except ReplayProjectionError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                except ReplayTransitionError as exc:
                    raise TransitionError(str(exc)) from exc
            diagnosis_constrained_generic_boundary = (
                generic_portfolio_boundary and replay_constraints is None
            )
            if (
                diagnosis_constrained_generic_boundary
                and diagnosis_binding is not None
                and not chosen_effective_axis.permits_generic_portfolio_action(
                    decision.chosen.action.value
                )
                and not (
                    diagnosis_binding.evidence_state == "engineering_gap"
                    and decision.engineering_reentry is not None
                    and decision.engineering_reentry.study_diagnosis_id
                    == diagnosis_binding.original_diagnosis_id
                )
            ):
                raise TransitionError(
                    "Portfolio Decision action is excluded by the latest "
                    "effective Study diagnosis"
                )
            if (
                diagnosis_constrained_generic_boundary
                and diagnosis_binding is not None
                and review is not None
                and not set(
                    diagnosis_binding.required_review_basis
                ).issubset(review_basis)
            ):
                raise TransitionError(
                    "quant-team review omits the latest effective axis "
                    "diagnosis authority"
                )
            scheduler_constraints = None
            if continuation is not None:
                scheduler_constraints = {
                    name: next_action[name]
                    for name in ARCHITECTURE_CONTINUATION_ACTION_FIELDS
                    if name in next_action
                }
            elif (
                required_target_axis_ids is not None
                or constraint_source_id is not None
            ):
                scheduler_constraints = {
                    "constraint_source_id": constraint_source_id,
                    "required_target_axis_ids": required_target_axis_ids,
                }
            if replay_constraints is not None:
                scheduler_constraints = {**(scheduler_constraints or {}), **replay_constraints}
            if (
                decision.recent_positive_lineage_id is not None
                and decision.recent_positive_lineage_id not in option_eligible_targets
                and _index.get("lineage", decision.recent_positive_lineage_id) is None
            ):
                raise TransitionError("recent-positive reference is not durable")
            target_axis = axes_by_id[decision.chosen.target_id]
            protocol_revision = decision.protocol_revision
            if protocol_revision is not None:
                from axiom_rift.operations.replay_projection import (
                    obligation_heads,
                    require_initial_completion_validity_revision_record,
                    require_scientific_change_return_record,
                    require_satisfaction_invalidation_record,
                )
                from axiom_rift.operations.semantic_question_registry import (
                    SemanticQuestionRegistryError,
                    SemanticQuestionRegistryIntegrityError,
                    require_semantic_question_study_binding,
                )
                from axiom_rift.operations.replay_projection import (
                    ReplayObligationStatus,
                )

                lineage = protocol_revision.semantic_question_lineage
                current_axis_architecture_authority = (
                    self._axis_architecture_authority_identity(
                        _index,
                        target_axis,
                    )
                )
                matching_obligations = tuple(
                    (obligation, head)
                    for obligation, head in obligation_heads(
                        _index,
                        mission_id=science["active_mission"],
                    )
                    if obligation.identity
                    == protocol_revision.replay_obligation_id
                )
                if (
                    decision.chosen.action
                    is not PortfolioAction.REVISE_PROTOCOL
                    or protocol_revision.mission_id
                    != science["active_mission"]
                    or protocol_revision.axis_id
                    != decision.chosen.target_id
                    or protocol_revision.predecessor_axis_identity
                    != target_axis.get("axis_identity")
                    or protocol_revision.mechanism_family
                    != target_axis.get("mechanism_family")
                    or protocol_revision.predecessor_architecture_family
                    != current_axis_architecture_authority
                    or lineage.successor_study_id
                    == lineage.predecessor_study_id
                    or _index.get("study-open", lineage.successor_study_id)
                    is not None
                    or len(matching_obligations) != 1
                ):
                    raise TransitionError(
                        "protocol revision authority differs from its current axis"
                    )
                obligation, obligation_head = matching_obligations[0]
                initial_completion_revision = (
                    protocol_revision.authority_kind
                    == "historical-scientific-validity-invalidation"
                )
                if obligation_head.status != ReplayObligationStatus.PENDING.value:
                    raise TransitionError(
                        "protocol revision lacks its current replay authority"
                    )
                if initial_completion_revision:
                    if (
                        obligation_head.kind != "historical-replay-obligation"
                        or obligation_head.record_id != obligation.identity
                    ):
                        raise TransitionError(
                            "initial protocol revision lacks its current replay "
                            "obligation"
                        )
                elif (
                    obligation_head.kind != protocol_revision.authority_kind
                    or obligation_head.record_id
                    != protocol_revision.authority_record_id
                ):
                    raise TransitionError(
                        "protocol revision lacks its current replay authority"
                    )
                try:
                    if (
                        protocol_revision.authority_kind
                        == "historical-replay-satisfaction-invalidation"
                    ):
                        require_satisfaction_invalidation_record(
                            _index,
                            obligation=obligation,
                            record=obligation_head,
                        )
                    elif (
                        protocol_revision.authority_kind
                        == "historical-replay-scientific-change-return"
                    ):
                        require_scientific_change_return_record(
                            _index,
                            obligation=obligation,
                            record=obligation_head,
                        )
                    else:
                        require_initial_completion_validity_revision_record(
                            _index,
                            obligation=obligation,
                            invalidation_record_id=(
                                protocol_revision.authority_record_id
                            ),
                        )
                    require_semantic_question_study_binding(
                        _index,
                        study_id=lineage.predecessor_study_id,
                        core_id=lineage.predecessor_core_id,
                    )
                except (
                    ReplayProjectionError,
                    SemanticQuestionRegistryIntegrityError,
                ) as exc:
                    raise RecoveryRequired(str(exc)) from exc
                except SemanticQuestionRegistryError as exc:
                    raise TransitionError(str(exc)) from exc
                if any(
                    ":" not in reference
                    or _index.get(*reference.split(":", 1)) is None
                    for reference in lineage.basis_record_ids
                ):
                    raise TransitionError(
                        "protocol revision lineage cites unavailable evidence"
                    )
                if (
                    review is not None
                    and (
                        protocol_revision.authority_kind,
                        protocol_revision.authority_record_id,
                    )
                    not in review_basis
                ):
                    raise TransitionError(
                        "quant-team review omits the protocol revision basis"
                    )
            baseline = decision.baseline_executable
            architecture = decision.architecture_chassis
            component_records: list[IndexRecord] = []
            baseline_provenance: dict[str, Any] | None = None
            resolved_architecture_family: str | None = None
            replacement_architecture_equivalence: dict[str, Any] | None = None
            prospective_reentry_equivalence: dict[str, Any] | None = None
            prospective_reentry_validation: dict[str, Any] | None = None
            replacement_replay_study: dict[str, Any] | None = None
            replacement_trigger_for_decision: IndexRecord | None = None
            source_authority_subject_ids: tuple[str, ...] = ()
            if baseline is not None:
                source_authority_subject_ids = self._source_authority_subject_ids(
                    baseline.to_identity_payload(),
                    error_type=TransitionError,
                )
                if isinstance(post_holdout_development_id, str):
                    required_holdout_id = science.get(
                        "required_future_holdout_id"
                    )
                    assert isinstance(required_holdout_id, str)
                    self._require_post_holdout_development_authority(
                        _index,
                        mission_id=science["active_mission"],
                        record_id=post_holdout_development_id,
                        required_holdout_id=required_holdout_id,
                        data_contract=baseline.data_contract,
                        split_contract=baseline.split_contract,
                    )
            if not self.engineering_fixture and decision.chosen.action in work_actions:
                if baseline is None or architecture is None:
                    raise TransitionError(
                        "scientific Portfolio Decision must bind a baseline Executable chassis"
                    )
                typed_axis_identity = target_axis.get(
                    "architecture_chassis_identity"
                )
                typed_axis_payload = target_axis.get("architecture_chassis")
                prior_anchor = self._axis_architecture_anchor(_index, target_axis)
                resolved_architecture_family = (
                    self._prospective_architecture_family_from_executable(
                        baseline
                    )
                )
                if decision.engineering_reentry is not None:
                    from axiom_rift.operations.prospective_engineering_reentry import (
                        ProspectiveEngineeringReentryValidationError,
                        require_prospective_engineering_reentry,
                    )

                    try:
                        prospective_reentry_validation = (
                            require_prospective_engineering_reentry(
                                _index,
                                artifact_reader=self.evidence.read_verified,
                                plan=decision.engineering_reentry,
                                mission_id=science["active_mission"],
                                portfolio_snapshot_id=snapshot.record_id,
                                portfolio_action=(
                                    decision.chosen.action.value
                                ),
                                target_axis=target_axis,
                                baseline_executable_id=baseline.identity,
                            )
                        )
                    except ProspectiveEngineeringReentryValidationError as exc:
                        raise TransitionError(str(exc)) from exc
                    required_reentry_basis = {
                        (item["kind"], item["record_id"])
                        for item in prospective_reentry_validation[
                            "required_review_basis"
                        ]
                    }
                    if review is None or not required_reentry_basis.issubset(
                        review_basis
                    ):
                        raise TransitionError(
                            "quant-team review omits prospective engineering "
                            "reentry authority"
                        )
                if isinstance(typed_axis_identity, str):
                    if not isinstance(typed_axis_payload, dict):
                        raise RecoveryRequired(
                            "typed Portfolio axis chassis payload is malformed"
                        )
                    accepted_axis_family = (
                        self._axis_prospective_architecture_family(
                            index=_index,
                            axis=target_axis,
                        )
                    )
                    try:
                        declared_axis_family = family_for_axis(
                            snapshot.payload,
                            target_axis,
                        )
                    except ProspectiveArchitectureProjectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    if (
                        accepted_axis_family is not None
                        and declared_axis_family is not None
                        and accepted_axis_family != declared_axis_family
                    ):
                        raise RecoveryRequired(
                            "Portfolio axis semantic family projection conflicts "
                            "with its accepted baseline"
                        )
                    typed_axis_family = (
                        accepted_axis_family
                        or declared_axis_family
                        or self._resolved_architecture_family(
                            index=_index,
                            architecture_payload=typed_axis_payload,
                        )
                    )
                    if (
                        typed_axis_family != resolved_architecture_family
                        and prospective_reentry_validation is not None
                    ):
                        prospective_reentry_equivalence = {
                            "accepted_axis_architecture_family": (
                                typed_axis_family
                            ),
                            "engineering_reentry_id": (
                                decision.engineering_reentry.identity
                            ),
                            "replacement_architecture_family": (
                                resolved_architecture_family
                            ),
                            "replacement_baseline_executable_id": (
                                baseline.identity
                            ),
                            "schema": (
                                "prospective_engineering_reentry_"
                                "equivalence.v1"
                            ),
                            "semantic_question_lineage_id": (
                                decision.engineering_reentry
                                .semantic_question_lineage.identity
                            ),
                            "successor_artifact_hash": (
                                decision.engineering_reentry
                                .successor_artifact_hash
                            ),
                            "successor_study_id": (
                                decision.engineering_reentry
                                .successor_study_id
                            ),
                            "target_axis_identity": target_axis[
                                "axis_identity"
                            ],
                        }
                    if (
                        typed_axis_family != resolved_architecture_family
                        and prospective_reentry_validation is None
                    ):
                        replacement_preflight = (
                            self._current_accepted_replay_replacement_preflight(
                                _index,
                                mission_id=science["active_mission"],
                                obligation_ids=decision.replay_obligation_ids,
                            )
                        )
                        replacement_trigger_for_decision = (
                            replacement_preflight
                        )
                        from axiom_rift.operations.replay_job_implementation_preflight import (
                            PREFLIGHT_SCHEMA,
                            ReplayJobImplementationPreflightError,
                            ReplayJobImplementationPreflightRequest,
                            derive_replay_job_scientific_surface,
                            replay_job_scientific_surface_hash,
                            require_active_replay_job_replacement_binding,
                            require_replacement_replay_baseline_semantics,
                            require_replacement_replay_study_semantics,
                        )
                        from axiom_rift.research.portfolio import BatchSpec
                        from axiom_rift.research.semantic_question import (
                            SemanticQuestionLineageProposal,
                            SemanticQuestionRelation,
                        )

                        try:
                            if not isinstance(
                                replacement_replay_study_payload,
                                Mapping,
                            ):
                                raise ReplayJobImplementationPreflightError(
                                    "replacement replay Study payload is absent"
                                )
                            if not isinstance(
                                replacement_replay_implementation_request,
                                ReplayJobImplementationPreflightRequest,
                            ):
                                raise ReplayJobImplementationPreflightError(
                                    "replacement replay implementation request is absent"
                                )
                            if not isinstance(
                                replacement_replay_batch_spec,
                                BatchSpec,
                            ):
                                raise ReplayJobImplementationPreflightError(
                                    "replacement replay Batch spec is absent"
                                )
                            if (
                                not isinstance(
                                    replacement_semantic_question_lineage,
                                    SemanticQuestionLineageProposal,
                                )
                                or replacement_semantic_question_lineage.relation
                                is not SemanticQuestionRelation.ENGINEERING_REENTRY
                                or replacement_semantic_question_lineage
                                .predecessor_core_id
                                != replacement_semantic_question_lineage
                                .successor_core_id
                                or replacement_semantic_question_lineage
                                .successor_core_id
                                != replacement_replay_study_payload.get(
                                    "semantic_question_core_id"
                                )
                            ):
                                raise ReplayJobImplementationPreflightError(
                                    "replacement replay engineering lineage is absent"
                                )
                            if (
                                replacement_replay_implementation_request
                                .replacement_for_preflight_id
                                is not None
                            ):
                                raise ReplayJobImplementationPreflightError(
                                    "active replacement request cannot replace a preflight"
                                )
                            replacement_replay_study = _copy(
                                replacement_replay_study_payload
                            )
                            active_surface = (
                                derive_replay_job_scientific_surface(
                                    replacement_replay_implementation_request,
                                    study_payload=(
                                        replacement_replay_study
                                    ),
                                    batch_payload={
                                        "spec": (
                                            replacement_replay_batch_spec
                                            .to_identity_payload()
                                        )
                                    },
                                    artifact_reader=(
                                        self.evidence.read_verified
                                    ),
                                )
                            )
                            active_surface_hash = (
                                replay_job_scientific_surface_hash(
                                    active_surface
                                )
                            )
                            require_active_replay_job_replacement_binding(
                                accepted_payload=(
                                    {}
                                    if replacement_preflight is None
                                    else replacement_preflight.payload
                                ),
                                active_payload={
                                    "callable_identity": (
                                        replacement_replay_implementation_request
                                        .callable_identity
                                    ),
                                    "executable_ids": list(
                                        replacement_replay_implementation_request
                                        .executable_ids
                                    ),
                                    "executable_manifests": [
                                        executable.to_identity_payload()
                                        for executable in (
                                            replacement_replay_implementation_request
                                            .executables
                                        )
                                    ],
                                    "implementation_identity": (
                                        replacement_replay_implementation_request
                                        .implementation_identity
                                    ),
                                    "mission_id": (
                                        replacement_replay_implementation_request
                                        .mission_id
                                    ),
                                    "protocol_id": (
                                        replacement_replay_implementation_request
                                        .protocol_id
                                    ),
                                    "replacement_for_preflight_id": None,
                                    "replay_obligation_ids": list(
                                        replacement_replay_implementation_request
                                        .replay_obligation_ids
                                    ),
                                    "schema": PREFLIGHT_SCHEMA,
                                    "scientific_surface": active_surface,
                                    "scientific_surface_hash": (
                                        active_surface_hash
                                    ),
                                },
                            )
                            baseline_equivalence_hash = (
                                require_replacement_replay_baseline_semantics(
                                    accepted_payload=(
                                        {}
                                        if replacement_preflight is None
                                        else replacement_preflight.payload
                                    ),
                                    baseline_executable_manifest=(
                                        baseline.to_identity_payload()
                                    ),
                                )
                            )
                            study_equivalence_hash = (
                                require_replacement_replay_study_semantics(
                                    accepted_payload=(
                                        {}
                                        if replacement_preflight is None
                                        else replacement_preflight.payload
                                    ),
                                    study_payload=replacement_replay_study,
                                )
                            )
                        except ReplayJobImplementationPreflightError as exc:
                            raise TransitionError(
                                "Portfolio Decision baseline differs from its "
                                "typed axis chassis"
                            ) from exc
                        assert replacement_preflight is not None
                        replacement_chassis = (
                            replacement_replay_study.get(
                                "controlled_chassis"
                            )
                            if isinstance(replacement_replay_study, Mapping)
                            else None
                        )
                        replacement_question = (
                            replacement_replay_study.get("question")
                            if isinstance(replacement_replay_study, Mapping)
                            else None
                        )
                        replacement_proposal = (
                            replacement_replay_study.get(
                                "semantic_proposal"
                            )
                            if isinstance(replacement_replay_study, Mapping)
                            else None
                        )
                        if (
                            baseline_equivalence_hash
                            != study_equivalence_hash
                            or not isinstance(replacement_chassis, Mapping)
                            or replacement_chassis.get(
                                "baseline_executable"
                            )
                            != baseline.to_identity_payload()
                            or replacement_chassis.get("architecture")
                            != architecture.to_identity_payload()
                            or replacement_replay_study.get("mission_id")
                            != science["active_mission"]
                            or replacement_replay_study.get(
                                "replay_obligation_ids"
                            )
                            != list(decision.replay_obligation_ids)
                            or replacement_replay_study.get(
                                "portfolio_action"
                            )
                            != decision.chosen.action.value
                            or replacement_replay_study.get(
                                "mechanism_family"
                            )
                            != target_axis.get("mechanism_family")
                            or replacement_replay_study.get(
                                "primary_research_layer"
                            )
                            != target_axis.get("primary_research_layer")
                            or replacement_replay_study.get(
                                "changed_domains"
                            )
                            != target_axis.get("changed_domains")
                            or replacement_replay_study.get(
                                "controlled_domains"
                            )
                            != target_axis.get("controlled_domains")
                            or not isinstance(replacement_question, Mapping)
                            or replacement_question.get("causal_question")
                            != target_axis.get("causal_question")
                            or not isinstance(replacement_proposal, Mapping)
                            or replacement_proposal.get("mechanism")
                            != target_axis.get("mechanism_family")
                        ):
                            raise TransitionError(
                                "Portfolio Decision replacement Study differs "
                                "from its reused axis"
                            )
                        replacement_study_binding_hash = _digest(
                            replacement_replay_study,
                            domain="replay-replacement-study-binding",
                        )
                        replacement_architecture_equivalence = {
                            "accepted_replacement_preflight_id": (
                                replacement_preflight.record_id
                            ),
                            "accepted_axis_architecture_family": (
                                typed_axis_family
                            ),
                            "replacement_architecture_family": (
                                resolved_architecture_family
                            ),
                            "replacement_baseline_executable_id": (
                                baseline.identity
                            ),
                            "replay_obligation_ids": list(
                                decision.replay_obligation_ids
                            ),
                            "replacement_executable_ids": list(
                                replacement_replay_implementation_request
                                .executable_ids
                            ),
                            "replacement_batch_id": (
                                replacement_replay_batch_spec.identity
                            ),
                            "replacement_request_identity": (
                                replacement_replay_implementation_request
                                .identity
                            ),
                            "replacement_lineage_id": (
                                replacement_semantic_question_lineage.identity
                            ),
                            "schema": (
                                "replay_replacement_architecture_equivalence.v1"
                            ),
                            "scientific_equivalence_hash": (
                                study_equivalence_hash
                            ),
                            "prospective_study_binding_hash": (
                                replacement_study_binding_hash
                            ),
                            "target_axis_identity": target_axis[
                                "axis_identity"
                            ],
                        }
                if not isinstance(typed_axis_identity, str) and prior_anchor is not None and (
                    (
                        self._prospective_architecture_family_from_executable(
                            prior_anchor["baseline_executable"]
                        )
                        if isinstance(
                            prior_anchor.get("baseline_executable"), Mapping
                        )
                        else self._resolved_architecture_family(
                            index=_index,
                            architecture_payload=prior_anchor[
                                "architecture_chassis"
                            ],
                        )
                        if isinstance(
                            prior_anchor.get("architecture_chassis"), Mapping
                        )
                        else prior_anchor["architecture_chassis_identity"]
                    )
                    != resolved_architecture_family
                ):
                    raise TransitionError(
                        "legacy Portfolio axis cannot change its prospective chassis anchor"
                    )
                if (
                    not isinstance(typed_axis_identity, str)
                    and prior_anchor is not None
                    and replacement_architecture_equivalence is None
                    and prospective_reentry_equivalence is None
                    and (
                        prior_anchor.get("baseline_executable_id")
                        != baseline.identity
                        or prior_anchor.get("baseline_executable")
                        != baseline.to_identity_payload()
                    )
                ):
                    raise TransitionError(
                        "legacy Portfolio axis cannot change its prospective "
                        "baseline anchor"
                    )
                prior_baseline = (
                    None
                    if (
                        replacement_architecture_equivalence is not None
                        or prospective_reentry_validation is not None
                    )
                    else self._prior_scientific_baseline(
                        _index,
                        baseline,
                        portfolio_axis_identity=target_axis[
                            "axis_identity"
                        ],
                    )
                )
                bootstrap_anchors = [
                    record
                    for record in _index.records_by_payload_text(
                        "portfolio-decision",
                        "target_axis_identity",
                        target_axis["axis_identity"],
                    )
                    if self._active_portfolio_decision(_index, record.record_id)
                    is not None
                    and record.payload.get("baseline_executable_id") == baseline.identity
                    and record.payload.get("baseline_executable")
                    == baseline.to_identity_payload()
                    and isinstance(record.payload.get("baseline_provenance"), dict)
                    and record.payload["baseline_provenance"].get("kind")
                    in {
                        "first_controlled_chassis_bootstrap",
                        "first_axis_controlled_chassis_bootstrap",
                    }
                    and record.payload.get("target_axis_identity")
                    == target_axis["axis_identity"]
                ]
                if len(bootstrap_anchors) > 1:
                    raise RecoveryRequired(
                        "controlled chassis has conflicting bootstrap anchors"
                    )
                has_data_contract_trials = any(
                    isinstance(record.payload.get("executable"), dict)
                    and record.payload["executable"].get("data_contract")
                    == baseline.data_contract
                    for record in _index.records_by_payload_text(
                        "trial",
                        "trial_data_contract",
                        baseline.data_contract,
                    )
                )
                axis_has_controlled_history = any(
                    isinstance(record.payload.get("controlled_chassis"), dict)
                    and record.payload.get("portfolio_axis_identity")
                    == target_axis["axis_identity"]
                    for record in _index.records_by_payload_text(
                        "study-open",
                        "portfolio_axis_identity",
                        target_axis["axis_identity"],
                    )
                )
                has_any_controlled_history = (
                    _index.has_controlled_chassis_study()
                )
                baseline_provenance = (
                    {
                        "kind": "accepted_prospective_engineering_reentry",
                        "record_id": decision.engineering_reentry.identity,
                    }
                    if prospective_reentry_validation is not None
                    else
                    {
                        "kind": "accepted_replay_replacement",
                        "record_id": replacement_architecture_equivalence[
                            "accepted_replacement_preflight_id"
                        ],
                    }
                    if replacement_architecture_equivalence is not None
                    else
                    {
                        "kind": "trial",
                        "record_id": prior_baseline.record_id,
                    }
                    if prior_baseline is not None
                    else {
                        "kind": "controlled_chassis_anchor_reuse",
                        "record_id": bootstrap_anchors[0].record_id,
                    }
                    if bootstrap_anchors
                    else {
                        "data_contract": baseline.data_contract,
                        **(
                            {
                                "kind": "first_axis_controlled_chassis_bootstrap",
                                "portfolio_axis_identity": target_axis[
                                    "axis_identity"
                                ],
                            }
                            if has_data_contract_trials
                            and has_any_controlled_history
                            and not axis_has_controlled_history
                            else {
                                "kind": (
                                    "first_controlled_chassis_bootstrap"
                                    if has_data_contract_trials
                                    else "first_data_contract_bootstrap"
                                )
                            }
                        ),
                    }
                )
                component_records = self._project_executable_components(
                    _index, baseline
                )
                effective_target = self._effective_axis_resolution(
                    _index,
                    target_axis,
                    prospective_source_ids=source_authority_subject_ids,
                )
                if not effective_target.selectable:
                    raise TransitionError(
                        "Portfolio Decision baseline uses an invalidated source; "
                        "a new SourceContract and axis are required"
                    )
            elif (
                not self.engineering_fixture
                and (baseline is not None or architecture is not None)
            ):
                raise TransitionError(
                    "structural Portfolio Decision cannot pre-register a Study baseline"
                )
            if (
                (
                    replacement_replay_study_payload is not None
                    or replacement_replay_implementation_request is not None
                    or replacement_replay_batch_spec is not None
                    or replacement_semantic_question_lineage is not None
                )
                and replacement_replay_study is None
            ):
                raise TransitionError(
                    "replacement replay Study authority is unnecessary"
                )
            target_architecture_identity = resolved_architecture_family
            if target_architecture_identity is None:
                target_architecture_identity = (
                    self._axis_resolved_architecture_family(
                        index=_index,
                        axis=target_axis,
                    )
                )
            try:
                diagnosis_authority = DiagnosisAuthorityContext.from_mapping(
                    next_action
                )
            except DiagnosisAuthorityContextError as exc:
                raise TransitionError(str(exc)) from exc
            diagnosis_id = diagnosis_authority.study_diagnosis_id
            diagnosis_correction_id = (
                diagnosis_authority.study_diagnosis_correction_id
            )
            diagnosis_correction_audit_id = (
                diagnosis_authority.diagnosis_correction_audit_id
            )
            diagnosis = None
            prospective_engineering_reentry = False
            if isinstance(diagnosis_id, str):
                from axiom_rift.operations.effective_study_diagnosis import (
                    EffectiveStudyDiagnosisError,
                    effective_study_diagnosis,
                )

                try:
                    diagnosis = effective_study_diagnosis(
                        _index,
                        diagnosis_id,
                    )
                except EffectiveStudyDiagnosisError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                observed_correction_id = (
                    None
                    if diagnosis.correction is None
                    else diagnosis.correction.record_id
                )
                if diagnosis_correction_id != observed_correction_id:
                    raise TransitionError(
                        "Portfolio Decision diagnosis correction is absent or stale"
                    )
                observed_audit_id = (
                    None
                    if diagnosis.correction is None
                    else diagnosis.correction.payload.get("audit_id")
                )
                if (
                    diagnosis_correction_audit_id is not None
                    and not isinstance(diagnosis_correction_audit_id, str)
                ) or (
                    diagnosis.correction is not None
                    and diagnosis_correction_audit_id != observed_audit_id
                ):
                    raise TransitionError(
                        "Portfolio Decision diagnosis correction audit is absent or stale"
                    )
                if isinstance(diagnosis_correction_audit_id, str):
                    audit_record = _index.get(
                        "study-diagnosis-correction-audit",
                        diagnosis_correction_audit_id,
                    )
                    if (
                        audit_record is None
                        or audit_record.subject
                        != f"Mission:{science['active_mission']}"
                    ):
                        raise RecoveryRequired(
                            "Portfolio Decision diagnosis correction audit is unavailable"
                        )
            diagnosis_architecture_identity: str | None = None
            if diagnosis is not None:
                diagnosis_study_id = diagnosis.payload.get("study_id")
                diagnosis_study = (
                    None
                    if not isinstance(diagnosis_study_id, str)
                    else _index.get("study-open", diagnosis_study_id)
                )
                if diagnosis_study is None:
                    raise RecoveryRequired(
                        "Portfolio Decision diagnosis lost its Study"
                    )
                diagnosis_architecture_identity = (
                    self._study_resolved_architecture_family(
                        index=_index,
                        study=diagnosis_study,
                    )
                )
            diagnosis_structural_forest_exit = False
            if isinstance(diagnosis_id, str):
                if (
                    diagnosis is None
                    or diagnosis.payload.get("mission_id")
                    != science["active_mission"]
                    or diagnosis.payload.get("portfolio_snapshot_id")
                    != snapshot.record_id
                ):
                    raise TransitionError(
                        "Portfolio Decision Study diagnosis is absent or stale"
                    )
                allowed_actions = set(diagnosis.payload.get("allowed_actions", []))
                allowed_layers = set(
                    diagnosis.payload.get("allowed_research_layers", [])
                )
                source_axis_id = diagnosis.payload.get("portfolio_axis_id")
                source_axis = axes_by_id.get(source_axis_id)
                chosen_action = decision.chosen.action.value
                same_axis_disposition = (
                    decision.chosen.target_id == source_axis_id
                    and chosen_action in {"preserve", "prune"}
                    and chosen_action in allowed_actions
                )
                branch_match = (
                    chosen_action not in {"preserve", "prune"}
                    and chosen_action in allowed_actions
                    and (
                        target_axis["primary_research_layer"] in allowed_layers
                        or chosen_action == "new_mechanism"
                    )
                )
                forest_diversion = (
                    source_axis is not None
                    and decision.chosen.target_id != source_axis_id
                    and chosen_action
                    in {
                        "complementary_sleeve",
                        "contrast",
                        "recombine",
                        "rotate",
                        "synthesize",
                    }
                    and (
                        target_axis["primary_research_layer"]
                        != source_axis["primary_research_layer"]
                        or (
                            isinstance(target_architecture_identity, str)
                            and target_architecture_identity
                            != diagnosis_architecture_identity
                        )
                    )
                )
                proposed_axis = decision.proposed_axis
                proposed_architecture_identity = (
                    None
                    if proposed_axis is None
                    else proposed_axis.system_architecture_family
                )
                if (
                    proposed_axis is not None
                    and proposed_axis.architecture_chassis is not None
                ):
                    from axiom_rift.research.chassis import (
                        ChassisIdentityError,
                        prospective_architecture_family_identity_from_chassis,
                    )

                    try:
                        proposed_architecture_identity = (
                            prospective_architecture_family_identity_from_chassis(
                                proposed_axis.architecture_chassis
                            )
                        )
                    except ChassisIdentityError as exc:
                        raise TransitionError(
                            "proposed axis lacks a prospective semantic family"
                        ) from exc
                diagnosis_structural_forest_exit = (
                    chosen_action == "new_mechanism"
                    and source_axis is not None
                    and proposed_axis is not None
                    and proposed_axis.axis_id not in axes_by_id
                    and proposed_axis.mechanism_family
                    not in {
                        axis.get("mechanism_family")
                        for axis in axes_by_id.values()
                    }
                    and (
                        proposed_axis.primary_research_layer.value
                        != source_axis.get("primary_research_layer")
                        or proposed_architecture_identity
                        != diagnosis_architecture_identity
                    )
                )
                diagnosis_basis = {
                    (item.get("kind"), item.get("record_id"))
                    for item in diagnosis.payload.get("evidence_basis", [])
                    if isinstance(item, Mapping)
                }
                replaced_preflight_id = (
                    None
                    if replacement_trigger_for_decision is None
                    else replacement_trigger_for_decision.payload.get(
                        "replacement_for_preflight_id"
                    )
                )
                engineering_reentry = (
                    diagnosis.payload.get("evidence_state")
                    == "engineering_gap"
                    and decision.chosen.target_id == source_axis_id
                    and chosen_action in {item.value for item in work_actions}
                    and target_axis["primary_research_layer"] in allowed_layers
                    and replacement_architecture_equivalence is not None
                    and replacement_semantic_question_lineage is not None
                    and replacement_semantic_question_lineage
                    .predecessor_study_id
                    == diagnosis.payload.get("study_id")
                    and {
                        "study-diagnosis:" + diagnosis_id,
                        "job-implementation-preflight:"
                        + replaced_preflight_id,
                    }.issubset(
                        set(
                            replacement_semantic_question_lineage
                            .basis_record_ids
                        )
                    )
                    and isinstance(replaced_preflight_id, str)
                    and (
                        "job-implementation-preflight",
                        replaced_preflight_id,
                    )
                    in diagnosis_basis
                )
                prospective_engineering_reentry = (
                    prospective_reentry_validation is not None
                    and decision.engineering_reentry is not None
                    and diagnosis.payload.get("evidence_state")
                    == "engineering_gap"
                    and decision.engineering_reentry.study_diagnosis_id
                    == diagnosis_id
                    and decision.engineering_reentry.predecessor_study_id
                    == diagnosis.payload.get("study_id")
                    and decision.chosen.target_id == source_axis_id
                    and chosen_action in {item.value for item in work_actions}
                    and target_axis["primary_research_layer"]
                    in allowed_layers
                )
                replay_protocol_revision = (
                    is_exact_replay_protocol_revision_selection(
                        constraints=replay_constraints,
                        selected_obligation_ids=(
                            decision.replay_obligation_ids
                        ),
                        action=chosen_action,
                        protocol_revision_obligation_id=(
                            None
                            if protocol_revision is None
                            else protocol_revision.replay_obligation_id
                        ),
                    )
                )
                if not (
                    same_axis_disposition
                    or branch_match
                    or forest_diversion
                    or diagnosis_structural_forest_exit
                    or engineering_reentry
                    or prospective_engineering_reentry
                    or replay_protocol_revision
                ):
                    raise TransitionError(
                        "Portfolio Decision does not follow or structurally exit its diagnosis"
                    )
                if engineering_reentry:
                    assert replacement_architecture_equivalence is not None
                    replacement_architecture_equivalence[
                        "engineering_gap_diagnosis_id"
                    ] = diagnosis_id
                if (
                    prospective_engineering_reentry
                    and prospective_reentry_equivalence is not None
                ):
                    prospective_reentry_equivalence[
                        "engineering_gap_diagnosis_id"
                    ] = diagnosis_id
                if (
                    review is not None
                    and ("study-diagnosis", diagnosis_id) not in review_basis
                ):
                    raise TransitionError(
                        "quant-team review omits its Study-diagnosis basis"
                    )
                if (
                    review is not None
                    and diagnosis.correction is not None
                    and (
                        "study-diagnosis-correction",
                        diagnosis.correction.record_id,
                    )
                    not in review_basis
                ):
                    raise TransitionError(
                        "quant-team review omits its effective diagnosis correction"
                    )
                if (
                    review is not None
                    and isinstance(diagnosis_correction_audit_id, str)
                    and (
                        "study-diagnosis-correction-audit",
                        diagnosis_correction_audit_id,
                    )
                    not in review_basis
                ):
                    raise TransitionError(
                        "quant-team review omits its diagnosis correction audit"
                    )
            if (
                decision.engineering_reentry is not None
                and not prospective_engineering_reentry
            ):
                raise TransitionError(
                    "prospective engineering reentry is not the exact "
                    "diagnosis continuation"
                )
            architecture_review_id = next_action.get("architecture_review_id")
            architecture_review = (
                None
                if not isinstance(architecture_review_id, str)
                else _index.get("architecture-review", architecture_review_id)
            )
            if isinstance(architecture_review_id, str) and (
                architecture_review is None
                or architecture_review.payload.get("mission_id")
                != science["active_mission"]
            ):
                raise TransitionError(
                    "Portfolio Decision architecture review is absent or stale"
                )
            if (
                review is not None
                and isinstance(architecture_review_id, str)
                and ("architecture-review", architecture_review_id)
                not in review_basis
            ):
                raise TransitionError(
                    "quant-team review omits its architecture-review basis"
                )
            excluded_architecture = next_action.get(
                "excluded_architecture_family"
            )
            excluded_layers = set(
                next_action.get("excluded_research_layers", [])
            )
            if architecture_review is not None:
                conclusion = architecture_review.payload.get("conclusion")
                if conclusion == "bounded_same_architecture":
                    if continuation is None:
                        raise TransitionError(
                            "bounded architecture review lost its continuation"
                        )
                    trigger = _index.get(
                        "architecture-review-trigger",
                        continuation.trigger_record_id,
                    )
                    if trigger is None:
                        raise RecoveryRequired(
                            "bounded architecture review trigger is unavailable"
                        )
                    try:
                        require_review_binding(
                            continuation,
                            review_record_id=architecture_review.record_id,
                            review_payload=architecture_review.payload,
                            trigger_payload=trigger.payload,
                        )
                        if self._review_resolved_architecture_family(
                            index=_index,
                            review=architecture_review,
                        ) != continuation.required_architecture_family:
                            raise ArchitectureReviewDirectionError(
                                "bounded architecture review family is no longer current"
                            )
                        required_axis_ids = set(
                            continuation.required_target_axis_ids
                        )
                        required_axis_ids.add(decision.chosen.target_id)
                        resolved_families = {
                            axis_id: self._axis_resolved_architecture_family(
                                index=_index,
                                axis=axes_by_id[axis_id],
                            )
                            for axis_id in required_axis_ids
                            if axis_id in axes_by_id
                        }
                        require_existing_axis_binding(
                            continuation,
                            axes_by_id=axes_by_id,
                            selectable_axis_ids=frozenset(
                                option_eligible_targets
                            ),
                            resolved_architecture_families=resolved_families,
                        )
                        require_decision_direction(
                            continuation,
                            action=decision.chosen.action.value,
                            target_axis_id=decision.chosen.target_id,
                            target_axis_identity=target_axis["axis_identity"],
                            target_architecture_family=target_architecture_identity,
                        )
                    except ArchitectureReviewDirectionError as exc:
                        raise TransitionError(str(exc)) from exc
                    if review is None or not required_quant_team_basis(
                        continuation
                    ).issubset(review_basis):
                        raise TransitionError(
                            "quant-team review omits bounded architecture bases"
                        )
                elif continuation is not None:
                    raise TransitionError(
                        "legacy architecture review carries a bounded continuation"
                    )
                elif conclusion == "rotate_architecture":
                    reviewed_family = self._review_resolved_architecture_family(
                        index=_index,
                        review=architecture_review,
                    )
                    if (
                        excluded_architecture != reviewed_family
                        or excluded_layers
                    ):
                        raise TransitionError(
                            "Portfolio Decision architecture constraint is malformed"
                        )
                elif conclusion == "change_research_layer":
                    if (
                        excluded_layers
                        != set(
                            architecture_review.payload.get(
                                "primary_research_layers", []
                            )
                        )
                        or excluded_architecture is not None
                    ):
                        raise TransitionError(
                            "Portfolio Decision layer constraint is malformed"
                        )
                else:
                    raise TransitionError(
                        "Portfolio Decision architecture conclusion is invalid"
                    )
            if decision.chosen.action != PortfolioAction.NEW_MECHANISM:
                if (
                    isinstance(excluded_architecture, str)
                    and not isinstance(target_architecture_identity, str)
                ):
                    raise TransitionError(
                        "Portfolio Decision cannot prove architecture rotation from a legacy name"
                    )
                if (
                    isinstance(excluded_architecture, str)
                    and target_architecture_identity == excluded_architecture
                ):
                    raise TransitionError(
                        "Portfolio Decision did not rotate the reviewed architecture"
                    )
                if target_axis["primary_research_layer"] in excluded_layers:
                    raise TransitionError(
                        "Portfolio Decision did not change the reviewed research layer"
                    )
            body = self._body(current)
            audit_deferred_prune_reopen = (
                decision.chosen.action is PortfolioAction.PRESERVE
                and chosen_effective_axis.requires_reopen
                and chosen_effective_axis.snapshot_status == "pruned"
            )
            next_kind = (
                "record_axis_reopen_authority"
                if audit_deferred_prune_reopen
                else (
                    "record_portfolio_snapshot"
                    if decision.chosen.action
                    in {
                        PortfolioAction.NEW_MECHANISM,
                        PortfolioAction.REVISE_PROTOCOL,
                        PortfolioAction.PRESERVE,
                        PortfolioAction.PRUNE,
                    }
                    else "execute_portfolio_decision"
                )
            )
            body["next_action"] = {
                "kind": next_kind,
                "decision_id": decision.identity,
                "action": decision.chosen.action.value,
                "target_id": decision.chosen.target_id,
                "target_axis_identity": target_axis["axis_identity"],
                "portfolio_snapshot_id": snapshot.record_id,
            }
            if isinstance(post_holdout_development_id, str):
                body["next_action"]["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            if decision.replay_obligation_ids:
                body["next_action"]["replay_obligation_ids"] = list(
                    decision.replay_obligation_ids
                )
            if protocol_revision is not None:
                body["next_action"]["protocol_revision_id"] = (
                    protocol_revision.identity
                )
            if audit_deferred_prune_reopen:
                from axiom_rift.research.effective_axis import (
                    axis_reopen_evidence,
                )

                body["next_action"].update(
                    axis_reopen_evidence(
                        chosen_effective_axis
                    ).to_action_fields()
                )
            if next_kind == "execute_portfolio_decision" and not self.engineering_fixture:
                assert baseline is not None and architecture is not None
                body["next_action"].update(
                    {
                        "architecture_chassis_identity": architecture.identity,
                        "resolved_architecture_family": resolved_architecture_family,
                        "baseline_executable_id": baseline.identity,
                    }
                )
                if isinstance(diagnosis_id, str):
                    body["next_action"]["study_diagnosis_id"] = diagnosis_id
                if isinstance(diagnosis_correction_id, str):
                    body["next_action"]["study_diagnosis_correction_id"] = (
                        diagnosis_correction_id
                    )
                if isinstance(diagnosis_correction_audit_id, str):
                    body["next_action"]["diagnosis_correction_audit_id"] = (
                        diagnosis_correction_audit_id
                    )
                if isinstance(architecture_review_id, str):
                    body["next_action"]["architecture_review_id"] = (
                        architecture_review_id
                    )
                if isinstance(scheduler_constraints, Mapping):
                    body["next_action"].update(
                        {
                            name: scheduler_constraints[name]
                            for name in ARCHITECTURE_CONTINUATION_ACTION_FIELDS
                            if name in scheduler_constraints
                        }
                    )
                if replacement_architecture_equivalence is not None:
                    body["next_action"][
                        "replacement_architecture_equivalence"
                    ] = replacement_architecture_equivalence
                if prospective_reentry_validation is not None:
                    body["next_action"].update(
                        {
                            "engineering_reentry_id": (
                                decision.engineering_reentry.identity
                            ),
                            "engineering_reentry_validation": (
                                prospective_reentry_validation
                            ),
                        }
                    )
                    if prospective_reentry_equivalence is not None:
                        body["next_action"][
                            "prospective_reentry_equivalence"
                        ] = prospective_reentry_equivalence
            if next_kind == "record_portfolio_snapshot" and (
                decision.chosen.action == PortfolioAction.NEW_MECHANISM
            ):
                constraint_source_id = next_action.get("constraint_source_id")
                if continuation is not None:
                    body["next_action"].update(continuation.to_action_fields())
                    constraint_source_id = continuation.architecture_review_id
                elif (
                    isinstance(diagnosis_id, str)
                    and not diagnosis_structural_forest_exit
                ):
                    body["next_action"]["required_followup_layers"] = list(
                        diagnosis.payload["allowed_research_layers"]
                    )
                    constraint_source_id = diagnosis_id
                if isinstance(excluded_architecture, str):
                    body["next_action"]["excluded_architecture_family"] = (
                        excluded_architecture
                    )
                if excluded_layers:
                    body["next_action"]["excluded_research_layers"] = sorted(
                        excluded_layers
                    )
                if (
                    "required_followup_layers" in body["next_action"]
                    or "excluded_architecture_family" in body["next_action"]
                    or "excluded_research_layers" in body["next_action"]
                ):
                    if not isinstance(constraint_source_id, str):
                        raise TransitionError(
                            "constrained new mechanism lacks its exact source"
                        )
                    body["next_action"]["constraint_source_id"] = (
                        constraint_source_id
                    )
            if next_kind in {
                "record_axis_reopen_authority",
                "record_portfolio_snapshot",
            }:
                body["next_action"] = self._with_replay_scheduler_constraints(
                    body["next_action"],
                    replay_constraints,
                )
            record = _record(
                kind="portfolio-decision",
                record_id=decision.identity,
                subject=f"Mission:{science['active_mission']}",
                status=decision.chosen.action.value,
                fingerprint=decision_hash,
                payload={
                    **decision.to_identity_payload(),
                    "architecture_review_id": architecture_review_id,
                    "baseline_provenance": baseline_provenance,
                    "effective_axis": effective_axes[
                        decision.chosen.target_id
                    ].to_projection_payload(),
                    "portfolio_snapshot_id": snapshot.record_id,
                    "post_holdout_development_id": (
                        post_holdout_development_id
                    ),
                    "scheduler_constraints": scheduler_constraints,
                    "source_authority_subject_ids": list(
                        source_authority_subject_ids
                    ),
                    "diagnosis_correction_audit_id": (
                        diagnosis_correction_audit_id
                    ),
                    "study_diagnosis_id": diagnosis_id,
                    "study_diagnosis_correction_id": diagnosis_correction_id,
                    "target_axis_identity": target_axis["axis_identity"],
                    "resolved_architecture_family": resolved_architecture_family,
                    "replacement_architecture_equivalence": (
                        replacement_architecture_equivalence
                    ),
                    "engineering_reentry_validation": (
                        prospective_reentry_validation
                    ),
                    "prospective_reentry_equivalence": (
                        prospective_reentry_equivalence
                    ),
                },
            )
            return body, [*component_records, record], {
                "decision_id": decision.identity
            }

        return self._commit(
            event_kind="portfolio_decision_recorded",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={"decision_id": decision.identity},
            prepare=prepare,
        )
