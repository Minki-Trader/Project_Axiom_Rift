"""Study admission, architecture authority, and replay-entry preparation.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.diagnosis_authority_context import (
    DiagnosisAuthorityContext,
    DiagnosisAuthorityContextError,
)
from axiom_rift.operations.permits import Permit, PermitKind, SubjectKind
from axiom_rift.operations.writer_portfolio_withdrawal import (
    PortfolioWithdrawalWriterMixin,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _digest,
    _record,
    _require_ascii,
    _require_digest,
    _require_manifest,
    _require_study_evidence_modes,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView
from axiom_rift.storage.state import WriterLock
from axiom_rift.storage.study_kpi import validate_study_id


@dataclass(frozen=True, slots=True)
class _StudyPortfolioPlan:
    """Validated Portfolio authority needed by the remaining Study admission."""

    portfolio_snapshot_id: str | None
    mechanism_family: str | None
    primary_research_layer: str | None
    system_architecture_family: str | None
    portfolio_architecture_family: str | None
    changed_domains: list[str] | None
    controlled_domains: list[str] | None
    portfolio_action: str | None
    commitment_batches: int | None
    post_holdout_development_id: str | None
    replay_obligation_ids: tuple[str, ...]
    replacement_preflight: IndexRecord | None


class StudyAdmissionWriterMixin:
    """Own Study admission while the facade retains atomic persistence."""
    @staticmethod
    def _require_post_holdout_development_authority(
        index: LocalIndex,
        *,
        mission_id: str,
        record_id: str,
        required_holdout_id: str,
        data_contract: str | None = None,
        split_contract: str | None = None,
    ) -> tuple[IndexRecord, IndexRecord]:
        """Rejoin one future-development authority to its material and holdout."""

        if (
            type(record_id) is not str
            or len(record_id) != 64
            or any(character not in "0123456789abcdef" for character in record_id)
        ):
            raise TransitionError(
                "post-holdout development authority identity is invalid"
            )
        authority = index.get("post-holdout-development", record_id)
        payload = {} if authority is None else authority.payload
        material_identity = payload.get("material_identity")
        material = (
            None
            if not isinstance(material_identity, str)
            else index.get("development-material", material_identity)
        )
        holdout = index.get("holdout-seal", required_holdout_id)
        expected_id = (
            None
            if not isinstance(material_identity, str)
            else canonical_digest(
                domain="post-holdout-development",
                payload={
                    "holdout_id": required_holdout_id,
                    "material_identity": material_identity,
                    "mission_id": mission_id,
                },
            )
        )
        if (
            authority is None
            or authority.status != "accepted"
            or authority.record_id != expected_id
            or authority.subject != f"Material:{material_identity}"
            or payload.get("mission_id") != mission_id
            or payload.get("holdout_id") != required_holdout_id
            or authority.authority_sequence is None
            or authority.authority_event_id is None
            or material is None
            or material.status != "accepted"
            or material.subject != f"Mission:{mission_id}"
            or material.payload.get("post_holdout_development_id") != record_id
            or material.payload.get("material_identity") != material_identity
            or material.authority_sequence != authority.authority_sequence
            or material.authority_event_id != authority.authority_event_id
            or holdout is None
            or holdout.status != "sealed_unrevealed"
            or index.event_head(f"holdout-reveal:{required_holdout_id}") is not None
            or (
                data_contract is not None
                and data_contract != f"data:{material_identity}"
            )
            or (
                split_contract is not None
                and split_contract != f"split:{payload.get('split_identity')}"
            )
        ):
            raise TransitionError(
                "post-holdout development authority is absent, stale, or misbound"
        )
        return authority, material

    @classmethod
    def _require_post_holdout_decision_binding(
        cls,
        index: LocalIndex,
        *,
        science: Mapping[str, Any],
        decision: IndexRecord,
        next_action: Mapping[str, Any] | None = None,
        data_contract: str | None = None,
        split_contract: str | None = None,
    ) -> tuple[str | None, IndexRecord | None]:
        """Revalidate and rejoin one Decision-carried development authority."""

        record_id = decision.payload.get("post_holdout_development_id")
        if (
            next_action is not None
            and next_action.get("post_holdout_development_id") != record_id
        ):
            raise TransitionError(
                "post-holdout development authority drifted from its Decision"
            )
        if record_id is None:
            return None, None
        mission_id = science.get("active_mission")
        required_holdout_id = science.get("required_future_holdout_id")
        if (
            science.get("holdout_reveals", 0) < 1
            or not isinstance(mission_id, str)
            or not isinstance(required_holdout_id, str)
            or not isinstance(record_id, str)
        ):
            raise TransitionError(
                "post-holdout Decision authority is malformed"
            )
        _, material = cls._require_post_holdout_development_authority(
            index,
            mission_id=mission_id,
            record_id=record_id,
            required_holdout_id=required_holdout_id,
            data_contract=data_contract,
            split_contract=split_contract,
        )
        return record_id, material

    @staticmethod
    def _historical_replay_obligation_heads(
        index: LocalIndex,
        *,
        mission_id: str,
    ) -> tuple[tuple[Any, IndexRecord], ...]:
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            obligation_heads,
        )

        try:
            return obligation_heads(index, mission_id=mission_id)
        except ReplayProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc

    @classmethod
    def _replay_scheduler_constraints(
        cls,
        index: LocalIndex,
        *,
        mission_id: str,
    ) -> dict[str, Any] | None:
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            scheduler_constraints,
        )

        try:
            return scheduler_constraints(index, mission_id=mission_id)
        except ReplayProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc

    @staticmethod
    def _with_replay_scheduler_constraints(
        action: Mapping[str, Any],
        constraints: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        from axiom_rift.operations.replay_projection import (
            with_scheduler_constraints,
        )

        return with_scheduler_constraints(action, constraints)

    @staticmethod
    def _effective_axis_resolution(
        index: LocalIndex,
        axis: Mapping[str, Any],
        *,
        prospective_source_ids: Sequence[str] = (),
    ) -> Any:
        from axiom_rift.operations.effective_axis_projection import (
            EffectiveAxisProjectionError,
            effective_axis_resolution,
        )

        try:
            return effective_axis_resolution(
                index,
                axis,
                prospective_source_ids=prospective_source_ids,
            )
        except EffectiveAxisProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc

    @staticmethod
    def _source_authority_subject_ids(
        executable: Mapping[str, Any],
        *,
        error_type: type[Exception],
    ) -> tuple[str, ...]:
        """Derive source-authority subjects without widening performance use."""

        from axiom_rift.operations.effective_axis_projection import (
            EffectiveAxisProjectionError,
            source_authority_subject_ids,
        )

        try:
            return source_authority_subject_ids(executable)
        except EffectiveAxisProjectionError as exc:
            raise error_type(str(exc)) from exc

    @staticmethod
    def _effective_axis_resolutions(
        index: LocalIndex | LocalIndexView,
        axes: Sequence[Mapping[str, Any]],
        *,
        prospective_source_ids_by_axis: Mapping[
            str, Sequence[str]
        ] | None = None,
    ) -> tuple[Any, ...]:
        from axiom_rift.operations.effective_axis_projection import (
            EffectiveAxisProjectionError,
            effective_axis_resolutions,
        )

        try:
            return effective_axis_resolutions(
                index,
                axes,
                prospective_source_ids_by_axis=(
                    prospective_source_ids_by_axis
                ),
            )
        except EffectiveAxisProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc

    @staticmethod
    def _mission_effective_axis_blockers(
        index: LocalIndex,
        *,
        mission_id: str,
    ) -> tuple[Any, ...]:
        from axiom_rift.operations.effective_axis_projection import (
            EffectiveAxisProjectionError,
            mission_effective_axis_blockers,
        )

        try:
            return mission_effective_axis_blockers(
                index,
                mission_id=mission_id,
            )
        except EffectiveAxisProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc

    @staticmethod
    def _axis_architecture_anchor(
        index: LocalIndex | LocalIndexView,
        axis: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        typed_identity = axis.get("architecture_chassis_identity")
        typed_payload = axis.get("architecture_chassis")
        if isinstance(typed_identity, str):
            if not isinstance(typed_payload, dict):
                raise RecoveryRequired("typed Portfolio axis chassis is malformed")
            return {
                "architecture_chassis": dict(typed_payload),
                "architecture_chassis_identity": typed_identity,
                "baseline_executable": None,
                "baseline_executable_id": None,
            }
        axis_identity = axis.get("axis_identity")
        if not isinstance(axis_identity, str):
            raise RecoveryRequired("legacy Portfolio axis identity is malformed")
        anchors: dict[tuple[str, str], dict[str, Any]] = {}
        for record in index.records_by_payload_text(
            "portfolio-decision",
            "target_axis_identity",
            axis_identity,
        ):
            if PortfolioWithdrawalWriterMixin._active_portfolio_decision(index, record.record_id) is None:
                continue
            payload = record.payload
            architecture_identity = payload.get("architecture_chassis_identity")
            baseline_id = payload.get("baseline_executable_id")
            if (
                payload.get("target_axis_identity") != axis_identity
                or not isinstance(architecture_identity, str)
                or not isinstance(baseline_id, str)
            ):
                continue
            anchor = {
                "architecture_chassis": payload.get("architecture_chassis"),
                "architecture_chassis_identity": architecture_identity,
                "baseline_executable": payload.get("baseline_executable"),
                "baseline_executable_id": baseline_id,
            }
            anchors[(architecture_identity, baseline_id)] = anchor
        if len(anchors) > 1:
            raise RecoveryRequired(
                "legacy Portfolio axis has conflicting prospective chassis anchors"
            )
        return None if not anchors else next(iter(anchors.values()))

    @staticmethod
    def _axis_architecture_authority_identity(
        index: LocalIndex | LocalIndexView,
        axis: Mapping[str, Any],
    ) -> str:
        """Return the exact typed or legacy-anchored chassis authority."""

        anchor = StudyAdmissionWriterMixin._axis_architecture_anchor(index, axis)
        identity = (
            None
            if anchor is None
            else anchor.get("architecture_chassis_identity")
        )
        if isinstance(identity, str):
            return identity
        legacy = axis.get("system_architecture_family")
        if not isinstance(legacy, str):
            raise RecoveryRequired(
                "Portfolio axis architecture authority is unavailable"
            )
        return legacy

    def _require_registered_chassis_baseline(
        self,
        *,
        index: LocalIndex,
        controlled_chassis: Any,
        decision: IndexRecord,
    ) -> None:
        baseline = controlled_chassis.baseline_executable
        baseline_payload = baseline.to_identity_payload()
        provenance = decision.payload.get("baseline_provenance")
        if (
            decision.payload.get("baseline_executable_id") != baseline.identity
            or decision.payload.get("baseline_executable") != baseline_payload
            or not isinstance(provenance, dict)
        ):
            raise TransitionError(
                "controlled chassis baseline differs from its accepted Decision"
            )
        target_axis_identity = decision.payload.get("target_axis_identity")
        if not isinstance(target_axis_identity, str):
            raise TransitionError(
                "controlled chassis baseline lacks its target axis identity"
            )
        replacement_equivalence = decision.payload.get(
            "replacement_architecture_equivalence"
        )
        prospective_equivalence = decision.payload.get(
            "prospective_reentry_equivalence"
        )
        prospective_plan = decision.payload.get("engineering_reentry")
        prospective_validation = decision.payload.get(
            "engineering_reentry_validation"
        )
        replacement_provenance = (
            provenance.get("kind") == "accepted_replay_replacement"
        )
        prospective_reentry_provenance = (
            provenance.get("kind")
            == "accepted_prospective_engineering_reentry"
        )
        prior = (
            None
            if replacement_provenance or prospective_reentry_provenance
            else self._prior_scientific_baseline(
                index,
                baseline,
                portfolio_axis_identity=target_axis_identity,
            )
        )
        if replacement_provenance:
            preflight_id = (
                replacement_equivalence.get(
                    "accepted_replacement_preflight_id"
                )
                if isinstance(replacement_equivalence, Mapping)
                else None
            )
            replacement_ids = (
                replacement_equivalence.get("replacement_executable_ids")
                if isinstance(replacement_equivalence, Mapping)
                else None
            )
            if (
                provenance
                != {
                    "kind": "accepted_replay_replacement",
                    "record_id": preflight_id,
                }
                or not isinstance(replacement_ids, list)
                or not replacement_ids
                or any(
                    not isinstance(executable_id, str)
                    or not executable_id.startswith("executable:")
                    for executable_id in replacement_ids
                )
                or len(replacement_ids) != len(set(replacement_ids))
                or replacement_equivalence.get(
                    "replacement_baseline_executable_id"
                )
                != baseline.identity
                or replacement_equivalence.get("target_axis_identity")
                != target_axis_identity
                or index.get("trial", baseline.identity) is not None
            ):
                raise TransitionError(
                    "controlled chassis replacement baseline authority is invalid"
                )
        elif prospective_reentry_provenance:
            reentry_id = decision.payload.get("engineering_reentry_id")
            if (
                not isinstance(prospective_plan, Mapping)
                or prospective_plan.get("schema")
                != "prospective_engineering_reentry.v1"
                or not isinstance(prospective_validation, Mapping)
                or prospective_validation.get("schema")
                != "prospective_engineering_reentry_validation.v1"
                or provenance
                != {
                    "kind": "accepted_prospective_engineering_reentry",
                    "record_id": reentry_id,
                }
                or prospective_validation.get("engineering_reentry_id")
                != reentry_id
                or prospective_plan.get("successor_baseline_executable_id")
                != baseline.identity
                or prospective_validation.get(
                    "successor_baseline_executable_id"
                )
                != baseline.identity
                or prospective_plan.get("target_axis_identity")
                != target_axis_identity
                or index.get("trial", baseline.identity) is not None
                or (
                    prospective_equivalence is not None
                    and (
                        not isinstance(prospective_equivalence, Mapping)
                        or prospective_equivalence.get("schema")
                        != "prospective_engineering_reentry_equivalence.v1"
                        or prospective_equivalence.get(
                            "engineering_reentry_id"
                        )
                        != reentry_id
                        or prospective_equivalence.get(
                            "replacement_baseline_executable_id"
                        )
                        != baseline.identity
                        or prospective_equivalence.get(
                            "target_axis_identity"
                        )
                        != target_axis_identity
                    )
                )
            ):
                raise TransitionError(
                    "controlled chassis prospective reentry baseline "
                    "authority is invalid"
                )
        elif provenance.get("kind") == "trial":
            if prior is None or provenance.get("record_id") != prior.record_id:
                raise TransitionError(
                    "controlled chassis baseline lost its prior scientific trial"
                )
        elif provenance.get("kind") == "controlled_chassis_anchor_reuse":
            anchor_id = provenance.get("record_id")
            anchor = (
                None
                if not isinstance(anchor_id, str)
                else self._active_portfolio_decision(index, anchor_id)
            )
            if (
                prior is not None
                or anchor is None
                or anchor.payload.get("baseline_executable_id") != baseline.identity
                or anchor.payload.get("baseline_executable") != baseline_payload
                or not isinstance(anchor.payload.get("baseline_provenance"), dict)
                or anchor.payload["baseline_provenance"].get("kind")
                not in {
                    "first_controlled_chassis_bootstrap",
                    "first_axis_controlled_chassis_bootstrap",
                }
            ):
                raise TransitionError(
                    "controlled chassis bootstrap anchor reuse is invalid"
                )
        else:
            relevant_trials = list(
                index.records_by_payload_text(
                    "trial",
                    "trial_data_contract",
                    baseline.data_contract,
                )
            )
            axis_controlled_history = [
                record
                for record in index.records_by_payload_text(
                    "study-open",
                    "portfolio_axis_identity",
                    target_axis_identity,
                )
                if isinstance(record.payload.get("controlled_chassis"), dict)
            ]
            has_any_controlled_history = (
                index.has_controlled_chassis_study()
            )
            expected_bootstrap = (
                {
                    "data_contract": baseline.data_contract,
                    "kind": "first_axis_controlled_chassis_bootstrap",
                    "portfolio_axis_identity": target_axis_identity,
                }
                if relevant_trials
                and has_any_controlled_history
                and not axis_controlled_history
                else {
                    "data_contract": baseline.data_contract,
                    "kind": (
                        "first_controlled_chassis_bootstrap"
                        if relevant_trials
                        else "first_data_contract_bootstrap"
                    ),
                }
            )
            if (
                provenance != expected_bootstrap
                or prior is not None
                or (
                    relevant_trials
                    and axis_controlled_history
                    and provenance.get("kind")
                    != "controlled_chassis_anchor_reuse"
                )
            ):
                raise TransitionError(
                    "controlled chassis baseline bootstrap is no longer valid"
                )
        for component, component_id in zip(
            baseline.components, baseline.component_identities, strict=True
        ):
            expected = self._component_manifest_record(
                component_id=component_id,
                manifest=component.to_identity_payload(),
            )
            existing = index.get("component-manifest", component_id)
            if existing is None:
                raise TransitionError(
                    "controlled chassis baseline component is not registered"
                )
            self._require_component_manifest_projection(index, expected)

    @staticmethod
    def _prior_scientific_baseline(
        index: LocalIndex,
        baseline: Any,
        portfolio_axis_identity: str | None = None,
    ) -> IndexRecord | None:
        if portfolio_axis_identity is not None:
            _require_ascii("Portfolio axis identity", portfolio_axis_identity)
        baseline_payload = baseline.to_identity_payload()
        exact = index.get("trial", baseline.identity)
        exact_executable = (
            None if exact is None else exact.payload.get("executable")
        )
        if not (
            isinstance(exact_executable, dict)
            and exact_executable.get("data_contract") == baseline.data_contract
        ):
            relevant = bool(
                index.records_by_payload_text(
                    "trial",
                    "trial_data_contract",
                    baseline.data_contract,
                )
            )
            if not relevant:
                return None
        if exact is None:
            data_contract_history = tuple(
                index.records_by_payload_text(
                    "study-open",
                    "study_open_baseline_data_contract",
                    baseline.data_contract,
                )
            )
            controlled_history = tuple(
                record
                for record in data_contract_history
                if portfolio_axis_identity is None
                or record.payload.get("portfolio_axis_identity")
                == portfolio_axis_identity
            )
            candidate_axis_identities = tuple(
                sorted(
                    {
                        value
                        for value in (
                            record.payload.get("portfolio_axis_identity")
                            for record in controlled_history
                        )
                        if isinstance(value, str)
                    }
                )
            )
            decision_candidates = (
                index.records_by_payload_text(
                    "portfolio-decision",
                    "target_axis_identity",
                    portfolio_axis_identity,
                )
                if portfolio_axis_identity is not None
                else index.records_by_payload_text_values(
                    "portfolio-decision",
                    "target_axis_identity",
                    candidate_axis_identities,
                )
            )
            accepted_bootstrap_anchors = [
                record
                for record in decision_candidates
                if PortfolioWithdrawalWriterMixin._active_portfolio_decision(index, record.record_id)
                is not None
                and record.payload.get("baseline_executable_id") == baseline.identity
                and record.payload.get("baseline_executable") == baseline_payload
                and isinstance(record.payload.get("baseline_provenance"), dict)
                and record.payload["baseline_provenance"].get("kind")
                in {
                    "first_controlled_chassis_bootstrap",
                    "first_axis_controlled_chassis_bootstrap",
                }
                and (
                    portfolio_axis_identity is None
                    or record.payload.get("target_axis_identity")
                    == portfolio_axis_identity
                )
            ]
            if not controlled_history or accepted_bootstrap_anchors:
                return None
        study_id = None if exact is None else exact.payload.get("study_id")
        study = (
            None
            if not isinstance(study_id, str)
            else index.get("study-open", study_id)
        )
        if (
            exact is None
            or exact.status != "evaluated"
            or exact.fingerprint != baseline.identity.removeprefix("executable:")
            or exact.payload.get("scientific_eligible") is not True
            or exact.payload.get("engineering_fixture") is not False
            or exact.payload.get("executable") != baseline_payload
            or study is None
            or exact.payload.get("mission_id") != study.payload.get("mission_id")
        ):
            raise TransitionError(
                "Portfolio Decision baseline must reuse a prior scientific Executable"
            )
        return exact

    def _require_component_parity_payload(
        self,
        *,
        index: LocalIndex,
        equivalence: Mapping[str, Any],
        mission_id: str,
        portfolio_decision_id: str | None,
    ) -> None:
        completion_id = equivalence.get("completion_record_id")
        parity_manifest_hash = equivalence.get("parity_manifest_hash")
        try:
            _require_digest("component parity completion", completion_id)
            _require_digest("component parity manifest", parity_manifest_hash)
        except (TypeError, ValueError) as exc:
            raise TransitionError("component parity authority is malformed") from exc
        completion = index.get("job-completed", completion_id)
        if completion is None or completion.status != "success":
            raise TransitionError(
                "component parity requires a successful registered-validator Job completion"
            )
        job_id = completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        binding = (
            None
            if declaration is None
            else declaration.payload.get("spec", {}).get("component_parity_binding")
        )
        parity = completion.payload.get("component_parity")
        expected = {
            "canonical_component_id": equivalence.get("canonical_component_id"),
            "canonical_component_manifest": equivalence.get(
                "canonical_component_manifest"
            ),
            "dimensions": equivalence.get("dimensions"),
            "equivalent_component_id": equivalence.get("equivalent_component_id"),
            "equivalent_component_manifest": equivalence.get(
                "equivalent_component_manifest"
            ),
        }
        if (
            declaration is None
            or declaration.fingerprint != completion.fingerprint
            or declaration.payload.get("mission_id") != mission_id
            or not isinstance(binding, dict)
            or (
                portfolio_decision_id is not None
                and binding.get("portfolio_decision_id") != portfolio_decision_id
            )
            or any(binding.get(name) != value for name, value in expected.items())
            or not isinstance(parity, dict)
            or parity.get("equivalent") is not True
            or parity.get("result_manifest_hash") != parity_manifest_hash
            or any(parity.get(name) != value for name, value in expected.items())
        ):
            raise TransitionError(
                "component parity completion differs from its typed endpoints"
            )
        trace = parity.get("validation_trace")
        measurement_hashes = parity.get("measurement_artifact_hashes")
        if (
            not isinstance(trace, dict)
            or trace.get("validator_id") != binding.get("validator_id")
            or type(trace.get("declared_artifact_count")) is not int
            or trace.get("declared_artifact_count", 0) <= 0
            or trace.get("declared_artifact_count")
            != trace.get("opened_artifact_count")
            or not isinstance(measurement_hashes, list)
            or not measurement_hashes
        ):
            raise TransitionError(
                "component parity lacks a complete registered-validator trace"
            )
        decisions = index.records_by_subject_status(
            subject=f"Job:{job_id}", status="accept_component_parity"
        )
        if not any(
            record.payload.get("completion_record_id") == completion_id
            for record in decisions
        ):
            raise TransitionError("component parity Job has not been accepted by Writer")
        for artifact_hash in [parity_manifest_hash, *measurement_hashes]:
            try:
                self.evidence.verify(artifact_hash)
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "component parity evidence bytes are unavailable"
                ) from exc

    def _require_component_parity_evidence(
        self,
        *,
        index: LocalIndex,
        controlled_chassis: Any,
        mission_id: str,
        portfolio_decision_id: str,
    ) -> None:
        """Verify every equivalence through Writer-accepted validator completions."""

        from axiom_rift.research.chassis import ControlledStudyChassis

        if not isinstance(controlled_chassis, ControlledStudyChassis):
            raise TransitionError("controlled component chassis is not typed")
        for equivalence in controlled_chassis.equivalences:
            self._require_component_parity_payload(
                index=index,
                equivalence=equivalence.to_identity_payload(),
                mission_id=mission_id,
                portfolio_decision_id=portfolio_decision_id,
            )

    @staticmethod
    def _component_parity_member_records(
        *,
        equivalence: Mapping[str, Any],
        mission_id: str,
        portfolio_decision_id: str,
    ) -> list[IndexRecord]:
        from axiom_rift.research.chassis import (
            ChassisComponentOutsideArchitectureError,
            ChassisIdentityError,
            architecture_component_semantic_surface_identity,
            component_semantic_surface_identity,
        )

        canonical_id = equivalence.get("canonical_component_id")
        equivalent_id = equivalence.get("equivalent_component_id")
        if not isinstance(canonical_id, str) or not isinstance(equivalent_id, str):
            raise TransitionError("component parity endpoints are malformed")
        edge_id = canonical_digest(
            domain="component-parity-edge",
            payload={
                "component_ids": sorted((canonical_id, equivalent_id)),
                "schema": "component_parity_edge.v1",
            },
        )
        records: list[IndexRecord] = []
        for endpoint, peer, prefix in (
            (canonical_id, equivalent_id, "canonical"),
            (equivalent_id, canonical_id, "equivalent"),
        ):
            manifest = equivalence.get(f"{prefix}_component_manifest")
            if not isinstance(manifest, Mapping):
                raise TransitionError("component parity endpoint manifest is malformed")
            try:
                surface = architecture_component_semantic_surface_identity(manifest)
            except ChassisComponentOutsideArchitectureError:
                surface = component_semantic_surface_identity(manifest)
            except ChassisIdentityError as exc:
                raise TransitionError(str(exc)) from exc
            record_id = canonical_digest(
                domain="component-parity-member",
                payload={
                    "completion_record_id": equivalence.get(
                        "completion_record_id"
                    ),
                    "edge_id": edge_id,
                    "endpoint_id": endpoint,
                    "schema": "component_parity_member.v1",
                },
            )
            records.append(
                _record(
                    kind="component-parity-member",
                    record_id=record_id,
                    subject=f"Component:{endpoint}",
                    status="equivalent",
                    fingerprint=surface,
                    payload={
                        "edge_id": edge_id,
                        "endpoint_id": endpoint,
                        "equivalence": dict(equivalence),
                        "mission_id": mission_id,
                        "peer_component_id": peer,
                        "portfolio_decision_id": portfolio_decision_id,
                        "schema": "component_parity_member_projection.v1",
                    },
                )
            )
        return records

    def _verified_component_parity_edges(
        self,
        index: LocalIndex,
        *,
        surface_seeds: tuple[str, ...] = (),
        component_seeds: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Re-verify every durable Writer-accepted parity edge from exact bytes."""

        if not surface_seeds and not component_seeds:
            return ()
        edges: dict[tuple[str, str], dict[str, Any]] = {}
        members_by_id: dict[str, IndexRecord] = {}
        pending_surfaces = list(dict.fromkeys(surface_seeds))
        pending_components = list(dict.fromkeys(component_seeds))
        seen_surfaces: set[str] = set()
        seen_components: set[str] = set()
        while pending_surfaces or pending_components:
            if pending_surfaces:
                surface = pending_surfaces.pop()
                if surface in seen_surfaces:
                    continue
                seen_surfaces.add(surface)
                candidates = index.records_by_fingerprint(surface)
            else:
                component_id = pending_components.pop()
                if component_id in seen_components:
                    continue
                seen_components.add(component_id)
                candidates = index.records_by_subject_status(
                    subject=f"Component:{component_id}",
                    status="equivalent",
                )
            for candidate in candidates:
                if candidate.kind != "component-parity-member":
                    continue
                members_by_id[candidate.record_id] = candidate
                equivalence = candidate.payload.get("equivalence")
                if not isinstance(equivalence, dict):
                    raise RecoveryRequired(
                        "accepted component parity member is malformed"
                    )
                for name in (
                    "canonical_component_id",
                    "equivalent_component_id",
                ):
                    value = equivalence.get(name)
                    if isinstance(value, str) and value not in seen_components:
                        pending_components.append(value)
        members = tuple(members_by_id.values())
        for member in members:
            equivalence = member.payload.get("equivalence")
            mission_id = member.payload.get("mission_id")
            portfolio_decision_id = member.payload.get("portfolio_decision_id")
            if (
                member.status != "equivalent"
                or member.payload.get("schema")
                != "component_parity_member_projection.v1"
                or not isinstance(equivalence, dict)
                or not isinstance(mission_id, str)
                or not isinstance(portfolio_decision_id, str)
            ):
                raise RecoveryRequired("accepted component parity member is malformed")
            self._require_component_parity_payload(
                index=index,
                equivalence=equivalence,
                mission_id=mission_id,
                portfolio_decision_id=portfolio_decision_id,
            )
            endpoints = (
                equivalence["canonical_component_id"],
                equivalence["equivalent_component_id"],
            )
            if any(not isinstance(value, str) for value in endpoints):
                raise RecoveryRequired("accepted component parity endpoints are malformed")
            key = tuple(sorted(endpoints))
            prior = edges.get(key)
            if prior is not None and (
                prior["canonical_component_manifest"]
                != equivalence["canonical_component_manifest"]
                or prior["equivalent_component_manifest"]
                != equivalence["equivalent_component_manifest"]
            ):
                prior_by_id = {
                    prior["canonical_component_id"]: prior[
                        "canonical_component_manifest"
                    ],
                    prior["equivalent_component_id"]: prior[
                        "equivalent_component_manifest"
                    ],
                }
                current_by_id = {
                    equivalence["canonical_component_id"]: equivalence[
                        "canonical_component_manifest"
                    ],
                    equivalence["equivalent_component_id"]: equivalence[
                        "equivalent_component_manifest"
                    ],
                }
                if prior_by_id != current_by_id:
                    raise RecoveryRequired(
                        "accepted component parity endpoints conflict"
                    )
            edges[key] = equivalence
        return tuple(edges[key] for key in sorted(edges))

    @staticmethod
    def _architecture_parity_surface_replacements(
        equivalences: tuple[Mapping[str, Any], ...],
    ) -> dict[str, str]:
        from axiom_rift.research.chassis import (
            ChassisComponentOutsideArchitectureError,
            ChassisIdentityError,
            architecture_component_semantic_surface_identity,
        )

        parents: dict[str, str] = {}
        manifests: dict[str, Mapping[str, Any]] = {}

        def find(component_id: str) -> str:
            parent = parents.setdefault(component_id, component_id)
            if parent != component_id:
                parents[component_id] = find(parent)
            return parents[component_id]

        def union(left_id: str, right_id: str) -> None:
            left_root = find(left_id)
            right_root = find(right_id)
            if left_root == right_root:
                return
            low, high = sorted((left_root, right_root))
            parents[high] = low

        for equivalence in equivalences:
            endpoint_values = []
            for prefix in ("canonical", "equivalent"):
                component_id = equivalence.get(f"{prefix}_component_id")
                manifest = equivalence.get(f"{prefix}_component_manifest")
                if not isinstance(component_id, str) or not isinstance(manifest, Mapping):
                    raise RecoveryRequired("accepted parity endpoint is malformed")
                expected_id = "component:" + canonical_digest(
                    domain="component", payload=dict(manifest)
                )
                if component_id != expected_id:
                    raise RecoveryRequired(
                        "accepted parity endpoint differs from its manifest"
                    )
                prior = manifests.get(component_id)
                if prior is not None and dict(prior) != dict(manifest):
                    raise RecoveryRequired("accepted parity manifest collision")
                manifests[component_id] = manifest
                endpoint_values.append(component_id)
            union(endpoint_values[0], endpoint_values[1])

        surface_owners: dict[str, str] = {}
        for component_id, manifest in manifests.items():
            try:
                surface = architecture_component_semantic_surface_identity(
                    manifest
                )
            except ChassisComponentOutsideArchitectureError:
                continue
            except ChassisIdentityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            owner = surface_owners.get(surface)
            if owner is None:
                surface_owners[surface] = component_id
            else:
                union(owner, component_id)

        classes: dict[str, list[str]] = {}
        for component_id in parents:
            classes.setdefault(find(component_id), []).append(component_id)
        replacements: dict[str, str] = {}
        for members in classes.values():
            normalized_members = sorted(members)
            class_surface = "architecture-equivalence-class:" + canonical_digest(
                domain="architecture-equivalence-class",
                payload={
                    "component_ids": normalized_members,
                    "schema": "architecture_equivalence_class.v1",
                },
            )
            for component_id in normalized_members:
                try:
                    surface = architecture_component_semantic_surface_identity(
                        manifests[component_id]
                    )
                except ChassisComponentOutsideArchitectureError:
                    continue
                except ChassisIdentityError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                prior = replacements.get(surface)
                if prior is not None and prior != class_surface:
                    raise RecoveryRequired(
                        "accepted parity architecture classes conflict"
                    )
                replacements[surface] = class_surface
        return replacements

    @staticmethod
    def _prospective_architecture_family_from_executable(
        executable_or_payload: Any,
    ) -> str:
        """Derive the v4 scheduler family without changing legacy identity."""

        from axiom_rift.core.identity import ExecutableSpec
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            prospective_architecture_family_identity,
        )
        from axiom_rift.research.portfolio_projection import (
            PortfolioProjectionError,
            executable_from_identity_payload,
        )

        try:
            executable = (
                executable_or_payload
                if isinstance(executable_or_payload, ExecutableSpec)
                else executable_from_identity_payload(executable_or_payload)
                if isinstance(executable_or_payload, Mapping)
                else None
            )
        except PortfolioProjectionError as exc:
            raise RecoveryRequired(
                "durable architecture baseline cannot be reconstructed"
            ) from exc
        if executable is None:
            raise RecoveryRequired("architecture baseline Executable is absent")
        try:
            return prospective_architecture_family_identity(executable)
        except ChassisIdentityError as exc:
            raise RecoveryRequired(
                "architecture baseline lacks a prospective semantic family"
            ) from exc

    def _axis_prospective_architecture_family(
        self,
        *,
        index: LocalIndex | LocalIndexView,
        axis: Mapping[str, Any],
        baseline_override: Any | None = None,
    ) -> str | None:
        """Resolve one axis from exact accepted baselines, never display labels."""

        if baseline_override is not None:
            return self._prospective_architecture_family_from_executable(
                baseline_override
            )
        axis_identity = axis.get("axis_identity")
        if not isinstance(axis_identity, str):
            raise RecoveryRequired("Portfolio axis identity is malformed")
        families: set[str] = set()
        for record in index.records_by_payload_text(
            "portfolio-decision",
            "target_axis_identity",
            axis_identity,
        ):
            if self._active_portfolio_decision(index, record.record_id) is None:
                continue
            baseline = record.payload.get("baseline_executable")
            if (
                isinstance(baseline, Mapping)
                and baseline.get("schema") == "executable_spec.v1"
            ):
                families.add(
                    self._prospective_architecture_family_from_executable(
                        baseline
                    )
                )
        if len(families) > 1:
            raise RecoveryRequired(
                "Portfolio axis has conflicting prospective semantic families"
            )
        return None if not families else next(iter(families))

    def _resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        architecture_payload: Mapping[str, Any],
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            architecture_family_identity,
        )

        roles = architecture_payload.get("roles")
        if not isinstance(roles, Mapping):
            raise TransitionError("architecture chassis roles are malformed")
        surface_seeds = tuple(
            sorted(
                {
                    surface
                    for role in roles.values()
                    if isinstance(role, Mapping)
                    for surface in role.get("component_semantic_surfaces", [])
                    if isinstance(surface, str)
                }
            )
        )
        cache = getattr(index, "_axiom_verified_parity_cache", None)
        if cache is None:
            cache = {}
            try:
                setattr(index, "_axiom_verified_parity_cache", cache)
            except AttributeError:
                # Authenticated read-only views are slot-backed.  They remain
                # valid callers; only the optional per-transaction cache is
                # unavailable on that boundary.
                pass
        verified = cache.get(surface_seeds)
        if verified is None:
            verified = self._verified_component_parity_edges(
                index,
                surface_seeds=surface_seeds,
            )
            cache[surface_seeds] = verified
        equivalences = (
            *verified,
            *extra_equivalences,
        )
        replacements = self._architecture_parity_surface_replacements(
            tuple(equivalences)
        )
        try:
            return architecture_family_identity(
                architecture_payload,
                surface_replacements=replacements,
            )
        except ChassisIdentityError as exc:
            raise TransitionError(str(exc)) from exc

    def _study_resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        study: IndexRecord,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        controlled = study.payload.get("controlled_chassis")
        baseline = (
            None
            if not isinstance(controlled, dict)
            else controlled.get("baseline_executable")
        )
        if isinstance(baseline, Mapping):
            return self._prospective_architecture_family_from_executable(
                baseline
            )
        architecture = (
            None if not isinstance(controlled, dict) else controlled.get("architecture")
        )
        if isinstance(architecture, dict):
            return self._resolved_architecture_family(
                index=index,
                architecture_payload=architecture,
                extra_equivalences=extra_equivalences,
            )
        legacy = study.payload.get("system_architecture_family")
        if not isinstance(legacy, str):
            raise TransitionError("Study lacks a system architecture family")
        return legacy

    def _review_resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        review: IndexRecord,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        families: set[str] = set()
        for diagnosis_id in review.payload.get("covered_diagnosis_ids", []):
            if not isinstance(diagnosis_id, str):
                raise RecoveryRequired("architecture review diagnosis binding is malformed")
            diagnosis = index.get("study-diagnosis", diagnosis_id)
            study_id = None if diagnosis is None else diagnosis.payload.get("study_id")
            study = (
                None
                if not isinstance(study_id, str)
                else index.get("study-open", study_id)
            )
            if study is None:
                raise RecoveryRequired(
                    "architecture review lost a covered Study diagnosis"
                )
            families.add(
                self._study_resolved_architecture_family(
                    index=index,
                    study=study,
                    extra_equivalences=extra_equivalences,
                )
            )
        if len(families) > 1:
            raise RecoveryRequired(
                "architecture review covered Studies no longer share one family"
            )
        if families:
            return next(iter(families))
        stored = review.payload.get("system_architecture_family")
        if not isinstance(stored, str):
            raise RecoveryRequired("architecture review family is unavailable")
        return stored

    def _axis_resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        axis: Mapping[str, Any],
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        """Resolve one current or newly proposed axis without history-wide lookup."""

        prospective = self._axis_prospective_architecture_family(
            index=index,
            axis=axis,
        )
        if prospective is not None:
            return prospective
        architecture = axis.get("architecture_chassis")
        if isinstance(architecture, Mapping):
            return self._resolved_architecture_family(
                index=index,
                architecture_payload=architecture,
                extra_equivalences=extra_equivalences,
            )
        anchor = self._axis_architecture_anchor(index, axis)
        if anchor is not None:
            anchored_architecture = anchor.get("architecture_chassis")
            if isinstance(anchored_architecture, Mapping):
                return self._resolved_architecture_family(
                    index=index,
                    architecture_payload=anchored_architecture,
                    extra_equivalences=extra_equivalences,
                )
            anchored_identity = anchor.get("architecture_chassis_identity")
            if isinstance(anchored_identity, str):
                return anchored_identity
        legacy = axis.get("system_architecture_family")
        if not isinstance(legacy, str):
            raise TransitionError("Portfolio axis architecture family is unavailable")
        return legacy

    def _pending_architecture_review_trigger(
        self,
        *,
        index: LocalIndex,
        mission_id: str,
        portfolio_snapshot_id: str,
        architecture_family: str,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
        effective_state_overrides: Mapping[str, str] | None = None,
        effective_authority_overrides: Mapping[
            str, tuple[str, str]
        ] | None = None,
        pending_diagnoses: tuple[IndexRecord, ...] = (),
        effective_diagnoses: Sequence[Any] | None = None,
        reviewed_diagnosis_ids: frozenset[str] | None = None,
    ) -> IndexRecord | None:
        snapshot = index.get("portfolio-snapshot", portfolio_snapshot_id)
        standard = (
            None if snapshot is None else snapshot.payload.get("exhaustion_standard")
        )
        if not isinstance(standard, dict):
            return None
        minimum_studies = standard.get("architecture_review_minimum_studies")
        minimum_axes = standard.get("architecture_review_minimum_axes")
        if type(minimum_studies) is not int or type(minimum_axes) is not int:
            raise RecoveryRequired("architecture review threshold is malformed")
        reviewed_ids: set[str] = (
            set(reviewed_diagnosis_ids)
            if reviewed_diagnosis_ids is not None
            else set()
        )
        if reviewed_diagnosis_ids is None:
            for review in index.records_by_payload_text(
                "architecture-review",
                "mission_id",
                mission_id,
            ):
                reviewed_ids.update(
                    value
                    for value in review.payload.get("covered_diagnosis_ids", [])
                    if isinstance(value, str)
                )
        from axiom_rift.operations.effective_study_diagnosis import (
            EffectiveStudyDiagnosisError,
            effective_study_diagnoses_for_mission,
        )

        if effective_diagnoses is None:
            try:
                effective_diagnoses = effective_study_diagnoses_for_mission(
                    index,
                    mission_id=mission_id,
                )
            except EffectiveStudyDiagnosisError as exc:
                raise RecoveryRequired(str(exc)) from exc
        overrides = {} if effective_state_overrides is None else dict(
            effective_state_overrides
        )
        authority_overrides = (
            {}
            if effective_authority_overrides is None
            else dict(effective_authority_overrides)
        )
        if any(
            diagnosis.kind != "study-diagnosis"
            or diagnosis.payload.get("mission_id") != mission_id
            for diagnosis in pending_diagnoses
        ):
            raise RecoveryRequired(
                "pending architecture diagnosis authority is malformed"
            )
        combined: tuple[Any, ...] = (
            *effective_diagnoses,
            *pending_diagnoses,
        )
        if len({diagnosis.record_id for diagnosis in combined}) != len(combined):
            raise RecoveryRequired(
                "architecture review diagnosis authority is duplicated"
            )
        diagnoses: list[Any] = []
        for diagnosis in combined:
            effective_state = overrides.get(
                diagnosis.record_id,
                diagnosis.payload.get("evidence_state"),
            )
            if (
                diagnosis.record_id in reviewed_ids
                or effective_state
                in {"engineering_gap", "supported_requires_confirmation"}
            ):
                continue
            study_id = diagnosis.payload.get("study_id")
            study = (
                None
                if not isinstance(study_id, str)
                else index.get("study-open", study_id)
            )
            if study is None:
                raise RecoveryRequired(
                    "architecture review diagnosis lost its Study"
                )
            if (
                self._study_resolved_architecture_family(
                    index=index,
                    study=study,
                    extra_equivalences=extra_equivalences,
                )
                == architecture_family
            ):
                diagnoses.append(diagnosis)
        axis_ids = {
            diagnosis.payload.get("portfolio_axis_id") for diagnosis in diagnoses
        }
        if (
            len(diagnoses) < minimum_studies
            or len(axis_ids) < minimum_axes
            or None in axis_ids
        ):
            return None
        trigger_payload = {
            "diagnosis_ids": sorted(
                diagnosis.record_id for diagnosis in diagnoses
            ),
            "mission_id": mission_id,
            "portfolio_axis_ids": sorted(axis_ids),
            "portfolio_snapshot_id": portfolio_snapshot_id,
            "primary_research_layers": sorted(
                {
                    diagnosis.payload["primary_research_layer"]
                    for diagnosis in diagnoses
                }
            ),
            "schema": "architecture_review_trigger.v1",
            "system_architecture_family": architecture_family,
            "threshold": {
                "minimum_distinct_axes": minimum_axes,
                "minimum_studies": minimum_studies,
            },
        }
        authorities: list[dict[str, str]] = []
        for diagnosis in sorted(diagnoses, key=lambda value: value.record_id):
            authority = authority_overrides.get(diagnosis.record_id)
            if authority is None:
                correction = getattr(diagnosis, "correction", None)
                authority = (
                    ("study-diagnosis", diagnosis.record_id)
                    if correction is None
                    else ("study-diagnosis-correction", correction.record_id)
                )
            authorities.append(
                {
                    "effective_authority_kind": authority[0],
                    "effective_authority_record_id": authority[1],
                    "original_diagnosis_id": diagnosis.record_id,
                }
            )
        if any(
            authority["effective_authority_kind"]
            == "study-diagnosis-correction"
            for authority in authorities
        ):
            trigger_payload["diagnosis_authorities"] = authorities
            trigger_payload["schema"] = "architecture_review_trigger.v2"
        trigger_id = canonical_digest(
            domain="architecture-review-trigger",
            payload=trigger_payload,
        )
        return _record(
            kind="architecture-review-trigger",
            record_id=trigger_id,
            subject=f"Mission:{mission_id}",
            status="required",
            fingerprint=trigger_id,
            payload=trigger_payload,
        )

    @staticmethod
    def study_input_hash(
        *,
        question: Mapping[str, Any],
        material_identity: str,
        semantic_proposal: Mapping[str, Any],
        semantic_question_equivalence: Any | None = None,
        semantic_question_lineage: Any | None = None,
        controlled_chassis: Any | None = None,
        portfolio_axis_id: str | None = None,
        portfolio_axis_identity: str | None = None,
        portfolio_decision_id: str | None = None,
    ) -> str:
        question_manifest = _require_manifest(
            "question",
            question,
            required={
                "causal_question",
                "changed_variables",
                "controlled_variables",
                "done_conditions",
                "evidence_modes",
            },
        )
        question_manifest["evidence_modes"] = list(
            _require_study_evidence_modes(question_manifest)
        )
        question_hash = _digest(question_manifest, domain="study-question")
        _require_ascii("material_identity", material_identity)
        from axiom_rift.research.chassis import ControlledStudyChassis

        if controlled_chassis is not None and not isinstance(
            controlled_chassis, ControlledStudyChassis
        ):
            raise TransitionError("controlled_chassis must be a ControlledStudyChassis")
        from axiom_rift.research.semantic_question import (
            SemanticQuestionEquivalenceProposal,
            SemanticQuestionLineageProposal,
        )

        if semantic_question_equivalence is not None and not isinstance(
            semantic_question_equivalence,
            SemanticQuestionEquivalenceProposal,
        ):
            raise TransitionError(
                "semantic_question_equivalence must be a typed proposal"
            )
        if semantic_question_lineage is not None and not isinstance(
            semantic_question_lineage,
            SemanticQuestionLineageProposal,
        ):
            raise TransitionError(
                "semantic_question_lineage must be a typed proposal"
            )
        if (
            semantic_question_equivalence is not None
            and semantic_question_lineage is None
        ):
            raise TransitionError(
                "semantic question equivalence requires exact Study lineage"
            )
        expected_equivalence_id = (
            None
            if semantic_question_equivalence is None
            else semantic_question_equivalence.identity
        )
        if (
            semantic_question_lineage is not None
            and semantic_question_lineage.equivalence_proposal_id
            != expected_equivalence_id
        ):
            raise TransitionError(
                "semantic question lineage and equivalence proposals diverge"
            )
        input_payload: dict[str, Any] = {
                "controlled_chassis": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.to_identity_payload()
                ),
                "question_hash": question_hash,
                "material_identity": material_identity,
                "portfolio_axis_id": portfolio_axis_id,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "semantic_proposal": dict(semantic_proposal),
        }
        if semantic_question_equivalence is not None:
            input_payload["semantic_question_equivalence"] = (
                semantic_question_equivalence.to_identity_payload()
            )
        if semantic_question_lineage is not None:
            input_payload["semantic_question_lineage"] = (
                semantic_question_lineage.to_identity_payload()
            )
        return _digest(
            input_payload,
            domain="study-input",
        )

    @staticmethod
    def _current_accepted_replay_replacement_preflight(
        index: LocalIndex,
        *,
        mission_id: str,
        obligation_ids: tuple[str, ...],
    ) -> IndexRecord | None:
        """Resolve one exact replacement trigger at a pending Study boundary."""

        if not obligation_ids:
            return None
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            obligation_heads,
            require_current_replacement_preflight_basis,
        )

        heads = {
            obligation.identity: head
            for obligation, head in obligation_heads(
                index,
                mission_id=mission_id,
            )
        }
        triggers: list[IndexRecord] = []
        for obligation_id in obligation_ids:
            head = heads.get(obligation_id)
            if head is None:
                raise TransitionError(
                    "replay implementation admission lacks its obligation"
                )
            resume = head
            if (
                head.kind != "historical-replay-obligation-resume"
                and head.status == "in_progress"
                and isinstance(head.event_stream, str)
                and type(head.event_sequence) is int
                and head.event_sequence >= 2
            ):
                resume = index.event_record(
                    head.event_stream,
                    head.event_sequence - 1,
                )
            evidence = (
                resume.payload.get("resume_evidence")
                if resume.kind == "historical-replay-obligation-resume"
                else None
            )
            trigger_id = (
                evidence.get("trigger_record_id")
                if isinstance(evidence, Mapping)
                else None
            )
            if not isinstance(trigger_id, str) or not trigger_id.startswith(
                "job-implementation-preflight:"
            ):
                continue
            trigger = index.get("job-implementation-preflight", trigger_id)
            stream_head = (
                None
                if trigger is None
                or not isinstance(trigger.event_stream, str)
                else index.event_head(trigger.event_stream)
            )
            replacement_for = (
                None
                if trigger is None
                else trigger.payload.get("replacement_for_preflight_id")
            )
            trigger_fingerprint = (
                None
                if trigger is None
                else _digest(
                    trigger.payload,
                    domain="replay-job-implementation-preflight",
                )
            )
            if (
                trigger is None
                or trigger.fingerprint != trigger_fingerprint
                or trigger.record_id
                != "job-implementation-preflight:" + trigger_fingerprint
                or trigger.status != "accepted"
                or trigger.payload.get("schema")
                != "replay_job_implementation_preflight.v1"
                or trigger.payload.get("outcome") != "accepted"
                or trigger.payload.get("mission_id") != mission_id
                or trigger.payload.get("replay_obligation_ids")
                != list(obligation_ids)
                or trigger.payload.get("batch_id") is not None
                or trigger.payload.get("study_id") is not None
                or not isinstance(replacement_for, str)
                or trigger.event_stream
                != (
                    "replay-job-implementation-preflight-replacement:"
                    + replacement_for
                )
                or stream_head is None
                or stream_head.record_id != trigger.record_id
                or not isinstance(
                    trigger.payload.get("source_closure_authority"),
                    Mapping,
                )
                or trigger.payload.get("failure_fingerprint") is not None
                or trigger.payload.get("reason_code") is not None
                or trigger.payload.get("remediation_kind") is not None
            ):
                raise RecoveryRequired(
                    "replay replacement implementation trigger is malformed"
                )
            triggers.append(trigger)
        if not triggers:
            return None
        if (
            len(triggers) != len(obligation_ids)
            or len({trigger.record_id for trigger in triggers}) != 1
        ):
            raise TransitionError(
                "replay obligations mix replacement implementation authority"
            )
        return triggers[0]

    @staticmethod
    def _study_replay_implementation_admission(
        index: LocalIndex,
        *,
        study_id: str,
        authority_manifest_digest: str,
        _include_repair_successors: bool = True,
    ) -> IndexRecord | None:
        study = index.get("study-open", study_id)
        initial_admission_id = (
            None
            if study is None
            else study.payload.get("replay_implementation_admission_id")
        )
        recertification_stream = (
            f"replay-implementation-admission-study:{study_id}"
        )
        recertification_head = index.event_head(recertification_stream)
        if initial_admission_id is not None and recertification_head is not None:
            raise RecoveryRequired(
                "Study mixes initial and recertified replay admissions"
            )
        base_admission_id = (
            recertification_head.record_id
            if initial_admission_id is None
            and recertification_head is not None
            else initial_admission_id
        )
        if base_admission_id is None:
            return None
        base_admission = (
            index.get("replay-implementation-admission", base_admission_id)
            if isinstance(base_admission_id, str)
            else None
        )
        if base_admission is None:
            raise RecoveryRequired(
                "Study replay implementation admission is unavailable"
            )
        from axiom_rift.operations.replay_implementation_repair_admission import (
            ReplayImplementationRepairAdmissionIntegrityError,
            current_replay_implementation_repair_admission,
            repair_admission_stream,
        )

        repair_recertification_stream = repair_admission_stream(study_id)
        repair_recertification_head = index.event_head(
            repair_recertification_stream
        )
        admission = base_admission
        if (
            _include_repair_successors
            and repair_recertification_head is not None
        ):
            validated_base = StudyAdmissionWriterMixin._study_replay_implementation_admission(
                index,
                study_id=study_id,
                authority_manifest_digest=authority_manifest_digest,
                _include_repair_successors=False,
            )
            if validated_base is None:
                raise RecoveryRequired(
                    "post-Repair admission lacks an authenticated predecessor"
                )
            try:
                admission = current_replay_implementation_repair_admission(
                    index,
                    study_id=study_id,
                    base_admission=validated_base,
                )
            except ReplayImplementationRepairAdmissionIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
        from axiom_rift.operations.research_protocol_projection import (
            ResearchProtocolProjectionError,
            require_current_research_protocol_activation,
        )

        try:
            protocol_activation = require_current_research_protocol_activation(
                index,
                authority_manifest_digest=authority_manifest_digest,
            )
        except ResearchProtocolProjectionError as exc:
            raise RecoveryRequired(str(exc)) from exc
        payload = admission.payload
        recertification_preflight_id = payload.get(
            "recertification_preflight_id"
        )
        recertification_preflight = (
            None
            if not isinstance(recertification_preflight_id, str)
            else index.get(
                "job-implementation-preflight",
                recertification_preflight_id,
            )
        )
        accepted_id = payload.get("accepted_replacement_preflight_id")
        accepted = (
            index.get("job-implementation-preflight", accepted_id)
            if isinstance(accepted_id, str)
            else None
        )
        accepted_head = (
            None
            if accepted is None
            or not isinstance(accepted.event_stream, str)
            else index.event_head(accepted.event_stream)
        )
        fingerprint = _digest(
            payload,
            domain="replay-implementation-admission",
        )
        request = payload.get("request")
        surface = payload.get("scientific_surface")
        source_authority = payload.get("source_closure_authority")
        from axiom_rift.operations.replay_job_implementation_preflight import (
            PREFLIGHT_SCHEMA,
            ReplayJobImplementationPreflightError,
            replay_job_scientific_surface_hash,
            require_active_replay_job_replacement_binding,
        )
        from axiom_rift.research.implementation_closure import (
            JOB_IMPLEMENTATION_SOURCE_AUTHORITY_SCHEMA,
        )

        request_keys = {
            "callable_identity",
            "executable_manifests",
            "implementation_identity",
            "mission_id",
            "protocol_id",
            "replacement_for_preflight_id",
            "replay_obligation_ids",
            "schema",
            "scientific_bindings",
        }
        source_keys = {
            "callable_module_path",
            "dependency_count",
            "path_inventory_hash",
            "schema",
            "source_closure_hash",
        }
        manifests = (
            request.get("executable_manifests")
            if isinstance(request, Mapping)
            else None
        )
        bindings = (
            request.get("scientific_bindings")
            if isinstance(request, Mapping)
            else None
        )
        try:
            surface_hash = (
                replay_job_scientific_surface_hash(surface)
                if isinstance(surface, Mapping)
                else None
            )
            executable_ids = (
                []
                if not isinstance(manifests, list)
                else [
                    "executable:"
                    + canonical_digest(
                        domain="executable",
                        payload=manifest,
                    )
                    for manifest in manifests
                ]
            )
            if (
                accepted is not None
                and payload.get("schema")
                != "replay_implementation_admission.v3"
            ):
                require_active_replay_job_replacement_binding(
                    accepted_payload=accepted.payload,
                    active_payload={
                        "callable_identity": request.get(
                            "callable_identity"
                        ),
                        "executable_ids": executable_ids,
                        "executable_manifests": manifests,
                        "implementation_identity": request.get(
                            "implementation_identity"
                        ),
                        "mission_id": request.get("mission_id"),
                        "protocol_id": request.get("protocol_id"),
                        "replacement_for_preflight_id": None,
                        "replay_obligation_ids": request.get(
                            "replay_obligation_ids"
                        ),
                        "schema": PREFLIGHT_SCHEMA,
                        "scientific_surface": surface,
                        "scientific_surface_hash": surface_hash,
                    },
                )
        except (
            AttributeError,
            ReplayJobImplementationPreflightError,
            TypeError,
            ValueError,
        ):
            surface_hash = None
            executable_ids = []
        accepted_invalid = accepted_id is not None and (
            not isinstance(accepted_id, str)
            or accepted is None
            or accepted.status != "accepted"
            or accepted.payload.get("outcome") != "accepted"
            or accepted.payload.get("remediation_kind") is not None
            or accepted_head is None
            or accepted_head.record_id != accepted.record_id
        )
        from axiom_rift.operations.replay_implementation_repair_admission import (
            REPAIR_RECERTIFICATION_ADMISSION_SCHEMA,
        )

        admission_schema = payload.get("schema")
        legacy_recertified = (
            admission_schema == "replay_implementation_admission.v2"
        )
        repair_recertified = (
            admission_schema == REPAIR_RECERTIFICATION_ADMISSION_SCHEMA
        )
        recertified = legacy_recertified or repair_recertified
        admission_boundary_invalid = bool(
            study is None
            or type(study.authority_sequence) is not int
            or type(protocol_activation.authority_sequence) is not int
            or type(admission.authority_sequence) is not int
            or (
                legacy_recertified
                and not (
                    study.authority_sequence
                    < protocol_activation.authority_sequence
                    < admission.authority_sequence
                )
            )
            or (
                not recertified
                and (
                    protocol_activation.authority_sequence
                    >= study.authority_sequence
                    or admission.authority_sequence
                    != study.authority_sequence
                    or admission.authority_event_id
                    != study.authority_event_id
                )
            )
            or (
                repair_recertified
                and not (
                    protocol_activation.authority_sequence
                    < admission.authority_sequence
                    and study.authority_sequence
                    < admission.authority_sequence
                )
            )
        )
        expected_payload_keys = {
            "accepted_replacement_preflight_id",
            "authority_manifest_digest",
            "batch_id",
            "request",
            "research_protocol_activation_id",
            "schema",
            "scientific_surface",
            "scientific_surface_hash",
            "source_closure_authority",
            "study_id",
        }
        if recertified:
            expected_payload_keys.update(
                {
                    "recertification_preflight_id",
                    "registered_prefix_executable_ids",
                }
            )
        if repair_recertified:
            expected_payload_keys.update(
                {
                    "predecessor_admission_id",
                    "repair_close_record_ids",
                    "repair_executable_id",
                    "repair_job_id",
                    "trigger_repair_close_record_id",
                }
            )
        recertification_invalid = False
        if recertified:
            batch_id = payload.get("batch_id")
            batch = (
                None
                if not isinstance(batch_id, str)
                else index.get("batch-open", batch_id)
            )
            preflight_head = (
                None
                if recertification_preflight is None
                or not isinstance(
                    recertification_preflight.event_stream,
                    str,
                )
                else index.event_head(
                    recertification_preflight.event_stream
                )
            )
            prefix = payload.get("registered_prefix_executable_ids")
            try:
                from axiom_rift.operations.replay_study_admission import (
                    ReplayStudyAdmissionError,
                    inspect_replay_study_registration,
                )

                registration = (
                    inspect_replay_study_registration(
                        index,
                        study_record=study,
                        batch_record=batch,
                    ).require_usable()
                    if study is not None and batch is not None
                    else None
                )
            except ReplayStudyAdmissionError:
                registration = None
            registered_trials = (
                ()
                if registration is None or batch is None
                else tuple(
                    index.event_record(
                        f"batch-trials:{batch.record_id}",
                        ordinal,
                    )
                    for ordinal in range(
                        1,
                        registration.registered_count + 1,
                    )
                )
            )
            prefix_count = len(prefix) if isinstance(prefix, list) else -1
            active_recertification_head = (
                repair_recertification_head
                if repair_recertified
                else recertification_head
            )
            active_recertification_stream = (
                repair_recertification_stream
                if repair_recertified
                else recertification_stream
            )
            active_recertification_sequence = (
                None
                if active_recertification_head is None
                else active_recertification_head.sequence
            )
            recertification_invalid = (
                active_recertification_head is None
                or (
                    legacy_recertified
                    and active_recertification_head.sequence != 1
                )
                or active_recertification_head.record_id != admission.record_id
                or admission.event_stream != active_recertification_stream
                or admission.event_sequence != active_recertification_sequence
                or recertification_preflight is None
                or recertification_preflight.status != "accepted"
                or recertification_preflight.payload.get("outcome")
                != "accepted"
                or recertification_preflight.payload.get("batch_id")
                != batch_id
                or recertification_preflight.payload.get("study_id")
                != study_id
                or recertification_preflight.payload.get("executable_ids")
                != executable_ids
                or recertification_preflight.payload.get(
                    "scientific_surface_hash"
                )
                != payload.get("scientific_surface_hash")
                or recertification_preflight.payload.get(
                    "source_closure_authority"
                )
                != source_authority
                or recertification_preflight.payload.get("request_identity")
                != (
                    None
                    if not isinstance(request, Mapping)
                    else (
                        "replay-job-implementation-preflight-request:"
                        + canonical_digest(
                            domain=(
                                "replay-job-implementation-preflight-request"
                            ),
                            payload=request,
                        )
                    )
                )
                or preflight_head is None
                or preflight_head.record_id
                != recertification_preflight.record_id
                or type(admission.authority_sequence) is not int
                or admission.authority_sequence
                != recertification_preflight.authority_sequence
                or admission.authority_event_id
                != recertification_preflight.authority_event_id
                or not isinstance(prefix, list)
                or any(type(item) is not str for item in prefix)
                or registration is None
                or prefix_count < 0
                or prefix_count > registration.registered_count
                or tuple(prefix)
                != registration.expected_executable_ids[: len(prefix)]
                or registration.registered_executable_ids[: len(prefix)]
                != tuple(prefix)
                or (
                    repair_recertified
                    and (
                        tuple(prefix) != registration.expected_executable_ids
                        or recertification_preflight.payload.get(
                            "repair_close_record_id"
                        )
                        != payload.get("trigger_repair_close_record_id")
                    )
                )
                or any(trial is None for trial in registered_trials)
                or any(
                    trial.authority_sequence >= admission.authority_sequence
                    for trial in registered_trials[:prefix_count]
                    if trial is not None
                )
                or any(
                    trial.authority_sequence <= admission.authority_sequence
                    for trial in registered_trials[prefix_count:]
                    if trial is not None
                )
            )
        if (
            study is None
            or study.status != "open"
            or study.subject != f"Study:{study_id}"
            or admission.status != "active"
            or admission.subject != f"Study:{study_id}"
            or set(payload) != expected_payload_keys
            or admission_schema
            not in {
                "replay_implementation_admission.v1",
                "replay_implementation_admission.v2",
                REPAIR_RECERTIFICATION_ADMISSION_SCHEMA,
            }
            or payload.get("study_id") != study_id
            or payload.get("authority_manifest_digest")
            != authority_manifest_digest
            or payload.get("research_protocol_activation_id")
            != protocol_activation.record_id
            or not isinstance(request, Mapping)
            or set(request) != request_keys
            or request.get("schema")
            != "replay_job_implementation_preflight_request.v1"
            or request.get("replacement_for_preflight_id") is not None
            or study.payload.get("mission_id") != request.get("mission_id")
            or study.payload.get("replay_obligation_ids")
            != request.get("replay_obligation_ids")
            or type(payload.get("batch_id")) is not str
            or not payload["batch_id"].startswith("batch:")
            or len(payload["batch_id"].removeprefix("batch:")) != 64
            or any(
                character not in "0123456789abcdef"
                for character in payload["batch_id"].removeprefix("batch:")
            )
            or not isinstance(manifests, list)
            or not manifests
            or not isinstance(bindings, list)
            or len(bindings) != len(manifests)
            or len(executable_ids) != len(manifests)
            or not isinstance(surface, Mapping)
            or surface_hash != payload.get("scientific_surface_hash")
            or surface.get("callable_identity")
            != request.get("callable_identity")
            or surface.get("mission_id") != request.get("mission_id")
            or surface.get("protocol_id") != request.get("protocol_id")
            or surface.get("replay_obligation_ids")
            != request.get("replay_obligation_ids")
            or not isinstance(source_authority, Mapping)
            or set(source_authority) != source_keys
            or source_authority.get("schema")
            != JOB_IMPLEMENTATION_SOURCE_AUTHORITY_SCHEMA
            or accepted_invalid
            or admission_boundary_invalid
            or recertification_invalid
            or admission.fingerprint != fingerprint
            or admission.record_id
            != f"replay-implementation-admission:{fingerprint}"
        ):
            raise RecoveryRequired(
                "Study replay implementation admission is malformed"
            )
        return admission

    def _require_replay_registration_source_authority(
        self,
        index: LocalIndex,
        *,
        admission: IndexRecord,
        executable: Any,
    ) -> None:
        """Recheck current bytes before a replay trial can enter multiplicity."""

        request = admission.payload.get("request")
        manifests = (
            None
            if not isinstance(request, Mapping)
            else request.get("executable_manifests")
        )
        bindings = (
            None
            if not isinstance(request, Mapping)
            else request.get("scientific_bindings")
        )
        executable_manifest = executable.to_identity_payload()
        try:
            member_index = (
                manifests.index(executable_manifest)
                if isinstance(manifests, list)
                else -1
            )
        except ValueError:
            member_index = -1
        if (
            member_index < 0
            or not isinstance(bindings, list)
            or member_index >= len(bindings)
            or not isinstance(bindings[member_index], Mapping)
        ):
            raise TransitionError(
                "Executable differs from the replay implementation admission"
            )
        spec = {
            "callable_identity": request["callable_identity"],
            "evidence_subject": {
                "kind": "Executable",
                "id": executable.identity,
            },
            "implementation_identity": request["implementation_identity"],
            "scientific_binding": bindings[member_index],
        }
        implementation = self._require_job_implementation_evidence(
            spec,
            _index=index,
        )
        try:
            from axiom_rift.research.implementation_closure import (
                ImplementationClosureError,
                require_current_job_source_closure,
                require_job_implementation_closure,
            )

            component_hashes = require_job_implementation_closure(
                executable_manifest=executable_manifest,
                job_artifact_hashes=implementation["artifact_hashes"],
                artifact_reader=self.evidence.read_verified,
            )
            source_authority = require_current_job_source_closure(
                callable_identity=request["callable_identity"],
                job_artifact_hashes=implementation["artifact_hashes"],
                artifact_reader=self.evidence.read_verified,
                source_root=(self.foundation_root / "src").absolute(),
                verified_non_source_artifact_hashes=component_hashes,
            )
        except ImplementationClosureError as exc:
            raise TransitionError(
                "replay implementation source drifted before trial "
                f"registration: {exc}"
            ) from exc
        if source_authority != admission.payload.get(
            "source_closure_authority"
        ):
            raise TransitionError(
                "replay implementation source authority changed after Study admission"
            )

    def _replay_scientific_protocol_failure(
        self,
        current: Mapping[str, Any],
        index: LocalIndex,
        *,
        request: Any,
    ) -> str | None:
        """Return a durable partial-Study incompatibility, not a validator guess."""

        protocol_head = index.event_head("research-protocol:scientific")
        if protocol_head is None:
            return "active scientific protocol is absent"
        protocol = index.get(
            protocol_head.record_kind,
            protocol_head.record_id,
        )
        if (
            protocol is None
            or protocol.kind != "research-protocol-activation"
            or protocol.status != "active"
            or protocol.event_sequence != protocol_head.sequence
            or protocol.event_stream != "research-protocol:scientific"
        ):
            raise RecoveryRequired(
                "active scientific protocol projection is invalid"
            )
        if (
            protocol.payload.get("protocol")
            != "scientific_adjudication_v2"
            or protocol.payload.get("authority_manifest_digest")
            != current.get("authority", {}).get("manifest_digest")
        ):
            return "active scientific protocol is not current"
        validator_ids = {
            binding.get("validator_id")
            for binding in request.scientific_binding_values()
            if isinstance(binding, Mapping)
        }
        if validator_ids != {protocol.payload.get("validator_id")}:
            return "replay family validator differs from the active protocol"
        return None


    def _prepare_study_portfolio_plan(
        self,
        *,
        current: Mapping[str, Any],
        index: LocalIndex,
        science: Mapping[str, Any],
        study_id: str,
        question_manifest: Mapping[str, Any],
        material_identity: str,
        semantic_proposal_manifest: Mapping[str, Any],
        semantic_question_core: Any,
        semantic_question_lineage: Any | None,
        controlled_chassis: Any | None,
        portfolio_axis_id: str | None,
        portfolio_axis_identity: str | None,
        portfolio_decision_id: str | None,
        replay_implementation_request: Any | None,
        replay_batch_spec: Any | None,
        permit: Permit,
    ) -> _StudyPortfolioPlan:
        """Validate Decision, axis, chassis, and reentry authority in order."""

        from axiom_rift.operations.prospective_architecture_projection import (
            ProspectiveArchitectureProjectionError,
            family_for_axis,
        )

        _index = index

        portfolio_snapshot_id: str | None = None
        mechanism_family: str | None = None
        primary_research_layer: str | None = None
        system_architecture_family: str | None = None
        changed_domains: list[str] | None = None
        controlled_domains: list[str] | None = None
        portfolio_action: str | None = None
        commitment_batches: int | None = None
        post_holdout_development_id: str | None = None
        replay_obligation_ids: tuple[str, ...] = ()
        replacement_preflight: IndexRecord | None = None
        if not self.engineering_fixture:
            if (
                portfolio_axis_id is None
                or portfolio_axis_identity is None
                or portfolio_decision_id is None
            ):
                raise TransitionError(
                    "scientific Study requires exact Portfolio axis and Decision identities"
                )
            _require_ascii("portfolio_axis_id", portfolio_axis_id)
            next_action = current["next_action"]
            portfolio_snapshot_id = next_action.get("portfolio_snapshot_id")
            if (
                next_action.get("kind") != "execute_portfolio_decision"
                or next_action.get("target_id") != portfolio_axis_id
                or next_action.get("target_axis_identity")
                != portfolio_axis_identity
                or next_action.get("decision_id") != portfolio_decision_id
                or not isinstance(portfolio_snapshot_id, str)
            ):
                raise TransitionError(
                    "Study must execute the current Portfolio Decision target"
                )
            snapshot = _index.get("portfolio-snapshot", portfolio_snapshot_id)
            if snapshot is None:
                raise TransitionError("Study Portfolio snapshot is unavailable")
            decision = self._active_portfolio_decision(
                _index, portfolio_decision_id
            )
            if (
                decision is None
                or decision.payload.get("portfolio_snapshot_id")
                != portfolio_snapshot_id
            ):
                raise TransitionError("Study Portfolio Decision is unavailable or stale")
            try:
                action_diagnosis_authority = (
                    DiagnosisAuthorityContext.from_mapping(next_action)
                )
                decision_diagnosis_authority = (
                    DiagnosisAuthorityContext.from_mapping(
                        decision.payload
                    )
                )
                decision_diagnosis_authority.require_effective(
                    _index,
                    mission_id=science["active_mission"],
                )
            except DiagnosisAuthorityContextError as exc:
                raise RecoveryRequired(str(exc)) from exc
            if action_diagnosis_authority != decision_diagnosis_authority:
                raise TransitionError(
                    "Study Portfolio Decision diagnosis authority drifted"
                )
            from axiom_rift.operations.replay_projection import (
                ReplayProjectionError,
                ReplayTransitionError,
                require_study_pending,
            )

            try:
                replay_obligation_ids = require_study_pending(
                    _index,
                    mission_id=science["active_mission"],
                    decision_payload=decision.payload,
                    next_action=next_action,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            replacement_preflight = (
                self._current_accepted_replay_replacement_preflight(
                    _index,
                    mission_id=science["active_mission"],
                    obligation_ids=replay_obligation_ids,
                )
            )
            options = {
                option["option_id"]: option
                for option in decision.payload.get("options", [])
            }
            chosen = options.get(decision.payload.get("chosen_option_id"))
            work_actions = {
                "complementary_sleeve",
                "contrast",
                "deepen",
                "recombine",
                "rotate",
                "synthesize",
            }
            if (
                not isinstance(chosen, dict)
                or chosen.get("action") not in work_actions
                or chosen.get("target_id") != portfolio_axis_id
            ):
                raise TransitionError(
                    "Portfolio Decision does not authorize a scientific Study"
                )
            axis = next(
                (
                    value
                    for value in snapshot.payload["axes"]
                    if value["axis_id"] == portfolio_axis_id
                ),
                None,
            )
            if (
                axis is None
                or axis["status"] == "pruned"
                or axis.get("axis_identity") != portfolio_axis_identity
            ):
                raise TransitionError("Study Portfolio axis is absent or pruned")
            decision_baseline = decision.payload.get("baseline_executable")
            if not isinstance(decision_baseline, Mapping):
                raise RecoveryRequired(
                    "accepted Portfolio Decision baseline is malformed"
                )
            raw_post_holdout_id = next_action.get(
                "post_holdout_development_id"
            )
            baseline_data_contract = decision_baseline.get(
                "data_contract"
            )
            baseline_split_contract = decision_baseline.get(
                "split_contract"
            )
            if raw_post_holdout_id is not None and (
                not isinstance(baseline_data_contract, str)
                or not isinstance(baseline_split_contract, str)
            ):
                raise TransitionError(
                    "Study post-holdout development authority is malformed"
                )
            post_holdout_development_id, authorized_material = (
                self._require_post_holdout_decision_binding(
                    _index,
                    science=science,
                    decision=decision,
                    next_action=next_action,
                    data_contract=(
                        baseline_data_contract
                        if isinstance(raw_post_holdout_id, str)
                        else None
                    ),
                    split_contract=(
                        baseline_split_contract
                        if isinstance(raw_post_holdout_id, str)
                        else None
                    ),
                )
            )
            if (
                authorized_material is not None
                and authorized_material.record_id != material_identity
            ):
                raise TransitionError(
                    "Study material differs from its post-holdout authority"
                )
            source_authority_subject_ids = (
                self._source_authority_subject_ids(
                    decision_baseline,
                    error_type=RecoveryRequired,
                )
            )
            recorded_source_authority_subject_ids = decision.payload.get(
                "source_authority_subject_ids"
            )
            if (
                recorded_source_authority_subject_ids is not None
                and recorded_source_authority_subject_ids
                != list(source_authority_subject_ids)
            ):
                raise RecoveryRequired(
                    "accepted Portfolio Decision source authority is malformed"
                )
            effective_axis = self._effective_axis_resolution(
                _index,
                axis,
                prospective_source_ids=source_authority_subject_ids,
            )
            if not effective_axis.selectable:
                raise TransitionError(
                    "Study Portfolio axis is effectively blocked by current source authority"
                )
            mechanism_family = axis["mechanism_family"]
            primary_research_layer = axis["primary_research_layer"]
            system_architecture_family = axis["system_architecture_family"]
            changed_domains = list(axis["changed_domains"])
            controlled_domains = list(axis["controlled_domains"])
            portfolio_action = chosen["action"]
            commitment_batches = decision.payload["commitment_batches"]
            if (
                type(commitment_batches) is not int
                or commitment_batches <= 0
            ):
                raise TransitionError(
                    "Portfolio Decision must commit a positive finite Batch bound"
                )
            assert controlled_chassis is not None
            if [domain.value for domain in controlled_chassis.changed_domains] != sorted(
                changed_domains
            ):
                raise TransitionError(
                    "Study changed component domains differ from its Portfolio axis"
                )
            if [domain.value for domain in controlled_chassis.controlled_domains] != sorted(
                controlled_domains
            ):
                raise TransitionError(
                    "Study controlled component domains differ from its Portfolio axis"
                )
            typed_axis_chassis = axis.get("architecture_chassis_identity")
            accepted_architecture = next_action.get(
                "architecture_chassis_identity"
            )
            accepted_resolved_family = next_action.get(
                "resolved_architecture_family"
            )
            accepted_baseline = next_action.get("baseline_executable_id")
            resolved_controlled_family = (
                self._prospective_architecture_family_from_executable(
                    controlled_chassis.baseline_executable
                )
            )
            recorded_replacement_equivalence = decision.payload.get(
                "replacement_architecture_equivalence"
            )
            try:
                declared_axis_family = family_for_axis(
                    snapshot.payload,
                    axis,
                )
            except ProspectiveArchitectureProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            if declared_axis_family is None and isinstance(
                recorded_replacement_equivalence,
                Mapping,
            ):
                legacy_declared_family = (
                    recorded_replacement_equivalence.get(
                        "accepted_axis_architecture_family"
                    )
                )
                if isinstance(legacy_declared_family, str):
                    declared_axis_family = legacy_declared_family
            resolved_axis_family = None
            if isinstance(typed_axis_chassis, str):
                resolved_axis_family = (
                    declared_axis_family
                    or self._axis_prospective_architecture_family(
                        index=_index,
                        axis=axis,
                    )
                )
            axis_family_mismatch = (
                isinstance(typed_axis_chassis, str)
                and resolved_axis_family != resolved_controlled_family
            )
            prospective_reentry_plan = None
            prospective_reentry_validation = None
            raw_prospective_reentry = decision.payload.get(
                "engineering_reentry"
            )
            if isinstance(raw_prospective_reentry, Mapping):
                from axiom_rift.operations.prospective_engineering_reentry import (
                    ProspectiveEngineeringReentryValidationError,
                    require_prospective_engineering_reentry,
                )
                from axiom_rift.research.prospective_engineering_reentry import (
                    ProspectiveEngineeringReentry,
                    ProspectiveEngineeringReentryError,
                )

                try:
                    prospective_reentry_plan = (
                        ProspectiveEngineeringReentry.from_mapping(
                            raw_prospective_reentry
                        )
                    )
                    prospective_reentry_validation = (
                        require_prospective_engineering_reentry(
                            _index,
                            artifact_reader=self.evidence.read_verified,
                            plan=prospective_reentry_plan,
                            mission_id=science["active_mission"],
                            portfolio_snapshot_id=portfolio_snapshot_id,
                            portfolio_action=portfolio_action,
                            target_axis=axis,
                            baseline_executable_id=(
                                controlled_chassis
                                .baseline_executable.identity
                            ),
                        )
                    )
                except (
                    ProspectiveEngineeringReentryError,
                    ProspectiveEngineeringReentryValidationError,
                ) as exc:
                    raise TransitionError(str(exc)) from exc
                if (
                    prospective_reentry_plan.successor_study_id
                    != study_id
                    or semantic_question_lineage
                    != prospective_reentry_plan
                    .semantic_question_lineage
                    or prospective_reentry_plan.semantic_question_lineage
                    .successor_core_id
                    != semantic_question_core.identity
                    or decision.payload.get("engineering_reentry_id")
                    != prospective_reentry_plan.identity
                    or next_action.get("engineering_reentry_id")
                    != prospective_reentry_plan.identity
                    or decision.payload.get(
                        "engineering_reentry_validation"
                    )
                    != prospective_reentry_validation
                    or next_action.get("engineering_reentry_validation")
                    != prospective_reentry_validation
                ):
                    raise TransitionError(
                        "Study prospective engineering reentry differs "
                        "from its accepted Decision"
                    )
            elif (
                decision.payload.get("engineering_reentry_id") is not None
                or decision.payload.get(
                    "engineering_reentry_validation"
                )
                is not None
                or next_action.get("engineering_reentry_id") is not None
                or next_action.get("engineering_reentry_validation")
                is not None
            ):
                raise RecoveryRequired(
                    "Study prospective engineering reentry authority is "
                    "malformed"
                )
            recorded_replacement_equivalence = decision.payload.get(
                "replacement_architecture_equivalence"
            )
            action_replacement_equivalence = next_action.get(
                "replacement_architecture_equivalence"
            )
            recorded_prospective_equivalence = decision.payload.get(
                "prospective_reentry_equivalence"
            )
            action_prospective_equivalence = next_action.get(
                "prospective_reentry_equivalence"
            )
            if axis_family_mismatch and prospective_reentry_plan is not None:
                expected_prospective_equivalence = {
                    "accepted_axis_architecture_family": (
                        resolved_axis_family
                    ),
                    "engineering_gap_diagnosis_id": (
                        prospective_reentry_plan.study_diagnosis_id
                    ),
                    "engineering_reentry_id": (
                        prospective_reentry_plan.identity
                    ),
                    "replacement_architecture_family": (
                        resolved_controlled_family
                    ),
                    "replacement_baseline_executable_id": (
                        controlled_chassis.baseline_executable.identity
                    ),
                    "schema": (
                        "prospective_engineering_reentry_equivalence.v1"
                    ),
                    "semantic_question_lineage_id": (
                        prospective_reentry_plan
                        .semantic_question_lineage.identity
                    ),
                    "successor_artifact_hash": (
                        prospective_reentry_plan.successor_artifact_hash
                    ),
                    "successor_study_id": (
                        prospective_reentry_plan.successor_study_id
                    ),
                    "target_axis_identity": axis["axis_identity"],
                }
                if (
                    recorded_prospective_equivalence
                    != expected_prospective_equivalence
                    or action_prospective_equivalence
                    != expected_prospective_equivalence
                    or recorded_replacement_equivalence is not None
                    or action_replacement_equivalence is not None
                ):
                    raise TransitionError(
                        "Study prospective replacement chassis differs "
                        "from its accepted reentry authority"
                    )
            elif axis_family_mismatch:
                from axiom_rift.operations.replay_job_implementation_preflight import (
                    ReplayJobImplementationPreflightError,
                    ReplayJobImplementationPreflightRequest,
                    require_replacement_replay_study_semantics,
                )
                from axiom_rift.research.portfolio import BatchSpec
                from axiom_rift.research.semantic_question import (
                    SemanticQuestionLineageProposal,
                    SemanticQuestionRelation,
                )

                if not isinstance(
                    replay_implementation_request,
                    ReplayJobImplementationPreflightRequest,
                ):
                    raise TransitionError(
                        "Study replacement chassis lacks its exact implementation request"
                    )
                if not isinstance(replay_batch_spec, BatchSpec):
                    raise TransitionError(
                        "Study replacement chassis lacks its exact Batch spec"
                    )
                if (
                    not isinstance(
                        semantic_question_lineage,
                        SemanticQuestionLineageProposal,
                    )
                    or semantic_question_lineage.relation
                    is not SemanticQuestionRelation.ENGINEERING_REENTRY
                    or semantic_question_lineage.successor_study_id
                    != study_id
                    or semantic_question_lineage.predecessor_core_id
                    != semantic_question_lineage.successor_core_id
                    or semantic_question_lineage.successor_core_id
                    != semantic_question_core.identity
                ):
                    raise TransitionError(
                        "Study replacement chassis lacks engineering reentry lineage"
                    )
                prospective_replacement_study = {
                    "changed_domains": changed_domains,
                    "controlled_chassis": (
                        controlled_chassis.to_identity_payload()
                    ),
                    "controlled_domains": controlled_domains,
                    "material_identity": material_identity,
                    "mechanism_family": mechanism_family,
                    "mission_id": science["active_mission"],
                    "portfolio_action": portfolio_action,
                    "primary_research_layer": primary_research_layer,
                    "question": question_manifest,
                    "replay_obligation_ids": list(
                        replay_obligation_ids
                    ),
                    "semantic_proposal": semantic_proposal_manifest,
                    "semantic_question_core_id": (
                        semantic_question_core.identity
                    ),
                }
                try:
                    equivalence_hash = (
                        require_replacement_replay_study_semantics(
                            accepted_payload=(
                                {}
                                if replacement_preflight is None
                                else replacement_preflight.payload
                            ),
                            study_payload=prospective_replacement_study,
                        )
                    )
                except ReplayJobImplementationPreflightError as exc:
                    raise TransitionError(
                        "Study replacement chassis lacks exact accepted "
                        "scientific equivalence"
                    ) from exc
                assert replacement_preflight is not None
                prospective_study_binding_hash = _digest(
                    prospective_replacement_study,
                    domain="replay-replacement-study-binding",
                )
                expected_replacement_equivalence = {
                    "accepted_replacement_preflight_id": (
                        replacement_preflight.record_id
                    ),
                    "accepted_axis_architecture_family": (
                        resolved_axis_family
                    ),
                    "replacement_architecture_family": (
                        resolved_controlled_family
                    ),
                    "replacement_baseline_executable_id": (
                        controlled_chassis.baseline_executable.identity
                    ),
                    "replay_obligation_ids": list(
                        replay_obligation_ids
                    ),
                    "replacement_executable_ids": list(
                        replay_implementation_request.executable_ids
                    ),
                    "replacement_batch_id": replay_batch_spec.identity,
                    "replacement_request_identity": (
                        replay_implementation_request.identity
                    ),
                    "replacement_lineage_id": (
                        semantic_question_lineage.identity
                    ),
                    "schema": (
                        "replay_replacement_architecture_equivalence.v1"
                    ),
                    "scientific_equivalence_hash": equivalence_hash,
                    "prospective_study_binding_hash": (
                        prospective_study_binding_hash
                    ),
                    "target_axis_identity": axis["axis_identity"],
                }
                engineering_diagnosis_id = (
                    recorded_replacement_equivalence.get(
                        "engineering_gap_diagnosis_id"
                    )
                    if isinstance(
                        recorded_replacement_equivalence,
                        Mapping,
                    )
                    else None
                )
                decision_diagnosis_id = decision.payload.get(
                    "study_diagnosis_id"
                )
                decision_diagnosis = (
                    _index.get(
                        "study-diagnosis",
                        decision_diagnosis_id,
                    )
                    if isinstance(decision_diagnosis_id, str)
                    else None
                )
                if (
                    decision_diagnosis is not None
                    and decision_diagnosis.payload.get("evidence_state")
                    == "engineering_gap"
                    and engineering_diagnosis_id
                    != decision_diagnosis_id
                ):
                    raise RecoveryRequired(
                        "Study engineering reentry binding is absent"
                    )
                if isinstance(engineering_diagnosis_id, str):
                    engineering_diagnosis = _index.get(
                        "study-diagnosis",
                        engineering_diagnosis_id,
                    )
                    replaced_preflight_id = (
                        replacement_preflight.payload.get(
                            "replacement_for_preflight_id"
                        )
                    )
                    diagnosis_basis = (
                        set()
                        if engineering_diagnosis is None
                        else {
                            (
                                item.get("kind"),
                                item.get("record_id"),
                            )
                            for item in engineering_diagnosis.payload.get(
                                "evidence_basis",
                                [],
                            )
                            if isinstance(item, Mapping)
                        }
                    )
                    if (
                        engineering_diagnosis is None
                        or engineering_diagnosis.payload.get(
                            "evidence_state"
                        )
                        != "engineering_gap"
                        or decision.payload.get("study_diagnosis_id")
                        != engineering_diagnosis_id
                        or semantic_question_lineage
                        .predecessor_study_id
                        != engineering_diagnosis.payload.get("study_id")
                        or {
                            "study-diagnosis:"
                            + engineering_diagnosis_id,
                            "job-implementation-preflight:"
                            + replaced_preflight_id,
                        }.difference(
                            semantic_question_lineage.basis_record_ids
                        )
                        or (
                            "job-implementation-preflight",
                            replaced_preflight_id,
                        )
                        not in diagnosis_basis
                    ):
                        raise RecoveryRequired(
                            "Study engineering reentry diagnosis is malformed"
                        )
                    expected_replacement_equivalence[
                        "engineering_gap_diagnosis_id"
                    ] = engineering_diagnosis_id
                if (
                    recorded_replacement_equivalence
                    != expected_replacement_equivalence
                    or action_replacement_equivalence
                    != expected_replacement_equivalence
                ):
                    raise TransitionError(
                        "Study replacement chassis differs from its "
                        "accepted Decision equivalence"
                    )
            elif (
                recorded_replacement_equivalence is not None
                or action_replacement_equivalence is not None
                or recorded_prospective_equivalence is not None
                or action_prospective_equivalence is not None
            ):
                raise RecoveryRequired(
                    "Study carries unnecessary replacement architecture authority"
                )
            if (
                not isinstance(accepted_architecture, str)
                or not isinstance(accepted_resolved_family, str)
                or not isinstance(accepted_baseline, str)
                or accepted_architecture
                != decision.payload.get("architecture_chassis_identity")
                or decision.payload.get("architecture_chassis")
                != controlled_chassis.architecture.to_identity_payload()
                or accepted_baseline
                != decision.payload.get("baseline_executable_id")
                or accepted_architecture
                != controlled_chassis.architecture.identity
                or accepted_baseline
                != controlled_chassis.baseline_executable.identity
                or accepted_resolved_family != resolved_controlled_family
            ):
                raise TransitionError(
                    "Study chassis differs from its accepted Portfolio Decision anchor"
                )
            self._require_registered_chassis_baseline(
                index=_index,
                controlled_chassis=controlled_chassis,
                decision=decision,
            )
            self._require_component_parity_evidence(
                index=_index,
                controlled_chassis=controlled_chassis,
                mission_id=science["active_mission"],
                portfolio_decision_id=portfolio_decision_id,
            )
            required_study_scope = {
                "study",
                f"decision:{portfolio_decision_id}",
                f"axis:{portfolio_axis_identity}",
                f"baseline:{accepted_baseline}",
                f"chassis:{accepted_architecture}",
                f"snapshot:{portfolio_snapshot_id}",
            }
            if not required_study_scope.issubset(permit.scope):
                raise TransitionError(
                    "StudyPermit does not bind the accepted Portfolio Decision"
                )
            system_architecture_family = resolved_controlled_family
        return _StudyPortfolioPlan(
            portfolio_snapshot_id=portfolio_snapshot_id,
            mechanism_family=mechanism_family,
            primary_research_layer=primary_research_layer,
            system_architecture_family=system_architecture_family,
            portfolio_architecture_family=(
                None
                if self.engineering_fixture
                else axis["system_architecture_family"]
            ),
            changed_domains=changed_domains,
            controlled_domains=controlled_domains,
            portfolio_action=portfolio_action,
            commitment_batches=commitment_batches,
            post_holdout_development_id=post_holdout_development_id,
            replay_obligation_ids=replay_obligation_ids,
            replacement_preflight=replacement_preflight,
        )

    def _prepare_study_replay_admission(
        self,
        *,
        current: Mapping[str, Any],
        index: LocalIndex,
        science: Mapping[str, Any],
        study_id: str,
        plan: _StudyPortfolioPlan,
        question_manifest: Mapping[str, Any],
        material_identity: str,
        semantic_proposal_manifest: Mapping[str, Any],
        semantic_question_core: Any,
        controlled_chassis: Any | None,
        replay_implementation_request: Any | None,
        replay_batch_spec: Any | None,
    ) -> IndexRecord | None:
        """Validate and assemble replay implementation admission authority."""

        replay_obligation_ids = plan.replay_obligation_ids
        replacement_preflight = plan.replacement_preflight
        mechanism_family = plan.mechanism_family
        primary_research_layer = plan.primary_research_layer
        changed_domains = plan.changed_domains
        controlled_domains = plan.controlled_domains
        portfolio_action = plan.portfolio_action
        _index = index
        admission_record: IndexRecord | None = None
        if replay_obligation_ids:
            from axiom_rift.operations.research_protocol_projection import (
                ResearchProtocolProjectionError,
                require_current_research_protocol_activation,
            )
            from axiom_rift.operations.replay_job_implementation_preflight import (
                PREFLIGHT_SCHEMA,
                ReplayJobImplementationPreflightError,
                ReplayJobImplementationPreflightRequest,
                derive_replay_job_scientific_surface,
                evaluate_replay_job_implementation_preflight,
                replay_job_scientific_surface_hash,
                require_active_replay_job_replacement_binding,
            )
            from axiom_rift.research.portfolio import BatchSpec

            if (
                not isinstance(
                    replay_implementation_request,
                    ReplayJobImplementationPreflightRequest,
                )
                or not isinstance(replay_batch_spec, BatchSpec)
                or replay_implementation_request.mission_id
                != science["active_mission"]
                or replay_implementation_request.replay_obligation_ids
                != replay_obligation_ids
                or replay_implementation_request.replacement_for_preflight_id
                is not None
            ):
                raise TransitionError(
                    "replay Study lacks typed implementation admission"
                )
            authority_manifest_digest = current.get("authority", {}).get(
                "manifest_digest"
            )
            try:
                protocol_activation = (
                    require_current_research_protocol_activation(
                        _index,
                        authority_manifest_digest=authority_manifest_digest,
                    )
                )
            except ResearchProtocolProjectionError as exc:
                raise TransitionError(
                    "replay Study requires the current prospective protocol "
                    "before implementation admission"
                ) from exc
            current_preflight = (
                evaluate_replay_job_implementation_preflight(
                    replay_implementation_request,
                    index=_index,
                    artifact_reader=self.evidence.read_verified,
                    source_root=(self.foundation_root / "src").absolute(),
                )
            )
            if not current_preflight.accepted:
                raise TransitionError(
                    "replay Study implementation is not current: "
                    f"{current_preflight.reason_code}: "
                    f"{current_preflight.failure_detail}"
                )
            study_surface_payload = {
                "changed_domains": changed_domains,
                "controlled_chassis": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.to_identity_payload()
                ),
                "controlled_domains": controlled_domains,
                "material_identity": material_identity,
                "mechanism_family": mechanism_family,
                "mission_id": science["active_mission"],
                "portfolio_action": portfolio_action,
                "primary_research_layer": primary_research_layer,
                "question": question_manifest,
                "replay_obligation_ids": list(replay_obligation_ids),
                "semantic_proposal": semantic_proposal_manifest,
                "semantic_question_core_id": semantic_question_core.identity,
            }
            try:
                scientific_surface = derive_replay_job_scientific_surface(
                    replay_implementation_request,
                    study_payload=study_surface_payload,
                    batch_payload={
                        "spec": replay_batch_spec.to_identity_payload()
                    },
                    artifact_reader=self.evidence.read_verified,
                )
                scientific_surface_hash = (
                    replay_job_scientific_surface_hash(
                        scientific_surface
                    )
                )
                active_payload = {
                        "callable_identity": (
                            replay_implementation_request.callable_identity
                        ),
                        "executable_ids": list(
                            replay_implementation_request.executable_ids
                        ),
                        "executable_manifests": [
                            executable.to_identity_payload()
                            for executable in (
                                replay_implementation_request.executables
                            )
                        ],
                        "implementation_identity": (
                            replay_implementation_request
                            .implementation_identity
                        ),
                        "mission_id": (
                            replay_implementation_request.mission_id
                        ),
                        "protocol_id": (
                            replay_implementation_request.protocol_id
                        ),
                        "replacement_for_preflight_id": None,
                        "replay_obligation_ids": list(
                            replay_implementation_request
                            .replay_obligation_ids
                        ),
                        "schema": PREFLIGHT_SCHEMA,
                        "scientific_surface": scientific_surface,
                        "scientific_surface_hash": (
                            scientific_surface_hash
                        ),
                    }
                if replacement_preflight is not None:
                    require_active_replay_job_replacement_binding(
                        accepted_payload=replacement_preflight.payload,
                        active_payload=active_payload,
                    )
            except ReplayJobImplementationPreflightError as exc:
                raise TransitionError(str(exc)) from exc
            request_payload = (
                replay_implementation_request.to_identity_payload()
            )
            admission_payload = {
                "accepted_replacement_preflight_id": (
                    None
                    if replacement_preflight is None
                    else replacement_preflight.record_id
                ),
                "authority_manifest_digest": authority_manifest_digest,
                "batch_id": replay_batch_spec.identity,
                "request": request_payload,
                "research_protocol_activation_id": (
                    protocol_activation.record_id
                ),
                "schema": "replay_implementation_admission.v1",
                "scientific_surface": scientific_surface,
                "scientific_surface_hash": scientific_surface_hash,
                "source_closure_authority": dict(
                    current_preflight.source_closure_authority or {}
                ),
                "study_id": study_id,
            }
            admission_fingerprint = _digest(
                admission_payload,
                domain="replay-implementation-admission",
            )
            admission_record = _record(
                kind="replay-implementation-admission",
                record_id=(
                    "replay-implementation-admission:"
                    + admission_fingerprint
                ),
                subject=f"Study:{study_id}",
                status="active",
                fingerprint=admission_fingerprint,
                payload=admission_payload,
            )
        elif (
            replay_implementation_request is not None
            or replay_batch_spec is not None
        ):
            raise TransitionError(
                "replay implementation admission lacks a replacement trigger"
            )
        return admission_record

    def _prepare_study_trial_context(
        self,
        *,
        index: LocalIndex,
        science: Mapping[str, Any],
        trial_accountant: Any,
        material_reference: Any,
        material_identity: str,
        semantic_proposal_manifest: Mapping[str, Any],
    ) -> tuple[Any, int, int]:
        """Resolve material eligibility and immutable prior multiplicity."""

        from axiom_rift.research.trials import StudyTrialContext

        _index = index

        if material_identity == trial_accountant.observed_material_identity:
            trial_context = trial_accountant.open_study(
                material=material_reference,
                semantic_proposal=semantic_proposal_manifest,
            )
        else:
            development_material = _index.get(
                "development-material", material_identity
            )
            if (
                development_material is None
                or development_material.status != "accepted"
                or development_material.subject
                != f"Mission:{science['active_mission']}"
                or development_material.payload.get("mission_id")
                != science["active_mission"]
                or development_material.payload.get("material_identity")
                != material_identity
                or (
                    science["holdout_reveals"] > 0
                    and development_material.payload.get("holdout_id")
                    != science.get("required_future_holdout_id")
                )
            ):
                raise TransitionError(
                    "Study material is not registered for the active Mission"
                )
            trial_context = StudyTrialContext(
                material_identity=material_identity,
                prior_global_multiplicity=0,
                semantic_warnings=trial_accountant.lookup_semantic_warnings(
                    semantic_proposal_manifest
                ),
                warning_scheduler_weight="none",
            )
        trial_head = _index.event_head(
            f"material-trial:{trial_context.material_identity}"
        )
        prior_global_multiplicity = (
            trial_context.prior_global_multiplicity
            + (0 if trial_head is None else trial_head.sequence)
        )
        prior_material_trial_count = 0 if trial_head is None else trial_head.sequence
        return (
            trial_context,
            prior_global_multiplicity,
            prior_material_trial_count,
        )

    def _build_study_open_record(
        self,
        *,
        study_id: str,
        study_hash: str,
        question_hash: str,
        question_manifest: Mapping[str, Any],
        science: Mapping[str, Any],
        trial_context: Any,
        prior_global_multiplicity: int,
        prior_material_trial_count: int,
        plan: _StudyPortfolioPlan,
        controlled_chassis: Any | None,
        portfolio_axis_id: str | None,
        portfolio_axis_identity: str | None,
        portfolio_decision_id: str | None,
        semantic_proposal_manifest: Mapping[str, Any],
        semantic_question_core: Any,
        semantic_question_equivalence: Any | None,
        semantic_question_lineage: Any | None,
        admission_record: IndexRecord | None,
    ) -> IndexRecord:
        """Assemble the canonical Study-open record from validated authority."""

        mechanism_family = plan.mechanism_family
        primary_research_layer = plan.primary_research_layer
        system_architecture_family = plan.system_architecture_family
        changed_domains = plan.changed_domains
        controlled_domains = plan.controlled_domains
        portfolio_action = plan.portfolio_action
        portfolio_snapshot_id = plan.portfolio_snapshot_id
        post_holdout_development_id = plan.post_holdout_development_id
        commitment_batches = plan.commitment_batches
        replay_obligation_ids = plan.replay_obligation_ids
        record = _record(
            kind="study-open",
            record_id=study_id,
            subject=f"Study:{study_id}",
            status="open",
            fingerprint=study_hash,
            payload={
                "question_hash": question_hash,
                "question": question_manifest,
                "material_identity": trial_context.material_identity,
                "mechanism_family": mechanism_family,
                "mission_id": science["active_mission"],
                "primary_research_layer": primary_research_layer,
                "system_architecture_family": system_architecture_family,
                "portfolio_architecture_family": (
                    plan.portfolio_architecture_family
                ),
                "controlled_chassis": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.to_identity_payload()
                ),
                "controlled_chassis_identity": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.controlled_chassis_identity
                ),
                "changed_domains": changed_domains,
                "controlled_domains": controlled_domains,
                "portfolio_action": portfolio_action,
                "portfolio_axis_id": portfolio_axis_id,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "portfolio_snapshot_id": portfolio_snapshot_id,
                **(
                    {
                        "post_holdout_development_id": (
                            post_holdout_development_id
                        )
                    }
                    if isinstance(post_holdout_development_id, str)
                    else {}
                ),
                "commitment_batches": commitment_batches,
                "semantic_proposal": semantic_proposal_manifest,
                "semantic_question_core_id": semantic_question_core.identity,
                "semantic_question_equivalence": (
                    None
                    if semantic_question_equivalence is None
                    else semantic_question_equivalence.to_identity_payload()
                ),
                "semantic_question_equivalence_id": (
                    None
                    if semantic_question_equivalence is None
                    else semantic_question_equivalence.identity
                ),
                "semantic_question_lineage": (
                    None
                    if semantic_question_lineage is None
                    else semantic_question_lineage.to_identity_payload()
                ),
                "semantic_question_lineage_id": (
                    None
                    if semantic_question_lineage is None
                    else semantic_question_lineage.identity
                ),
                "prior_global_multiplicity": prior_global_multiplicity,
                "prior_material_trial_count": prior_material_trial_count,
                "semantic_warning_ids": [
                    warning.warning_id for warning in trial_context.semantic_warnings
                ],
                "warning_scheduler_weight": trial_context.warning_scheduler_weight,
                **(
                    {"replay_obligation_ids": list(replay_obligation_ids)}
                    if replay_obligation_ids
                    else {}
                ),
                **(
                    {
                        "replay_implementation_admission_id": (
                            admission_record.record_id
                        )
                    }
                    if admission_record is not None
                    else {}
                ),
            },
        )
        return record

    def _build_study_semantic_records(
        self,
        *,
        index: LocalIndex,
        record: IndexRecord,
        study_id: str,
        semantic_question_core: Any,
        semantic_question_equivalence: Any | None,
        semantic_question_lineage: Any | None,
    ) -> list[IndexRecord]:
        """Project semantic-core, equivalence, and lineage rows atomically."""

        _index = index
        semantic_records: list[IndexRecord] = []
        from axiom_rift.operations.semantic_question_registry import (
            SemanticQuestionRegistryError,
            SemanticQuestionRegistryIntegrityError,
            require_repeated_core_lineage,
            require_semantic_question_projection,
            require_semantic_question_registry_activation,
            semantic_question_prospective_equivalence_record,
            semantic_question_prospective_lineage_record,
            semantic_question_records_for_study,
        )

        try:
            registry_active = (
                require_semantic_question_registry_activation(_index)
                is not None
            )
            if registry_active:
                require_repeated_core_lineage(
                    _index,
                    successor_study_id=study_id,
                    successor_core_id=semantic_question_core.identity,
                    proposal=semantic_question_lineage,
                )
                for projected in semantic_question_records_for_study(record):
                    pending = require_semantic_question_projection(
                        _index, projected
                    )
                    if pending is not None:
                        semantic_records.append(pending)
                equivalence_record = None
                if semantic_question_equivalence is not None:
                    equivalence_record = (
                        semantic_question_prospective_equivalence_record(
                            _index,
                            record,
                            semantic_question_equivalence,
                        )
                    )
                    pending = require_semantic_question_projection(
                        _index, equivalence_record
                    )
                    if pending is not None:
                        semantic_records.append(pending)
                if semantic_question_lineage is not None:
                    lineage_record = (
                        semantic_question_prospective_lineage_record(
                            _index,
                            record,
                            semantic_question_lineage,
                            equivalence_record=equivalence_record,
                        )
                    )
                    pending = require_semantic_question_projection(
                        _index, lineage_record
                    )
                    if pending is not None:
                        semantic_records.append(pending)
        except SemanticQuestionRegistryIntegrityError as exc:
            raise RecoveryRequired(str(exc)) from exc
        except SemanticQuestionRegistryError as exc:
            raise TransitionError(str(exc)) from exc
        return semantic_records
    def open_study(
        self,
        *,
        study_id: str,
        question: Mapping[str, Any],
        material_identity: str,
        material_display_name: str,
        semantic_proposal: Mapping[str, Any],
        semantic_question_equivalence: Any | None = None,
        semantic_question_lineage: Any | None = None,
        controlled_chassis: Any | None = None,
        permit: Permit,
        operation_id: str,
        portfolio_axis_id: str | None = None,
        portfolio_axis_identity: str | None = None,
        portfolio_decision_id: str | None = None,
        replay_implementation_request: Any | None = None,
        replay_batch_spec: Any | None = None,
    ) -> TransitionResult:
        self._require_study_close_delivery_guard()
        try:
            validate_study_id(study_id)
        except ValueError as exc:
            raise TransitionError("study_id is invalid") from exc
        question_manifest = _require_manifest(
            "question",
            question,
            required={
                "causal_question",
                "changed_variables",
                "controlled_variables",
                "done_conditions",
                "evidence_modes",
            },
        )
        question_manifest["evidence_modes"] = list(
            _require_study_evidence_modes(question_manifest)
        )
        question_hash = _digest(question_manifest, domain="study-question")
        _require_ascii("material_identity", material_identity)
        _require_ascii("material_display_name", material_display_name)
        semantic_proposal_manifest = _copy(semantic_proposal)
        from axiom_rift.research.semantic_question import (
            SemanticQuestionCore,
            SemanticQuestionEquivalenceProposal,
            SemanticQuestionError,
            SemanticQuestionLineageProposal,
        )

        try:
            semantic_question_core = SemanticQuestionCore.from_question_manifest(
                question_manifest
            )
        except SemanticQuestionError as exc:
            raise TransitionError(str(exc)) from exc
        if semantic_question_equivalence is not None and not isinstance(
            semantic_question_equivalence,
            SemanticQuestionEquivalenceProposal,
        ):
            raise TransitionError(
                "semantic_question_equivalence must be a typed proposal"
            )
        if semantic_question_lineage is not None and not isinstance(
            semantic_question_lineage,
            SemanticQuestionLineageProposal,
        ):
            raise TransitionError(
                "semantic_question_lineage must be a typed proposal"
            )
        from axiom_rift.research.trials import (
            MaterialReference,
            TrialAccountant,
        )
        from axiom_rift.research.chassis import ControlledStudyChassis

        if controlled_chassis is not None and not isinstance(
            controlled_chassis, ControlledStudyChassis
        ):
            raise TransitionError("controlled_chassis must be a ControlledStudyChassis")
        if not self.engineering_fixture and controlled_chassis is None:
            raise TransitionError(
                "scientific Study requires a typed controlled component chassis"
            )

        trial_accountant = TrialAccountant.from_foundation(self.foundation_root)
        material_reference = MaterialReference(
            identity=material_identity,
            display_name=material_display_name,
        )
        study_hash = self.study_input_hash(
            question=question_manifest,
            material_identity=material_identity,
            semantic_proposal=semantic_proposal_manifest,
            semantic_question_equivalence=semantic_question_equivalence,
            semantic_question_lineage=semantic_question_lineage,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=portfolio_axis_id,
            portfolio_axis_identity=portfolio_axis_identity,
            portfolio_decision_id=portfolio_decision_id,
        )


        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_initiative"] is None or science["active_study"] is not None:
                raise TransitionError("Study open requires an Initiative and no active Study")
            initiative_id = science["active_initiative"]

            plan = self._prepare_study_portfolio_plan(
                current=current,
                index=_index,
                science=science,
                study_id=study_id,
                question_manifest=question_manifest,
                material_identity=material_identity,
                semantic_proposal_manifest=semantic_proposal_manifest,
                semantic_question_core=semantic_question_core,
                semantic_question_lineage=semantic_question_lineage,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=portfolio_axis_id,
                portfolio_axis_identity=portfolio_axis_identity,
                portfolio_decision_id=portfolio_decision_id,
                replay_implementation_request=replay_implementation_request,
                replay_batch_spec=replay_batch_spec,
                permit=permit,
            )
            admission_record = self._prepare_study_replay_admission(
                current=current,
                index=_index,
                science=science,
                study_id=study_id,
                plan=plan,
                question_manifest=question_manifest,
                material_identity=material_identity,
                semantic_proposal_manifest=semantic_proposal_manifest,
                semantic_question_core=semantic_question_core,
                controlled_chassis=controlled_chassis,
                replay_implementation_request=replay_implementation_request,
                replay_batch_spec=replay_batch_spec,
            )
            (
                trial_context,
                prior_global_multiplicity,
                prior_material_trial_count,
            ) = self._prepare_study_trial_context(
                index=_index,
                science=science,
                trial_accountant=trial_accountant,
                material_reference=material_reference,
                material_identity=material_identity,
                semantic_proposal_manifest=semantic_proposal_manifest,
            )
            self._validate_permit_locked(
                control=current,
                index=_index,
                permit=permit,
                expected_kind=PermitKind.STUDY,
                action="open_study",
                subject_kind=SubjectKind.INITIATIVE,
                subject_id=initiative_id,
                expected_input_hash=study_hash,
            )
            science["active_study"] = study_id
            body["next_action"] = {"kind": "freeze_batch", "study_id": study_id}
            authorization = self._authorization(
                kind=SubjectKind.STUDY,
                subject_id=study_id,
                semantic_hash=study_hash,
            )
            self._bind_authorization(body, authorization)
            consumption = self._permit_consumption_record(permit, operation_id)
            record = self._build_study_open_record(
                study_id=study_id,
                study_hash=study_hash,
                question_hash=question_hash,
                question_manifest=question_manifest,
                science=science,
                trial_context=trial_context,
                prior_global_multiplicity=prior_global_multiplicity,
                prior_material_trial_count=prior_material_trial_count,
                plan=plan,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=portfolio_axis_id,
                portfolio_axis_identity=portfolio_axis_identity,
                portfolio_decision_id=portfolio_decision_id,
                semantic_proposal_manifest=semantic_proposal_manifest,
                semantic_question_core=semantic_question_core,
                semantic_question_equivalence=semantic_question_equivalence,
                semantic_question_lineage=semantic_question_lineage,
                admission_record=admission_record,
            )
            semantic_records = self._build_study_semantic_records(
                index=_index,
                record=record,
                study_id=study_id,
                semantic_question_core=semantic_question_core,
                semantic_question_equivalence=semantic_question_equivalence,
                semantic_question_lineage=semantic_question_lineage,
            )
            return body, [
                consumption,
                *((admission_record,) if admission_record is not None else ()),
                record,
                *semantic_records,
            ], {
                "study_id": study_id,
                "study_hash": study_hash,
                "semantic_question_core_id": semantic_question_core.identity,
                "semantic_question_lineage_id": (
                    None
                    if semantic_question_lineage is None
                    else semantic_question_lineage.identity
                ),
                "controlled_chassis_identity": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.controlled_chassis_identity
                ),
                "replay_implementation_admission_id": (
                    None
                    if admission_record is None
                    else admission_record.record_id
                ),
                "prior_global_multiplicity": prior_global_multiplicity,
                "semantic_warning_count": len(trial_context.semantic_warnings),
            }
        return self._commit(
            event_kind="study_opened",
            operation_id=operation_id,
            subject=f"Study:{study_id}",
            payload={
                "study_id": study_id,
                "question_hash": question_hash,
                "question": question_manifest,
                "material_identity": material_identity,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "study_hash": study_hash,
                "permit_id": permit.permit_id,
                "semantic_question_core_id": semantic_question_core.identity,
                "semantic_question_equivalence_id": (
                    None
                    if semantic_question_equivalence is None
                    else semantic_question_equivalence.identity
                ),
                "semantic_question_lineage_id": (
                    None
                    if semantic_question_lineage is None
                    else semantic_question_lineage.identity
                ),
            },
            prepare=prepare,
        )

    def study_chassis_combination_identity(
        self,
        *,
        left_study_id: str,
        right_study_id: str,
        shared_domains: tuple[Any, ...],
    ) -> str:
        """Prove cross-Study chassis compatibility from stored Writer authority."""

        validate_study_id(left_study_id)
        validate_study_id(right_study_id)
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            combine_control_payloads,
        )
        from axiom_rift.research.governance import ResearchLayer

        if type(shared_domains) is not tuple or not shared_domains or any(
            not isinstance(domain, ResearchLayer) for domain in shared_domains
        ):
            raise TransitionError("shared chassis domains are not typed")
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                self._require_stable_locked(index)
                studies = [
                    index.get("study-open", study_id)
                    for study_id in (left_study_id, right_study_id)
                ]
                if any(study is None for study in studies):
                    raise TransitionError(
                        "cross-Study chassis proof requires registered Studies"
                    )
                payloads: list[Mapping[str, Any]] = []
                for study in studies:
                    assert study is not None
                    payload = study.payload.get("controlled_chassis")
                    mission_id = study.payload.get("mission_id")
                    decision_id = study.payload.get("portfolio_decision_id")
                    if (
                        not isinstance(payload, dict)
                        or not isinstance(mission_id, str)
                        or not isinstance(decision_id, str)
                    ):
                        raise TransitionError(
                            "Study lacks a Writer-bound controlled chassis"
                        )
                    equivalences = payload.get("equivalences")
                    if not isinstance(equivalences, list):
                        raise TransitionError(
                            "Study component equivalences are malformed"
                        )
                    for equivalence in equivalences:
                        if not isinstance(equivalence, dict):
                            raise TransitionError(
                                "Study component equivalence is malformed"
                            )
                        self._require_component_parity_payload(
                            index=index,
                            equivalence=equivalence,
                            mission_id=mission_id,
                            portfolio_decision_id=decision_id,
                        )
                    payloads.append(payload)
                surface_seeds: set[str] = set()
                component_seeds: set[str] = set()
                for payload in payloads:
                    architecture = payload.get("architecture")
                    roles = (
                        None
                        if not isinstance(architecture, dict)
                        else architecture.get("roles")
                    )
                    if not isinstance(roles, dict):
                        raise TransitionError(
                            "Study architecture roles are malformed"
                        )
                    for role in roles.values():
                        surfaces = (
                            None
                            if not isinstance(role, dict)
                            else role.get("component_semantic_surfaces")
                        )
                        if not isinstance(surfaces, list):
                            raise TransitionError(
                                "Study architecture surfaces are malformed"
                            )
                        surface_seeds.update(
                            value for value in surfaces if isinstance(value, str)
                        )
                    components = payload.get("controlled_component_identities")
                    if not isinstance(components, dict):
                        raise TransitionError(
                            "Study controlled component identities are malformed"
                        )
                    for domain in shared_domains:
                        values = components.get(domain.value)
                        if not isinstance(values, list):
                            raise TransitionError(
                                "Study shared controlled domain is malformed"
                            )
                        component_seeds.update(
                            value for value in values if isinstance(value, str)
                        )
                try:
                    return combine_control_payloads(
                        payloads[0],
                        payloads[1],
                        shared_domains=shared_domains,
                        verified_equivalences=self._verified_component_parity_edges(
                            index,
                            surface_seeds=tuple(sorted(surface_seeds)),
                            component_seeds=tuple(sorted(component_seeds)),
                        ),
                    )
                except ChassisIdentityError as exc:
                    raise TransitionError(str(exc)) from exc

