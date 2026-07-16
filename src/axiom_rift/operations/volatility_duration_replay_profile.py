"""Read-only reconstruction profile for the already registered STU-0113 attempt.

The current attempt was registered before prospective implementation admission
existed.  Its Executables are reconstructed from immutable Writer records so
the attempt can be closed and diagnosed honestly after its historical source
module is restored.  This profile is not a source of new Executable identity.
"""

from __future__ import annotations

from collections.abc import Mapping

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BLOCK_LENGTHS,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    SELECTION_SEED,
)
from axiom_rift.research.fixed_hold_family_job import (
    build_fixed_hold_family_job_plan,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    historical_family_authority_from_payload,
)
from axiom_rift.research.portfolio_projection import (
    executable_from_identity_payload,
)
from axiom_rift.research.scientific_trace import (
    VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
)
from axiom_rift.research.trials import TrialAccountant


STU0051_CAUSAL_QUESTION = (
    "Does an exact prospective reconstruction of the four-member STU-0051 "
    "volatility state-age family preserve causal, after-cost evidence under "
    "exact controls and concurrent-family inference?"
)
_ATTEMPT_ARTIFACT_NAMESPACE = "stu0051-volatility-duration-replay-v1"
_CONTEXT_PARAMETER = "historical_context_prior_global_exposure_count"
_ATTEMPT_ENGINE_DIGEST_FIELDS = {
    "adapter": "adapter_sha256",
    "catalog": "catalog_sha256",
    "loader": "loader_sha256",
    "shared": "discovery_sha256",
    "trace_engine": "trace_engine_sha256",
}


def require_volatility_duration_family_authority(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
) -> HistoricalFamilyAuthority:
    with writer.open_stable_index() as (_control, index):
        record = index.get(
            "historical-family-authority",
            historical_family_authority_id,
        )
    if record is None:
        raise RuntimeError("STU-0113 historical family authority is absent")
    authority = historical_family_authority_from_payload(record.payload)
    if (
        record.record_id != authority.identity
        or record.status != "accepted"
        or record.subject != f"ReplayObligation:{spec.target_obligation_id}"
        or authority.identity != historical_family_authority_id
        or authority.replay_obligation_id != spec.target_obligation_id
        or authority.family.original_study_id != spec.original_study_id
    ):
        raise RuntimeError("STU-0113 historical family authority drifted")
    return authority


def _engine_producer_identities(engine_contract: str) -> tuple[tuple[str, str], ...]:
    if type(engine_contract) is not str or not engine_contract.isascii():
        raise RuntimeError("STU-0113 engine contract is malformed")
    observed: dict[str, str] = {}
    for value in engine_contract.split(":"):
        for prefix, field in _ATTEMPT_ENGINE_DIGEST_FIELDS.items():
            marker = prefix + "_"
            if value.startswith(marker):
                digest = value.removeprefix(marker)
                if (
                    len(digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in digest
                    )
                    or field in observed
                ):
                    raise RuntimeError("STU-0113 engine digest is malformed")
                observed[field] = digest
    if set(observed) != set(_ATTEMPT_ENGINE_DIGEST_FIELDS.values()):
        raise RuntimeError("STU-0113 engine digest surface is incomplete")
    return tuple(sorted(observed.items()))


def _attempt_definition(
    *,
    family_authority: HistoricalFamilyAuthority,
    executable_ids: tuple[str, ...],
    clock_contract: str,
    cost_contract: str,
    engine_contract: str,
    prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    return FixedHoldProtocolDefinition(
        family=family_authority.family,
        prospective_executable_ids=executable_ids,
        protocol_id=VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=(
            "mature_state_age_24_47",
            "persistent_state_age_72_143",
        ),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=clock_contract,
        cost_contract=cost_contract,
        producer_implementation_identities=_engine_producer_identities(
            engine_contract
        ),
        historical_context_id=family_authority.replay_obligation_id,
        historical_prior_global_exposure_count=prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
        alpha_ppm=100_000,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=(
            SELECTION_MONTE_CARLO_CONFIDENCE_PPM
        ),
        base_seed=SELECTION_SEED,
    )


def _rehydrate_attempt(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    family_authority: HistoricalFamilyAuthority,
) -> tuple[
    tuple[FixedHoldReplayMember, ...],
    ControlledStudyChassis,
]:
    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    with writer.open_stable_index() as (_control, index):
        study = index.get("study-open", spec.study_id)
        batch_stream = f"study-batches:{spec.study_id}"
        batch_head = index.event_head(batch_stream)
        batch_event = (
            None
            if batch_head is None or batch_head.sequence != 1
            else index.event_record(batch_stream, 1)
        )
        batch_id = None if batch_event is None else batch_event.record_id
        batch = (
            None if batch_id is None else index.get("batch-open", batch_id)
        )
        trial_stream = None if batch_id is None else f"batch-trials:{batch_id}"
        trial_head = (
            None if trial_stream is None else index.event_head(trial_stream)
        )
        if (
            study is None
            or batch_event is None
            or batch is None
            or trial_stream is None
            or trial_head is None
            or trial_head.sequence != family_authority.family.family_size
        ):
            raise RuntimeError("STU-0113 durable attempt is incomplete")
        trial_records = tuple(
            index.event_record(trial_stream, ordinal)
            for ordinal in range(1, trial_head.sequence + 1)
        )
        exposure = project_frozen_family_exposure_context(
            index,
            prior_global_exposure_floor=floor,
            study_id=spec.study_id,
            batch_id=batch_id,
            expected_family_size=family_authority.family.family_size,
            parameter_name=_CONTEXT_PARAMETER,
            allow_unregistered=False,
        )
        original_end = project_historical_family_end_global_exposure_count(
            index,
            prior_global_exposure_floor=floor,
            family=family_authority.family,
        )

    if any(record is None for record in trial_records):
        raise RuntimeError("STU-0113 trial stream has a gap")
    trials = tuple(record for record in trial_records if record is not None)
    executables = tuple(
        executable_from_identity_payload(record.payload["executable"])
        for record in trials
    )
    if tuple(executable.identity for executable in executables) != tuple(
        record.record_id for record in trials
    ):
        raise RuntimeError("STU-0113 Executable payload drifted")
    family_references = tuple(
        member.historical_reference_executable_id
        for member in family_authority.family.members
    )
    observed_references = tuple(
        str(executable.parameter_values()["historical_reference_executable_id"])
        for executable in executables
    )
    contexts = {
        executable.parameter_values().get(_CONTEXT_PARAMETER)
        for executable in executables
        if isinstance(executable.parameter_values(), Mapping)
    }
    clocks = {executable.clock_contract for executable in executables}
    costs = {executable.cost_contract for executable in executables}
    engines = {executable.engine_contract for executable in executables}
    batch_spec = batch.payload.get("spec")
    acceptance = (
        None
        if not isinstance(batch_spec, Mapping)
        else batch_spec.get("acceptance_profile")
    )
    concurrent = (
        None
        if not isinstance(acceptance, Mapping)
        else acceptance.get("concurrent_family")
    )
    if (
        observed_references != family_references
        or contexts != {exposure.prior_global_exposure_count}
        or len(clocks) != 1
        or len(costs) != 1
        or len(engines) != 1
        or not isinstance(concurrent, Mapping)
        or concurrent.get("executable_ids")
        != sorted(executable.identity for executable in executables)
    ):
        raise RuntimeError("STU-0113 registered family drifted")

    definition = _attempt_definition(
        family_authority=family_authority,
        executable_ids=tuple(
            executable.identity for executable in executables
        ),
        clock_contract=next(iter(clocks)),
        cost_contract=next(iter(costs)),
        engine_contract=next(iter(engines)),
        prior_global_exposure_count=exposure.prior_global_exposure_count,
        original_family_end_global_exposure_count=original_end,
    )
    members = tuple(
        FixedHoldReplayMember(
            ordinal=member.ordinal,
            configuration_id=member.configuration_id,
            historical_reference_executable_id=(
                member.historical_reference_executable_id
            ),
            executable=executable,
            job_plan=build_fixed_hold_family_job_plan(
                definition=definition,
                artifact_namespace=_ATTEMPT_ARTIFACT_NAMESPACE,
                mission_id=spec.mission_id,
                study_id=spec.study_id,
                executable_id=executable.identity,
            ),
        )
        for member, executable in zip(
            family_authority.family.members,
            executables,
            strict=True,
        )
    )

    control_payload = study.payload.get("controlled_chassis")
    if not isinstance(control_payload, Mapping):
        raise RuntimeError("STU-0113 controlled chassis is absent")
    baseline_payload = control_payload.get("baseline_executable")
    if not isinstance(baseline_payload, Mapping):
        raise RuntimeError("STU-0113 baseline Executable is absent")
    baseline = executable_from_identity_payload(baseline_payload)
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=tuple(
            ResearchLayer(value)
            for value in control_payload.get("changed_domains", ())
        ),
        controlled_domains=tuple(
            ResearchLayer(value)
            for value in control_payload.get("controlled_domains", ())
        ),
        embedded_controlled_domains=tuple(
            ResearchLayer(value)
            for value in control_payload.get(
                "embedded_controlled_domains",
                (),
            )
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    if chassis.to_identity_payload() != dict(control_payload):
        raise RuntimeError("STU-0113 controlled chassis cannot be rehydrated")
    return members, chassis


def build_volatility_duration_replay_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    semantic_question_lineage: SemanticQuestionLineageProposal,
) -> FixedHoldReplayDesign:
    """Rehydrate only the exact already-registered STU-0113 attempt."""

    family_authority = require_volatility_duration_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )
    members, chassis = _rehydrate_attempt(
        writer,
        spec=spec,
        family_authority=family_authority,
    )
    target_historical_id = (
        family_authority.family.target_historical_executable_id
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_historical_id
    )
    if len(targets) != 1:
        raise RuntimeError("STU-0113 target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=spec,
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=chassis,
        historical_family_manifest=family_authority.family.manifest(),
        historical_family_authority_id=family_authority.identity,
        criterion_ids=criterion_ids,
        causal_question=STU0051_CAUSAL_QUESTION,
        mechanism_family=(
            "prospective-stu0051-volatility-duration-family-replay"
        ),
        why_now=(
            "the P0 correction queue requires a completed-bar replay of the "
            "locally executable family after its prior satisfaction was invalidated"
        ),
        stop_or_reopen_condition=(
            "stop after all four members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
        semantic_question_lineage=semantic_question_lineage,
    )


__all__ = [
    "STU0051_CAUSAL_QUESTION",
    "build_volatility_duration_replay_profile_design",
    "require_volatility_duration_family_authority",
]
