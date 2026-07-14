"""One-Job composite audit reanalysis for the selected P0 replay set.

The six legacy surfaces were selected after a much larger historical search.
They therefore remain child support, not six newly closed Studies and not a
prospectively registered concurrent family.  This module creates one immutable
composite Executable, one pre-Job validator-v2 plan, and one post-Job
measurement/result pair.  All p-values are descriptive post-selection
diagnostics within the replayed set; none creates candidate authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core import canonical as canonical_module
from axiom_rift.core import identity as identity_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import (
    ComponentSpec,
    ExecutableSpec,
    canonical_digest,
    canonical_identity_bytes,
)
from axiom_rift.operations import validation as operations_validation_module
from axiom_rift.research import (
    adjudication as adjudication_module,
    analog_state_family as analog_family_module,
    analog_state_trace as analog_trace_module,
    audit_integrity_proof as audit_proof_module,
    chassis as chassis_module,
    data as data_module,
    discovery as discovery_module,
    evidence_proofs as evidence_proof_module,
    governance as governance_module,
    implementation_closure as implementation_closure_module,
    p0_replay_adapters as adapter_module,
    p0_replay_inventory as replay_inventory_module,
    scientific_trace as scientific_trace_module,
    selection_inference as selection_module,
    validation_v2 as validation_v2_module,
)
from axiom_rift.research.adjudication import adjudicate_plan_measurement
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.evidence_proofs import (
    AUDIT_INTEGRITY_MODE,
    AUDIT_STATISTICAL_PROOF_KIND,
    AUDIT_SUPPORT_PROOF_KIND,
    P0_FOREST_SUPPORT_SCHEMA,
    build_proof_references,
    parse_proof_requirements,
    proof_requirements_for_modes,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.implementation_closure import (
    semantic_dependency_closure,
)
from axiom_rift.research.p0_replay_adapters import (
    AxisReplay,
    ForestReplayError,
    P0_AXIS_REPLAY_SCHEMA,
    P0_AXIS_SPECS,
    P0AxisSpec,
    forest_replay_adapter_dependency_graph,
    replay_p0_axes,
)
from axiom_rift.research.p0_replay_inventory import p0_replay_inventory_sha256
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    P0_REPLAY_EXECUTABLE_IDS,
    P0_REPLAY_FAMILY_ID,
    SELECTION_DAILY_PNL_SCHEMA,
    SelectionInferenceResult,
    infer_p0_simultaneous_forest,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan_v2,
)


P0_FOREST_REPLAY_SCHEMA = "p0_forest_composite_reanalysis.v2"
P0_REPLAY_STAGE = "discovery"
P0_COMPOSITE_AUTHORITY = "post_selection_descriptive_audit_only"
P0_REPLAY_CLAIMS = (
    "audit_reanalysis_integrity",
    "historical_post_selection_diagnostic",
    "within_replayed_set_descriptive_sensitivity",
)
P0_REPLAY_EVIDENCE_MODES = (
    AUDIT_INTEGRITY_MODE,
)
P0_PNL_ATTRIBUTION = {
    "daily_pnl": "decision_day",
    "monthly_drawdown": "exit_day",
    "timezone_basis": "source_timestamp_observed_coordinate",
}

P0_DAILY_PNL_OUTPUT = "local/cache/p0-forest/support/daily-pnl.json"
P0_INFERENCE_OUTPUT = "local/cache/p0-forest/support/inference.json"
P0_STATISTICAL_OUTPUT = (
    "local/cache/p0-forest/support/statistical-inference.json"
)
P0_COMPOSITE_SUPPORT_OUTPUT = (
    "local/cache/p0-forest/support/composite-support.json"
)
P0_COMPOSITE_PLAN_OUTPUT = "evidence/p0-forest/composite/validation-plan.json"
P0_COMPOSITE_MEASUREMENT_OUTPUT = "evidence/p0-forest/composite/measurement.json"
P0_COMPOSITE_RESULT_OUTPUT = "evidence/p0-forest/composite/result.json"
P0_COMPOSITE_SURFACE_OUTPUT = "local/cache/p0-forest/composite/surface.json"

_VALIDITY_METRICS = (
    "append_invariance_mismatch_count",
    "causality_violation_count",
    "nonfinite_metric_count",
    "prefix_invariance_mismatch_count",
    "unknown_cost_unresolved_signal_count",
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ForestReplayError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ForestReplayError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _positive_int(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise ForestReplayError(f"{name} must be a positive integer")
    return value


def _axis_output(spec: P0AxisSpec) -> str:
    return (
        "local/cache/p0-forest/support/"
        f"{spec.study_id.lower()}-axis-replay.json"
    )


def _module_source(module: object) -> Path:
    value = getattr(module, "__file__", None)
    if type(value) is not str:
        raise ForestReplayError("semantic dependency module has no source path")
    return Path(value)


def _merge_semantic_dependency_graphs(
    *graphs: Mapping[Path, tuple[Path, ...]],
) -> dict[Path, tuple[Path, ...]]:
    merged: dict[Path, list[Path]] = {}
    for graph in graphs:
        for node, dependencies in graph.items():
            bucket = merged.setdefault(node, [])
            for dependency in dependencies:
                if dependency not in bucket:
                    bucket.append(dependency)
    return {node: tuple(dependencies) for node, dependencies in merged.items()}


def forest_replay_dependency_graph() -> dict[Path, tuple[Path, ...]]:
    """Declare the executed project-source graph behind the forest Job.

    Edges bind delegated calculations and the scientific validator identity
    path.  They intentionally exclude package initializers, type-only imports,
    and legacy discovery runners that this replay never calls.
    """

    forest = Path(__file__)
    canonical = _module_source(canonical_module)
    identity = _module_source(identity_module)
    operations_validation = _module_source(operations_validation_module)
    adjudication = _module_source(adjudication_module)
    analog_family = _module_source(analog_family_module)
    analog_trace = _module_source(analog_trace_module)
    audit_proof = _module_source(audit_proof_module)
    chassis = _module_source(chassis_module)
    data = _module_source(data_module)
    discovery = _module_source(discovery_module)
    evidence_proof = _module_source(evidence_proof_module)
    governance = _module_source(governance_module)
    implementation_closure = _module_source(implementation_closure_module)
    adapter = _module_source(adapter_module)
    inventory = _module_source(replay_inventory_module)
    scientific_trace = _module_source(scientific_trace_module)
    selection = _module_source(selection_module)
    validation_v2 = _module_source(validation_v2_module)
    graph = {
        forest: (
            adjudication,
            adapter,
            canonical,
            chassis,
            discovery,
            evidence_proof,
            governance,
            identity,
            implementation_closure,
            inventory,
            selection,
            validation_v2,
        ),
        adjudication: (),
        analog_family: (data, discovery, identity, selection),
        analog_trace: (
            analog_family,
            canonical,
            discovery,
            identity,
            scientific_trace,
            selection,
        ),
        audit_proof: (identity, selection),
        canonical: (),
        chassis: (canonical, governance, identity),
        data: (identity,),
        discovery: (canonical, data, identity),
        evidence_proof: (audit_proof, canonical, scientific_trace),
        governance: (identity,),
        identity: (canonical,),
        implementation_closure: (),
        inventory: (canonical,),
        operations_validation: (canonical, identity),
        scientific_trace: (),
        selection: (adjudication, canonical, identity, inventory),
        validation_v2: (
            adjudication,
            analog_family,
            analog_trace,
            audit_proof,
            canonical,
            evidence_proof,
            identity,
            operations_validation,
            scientific_trace,
            selection,
        ),
    }
    return _merge_semantic_dependency_graphs(
        forest_replay_adapter_dependency_graph(),
        graph,
    )


def forest_replay_dependency_paths() -> tuple[Path, ...]:
    """Return the deterministic recursive forest implementation closure."""

    return semantic_dependency_closure(
        roots=(Path(__file__),),
        dependency_graph=forest_replay_dependency_graph(),
        source_root=Path(__file__).resolve().parents[2],
    )


def forest_replay_implementation_manifest() -> dict[str, Any]:
    dependencies = [
        {
            "module": path.stem,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for path in forest_replay_dependency_paths()
    ]
    if len({item["module"] for item in dependencies}) != len(dependencies):
        raise ForestReplayError("replay dependency module names collide")
    dependency_artifact_hashes = sorted(
        {item["sha256"] for item in dependencies}
    )
    return {
        "dependency_artifact_hashes": dependency_artifact_hashes,
        "dependencies": dependencies,
        "implementation_bundle_schema": "component_implementation_bundle.v1",
        "schema": "forest_replay_implementation.v2",
        "self_sha256": sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
    }


def forest_replay_implementation_artifact() -> bytes:
    """Return the exact content-addressable bytes behind Component identity."""

    return canonical_identity_bytes(
        domain="forest-replay-implementation",
        payload=forest_replay_implementation_manifest(),
    )


def forest_replay_implementation_identity() -> str:
    digest = canonical_digest(
        domain="forest-replay-implementation",
        payload=forest_replay_implementation_manifest(),
    )
    return f"forest-replay-implementation:{digest}"


def p0_replay_family_inventory() -> tuple[dict[str, str], ...]:
    inventory = tuple(spec.manifest() for spec in P0_AXIS_SPECS)
    if tuple(item["executable_id"] for item in inventory) != (
        P0_REPLAY_EXECUTABLE_IDS
    ):
        raise ForestReplayError("P0 family inventory differs from registered replay")
    return inventory


def p0_replay_family_inventory_hash() -> str:
    return canonical_digest(
        domain="p0-replay-family-inventory",
        payload={
            "authority": P0_COMPOSITE_AUTHORITY,
            "members": list(p0_replay_family_inventory()),
            "replayed_set_id": P0_REPLAY_FAMILY_ID,
            "schema": "p0_replay_family_inventory.v1",
        },
    )


def _analysis_plan_manifest(
    *,
    historical_context: HistoricalSearchContext,
    alpha_ppm: int,
    bootstrap_samples: int,
    block_lengths: tuple[int, ...],
    monte_carlo_confidence_ppm: int,
    base_seed: int,
) -> dict[str, Any]:
    if not isinstance(historical_context, HistoricalSearchContext):
        raise ForestReplayError("historical_context must be typed")
    _positive_int("bootstrap_samples", bootstrap_samples)
    if (
        type(block_lengths) is not tuple
        or not block_lengths
        or any(type(value) is not int or value < 1 for value in block_lengths)
        or block_lengths != tuple(sorted(set(block_lengths)))
    ):
        raise ForestReplayError("block_lengths must be sorted positive integers")
    if type(alpha_ppm) is not int or not 1 <= alpha_ppm <= 1_000_000:
        raise ForestReplayError("alpha_ppm is invalid")
    if (
        type(monte_carlo_confidence_ppm) is not int
        or not 500_000 < monte_carlo_confidence_ppm < 1_000_000
    ):
        raise ForestReplayError("monte_carlo_confidence_ppm is invalid")
    if type(base_seed) is not int or not 0 <= base_seed <= 2**63 - 1:
        raise ForestReplayError("base_seed is invalid")
    return {
        "authority": P0_COMPOSITE_AUTHORITY,
        "candidate_eligible": False,
        "decisive_value_kind": "none_post_selection_descriptive_only",
        "economic_composite": False,
        "family_inventory_hash": p0_replay_family_inventory_hash(),
        "inventory_artifact_sha256": p0_replay_inventory_sha256(),
        "historical_search_context": historical_context.manifest(),
        "implementation_identity": forest_replay_implementation_identity(),
        "ordered_legacy_members": list(p0_replay_family_inventory()),
        "replayed_set_id": P0_REPLAY_FAMILY_ID,
        "schema": "p0_composite_audit_reanalysis_plan.v1",
        "pnl_attribution": dict(P0_PNL_ATTRIBUTION),
        "statistics": {
            "alpha_ppm": alpha_ppm,
            "base_seed": base_seed,
            "block_lengths": list(block_lengths),
            "bootstrap_samples": bootstrap_samples,
            "monte_carlo_confidence_ppm": monte_carlo_confidence_ppm,
            "point_and_monte_carlo_upper_retained_separately": True,
        },
    }


def _implementation_digest(analysis_plan: Mapping[str, Any]) -> str:
    plan = dict(analysis_plan)
    implementation_identity = _ascii(
        "implementation_identity", plan["implementation_identity"]
    )
    implementation_digest = implementation_identity.rsplit(":", 1)[-1]
    _digest("implementation identity digest", implementation_digest)
    return implementation_digest


def _component_implementation(*, name: str, digest: str) -> str:
    _ascii("component implementation name", name)
    _digest("component implementation digest", digest)
    return (
        "axiom_rift.research.forest_replay."
        f"{name}@sha256:{digest}"
    )


def _composite_parameters(analysis_plan: Mapping[str, Any]) -> dict[str, Any]:
    plan = dict(analysis_plan)
    return {
        "authority": P0_COMPOSITE_AUTHORITY,
        "economic_composite": False,
        "family_inventory_hash": plan["family_inventory_hash"],
        "historical_search_context": plan["historical_search_context"],
        "pnl_attribution": plan["pnl_attribution"],
        "statistics": plan["statistics"],
    }


def _audit_executable(
    *,
    analysis_plan: Mapping[str, Any],
    display_name: str,
    components: tuple[ComponentSpec, ...],
) -> ExecutableSpec:
    plan = dict(analysis_plan)
    implementation_digest = _implementation_digest(plan)
    return ExecutableSpec(
        display_name=display_name,
        components=components,
        parameters=_composite_parameters(plan),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract="cost:legacy_child_native_and_stress_replay_bound_v1",
        engine_contract=(
            "engine:p0_audit_replay_v2:"
            f"implementation_{implementation_digest}:"
            f"inventory_{plan['family_inventory_hash']}"
        ),
    )


def _build_audit_baseline_executable(
    analysis_plan: Mapping[str, Any],
) -> ExecutableSpec:
    """Build the exact no-new-claim audit extraction and control path."""

    plan = dict(analysis_plan)
    digest = _implementation_digest(plan)
    feature = ComponentSpec(
        display_name="P0 legacy replay audit extraction",
        protocol="feature.audit_replay_extraction.v1",
        implementation=_component_implementation(
            name="audit_replay_extraction", digest=digest
        ),
        spec={
            "authority": P0_COMPOSITE_AUTHORITY,
            "family_inventory_hash": plan["family_inventory_hash"],
            "ordered_legacy_executable_ids": list(P0_REPLAY_EXECUTABLE_IDS),
            "output": "aligned_legacy_evaluation_and_daily_pnl_audit_records",
            "parameter_fields": [],
            "schema": "p0_audit_replay_extraction.v1",
        },
        semantic_dependencies=P0_REPLAY_EXECUTABLE_IDS,
    )
    label = ComponentSpec(
        display_name="P0 descriptive audit target",
        protocol="label.audit_reanalysis_target.v1",
        implementation=_component_implementation(
            name="audit_reanalysis_target", digest=digest
        ),
        spec={
            "candidate_eligible": False,
            "forward_claim_authority": "none",
            "parameter_fields": [],
            "schema": "p0_audit_reanalysis_target.v1",
            "target": "legacy_realized_daily_net_pnl_on_observed_development",
        },
        semantic_dependencies=(feature.identity,),
    )
    model = ComponentSpec(
        display_name="P0 deterministic audit identity projection",
        protocol="model.audit_identity_projection.v1",
        implementation=_component_implementation(
            name="audit_identity_projection", digest=digest
        ),
        spec={
            "fitting": "none",
            "mapping": "preserve_each_legacy_member_and_realized_target",
            "parameter_fields": [],
            "schema": "p0_audit_identity_projection.v1",
            "selection_or_ranking": "none",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    trade = ComponentSpec(
        display_name="P0 no-new-trade audit observation",
        protocol="trade.audit_observation_no_new_orders.v1",
        implementation=_component_implementation(
            name="audit_observation_no_new_orders", digest=digest
        ),
        spec={
            "new_entry_decisions": "forbidden",
            "parameter_fields": [],
            "schema": "p0_audit_observation_no_new_orders.v1",
            "trade_surface": "observe_legacy_realized_trade_outcomes_only",
        },
        semantic_dependencies=(model.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="P0 legacy lifecycle audit passthrough",
        protocol="lifecycle.audit_legacy_exit_passthrough.v1",
        implementation=_component_implementation(
            name="audit_legacy_exit_passthrough", digest=digest
        ),
        spec={
            "lifecycle_mutation": "none",
            "parameter_fields": [],
            "schema": "p0_audit_legacy_exit_passthrough.v1",
            "surface": "preserve_legacy_realized_entry_and_exit_timing",
        },
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="P0 no-new-order audit execution",
        protocol="execution.audit_no_new_order_replay.v1",
        implementation=_component_implementation(
            name="audit_no_new_order_replay", digest=digest
        ),
        spec={
            "cost_surface": "legacy_native_and_registered_stress_observation",
            "new_order_submission": "forbidden",
            "parameter_fields": [],
            "schema": "p0_audit_no_new_order_replay.v1",
        },
        semantic_dependencies=(lifecycle.identity,),
    )
    synthesis_control = ComponentSpec(
        display_name="P0 selected-set audit replay control",
        protocol="synthesis.audit_replay_control.v1",
        implementation=_component_implementation(
            name="audit_replay_control", digest=digest
        ),
        spec={
            "candidate_authority": "none",
            "inference": "none_control_surface",
            "parameter_fields": [],
            "schema": "p0_audit_replay_control.v1",
            "subject_count": 1,
        },
        semantic_dependencies=(execution.identity,),
    )
    return _audit_executable(
        analysis_plan=plan,
        display_name="P0 selected-set audit extraction control",
        components=(
            feature,
            label,
            model,
            trade,
            lifecycle,
            execution,
            synthesis_control,
        ),
    )


def _build_composite_executable(
    analysis_plan: Mapping[str, Any],
    *,
    baseline_executable: ExecutableSpec,
) -> ExecutableSpec:
    plan = dict(analysis_plan)
    expected_baseline = _build_audit_baseline_executable(plan)
    if (
        not isinstance(baseline_executable, ExecutableSpec)
        or baseline_executable.to_identity_payload()
        != expected_baseline.to_identity_payload()
    ):
        raise ForestReplayError("composite baseline differs from audit control")
    implementation_digest = _implementation_digest(plan)
    component = ComponentSpec(
        display_name="P0 post-selection composite audit reanalysis",
        protocol="synthesis.p0_post_selection_audit_reanalysis.v1",
        implementation=_component_implementation(
            name="composite_audit_reanalysis", digest=implementation_digest
        ),
        spec=plan,
        semantic_dependencies=(baseline_executable.components[-1].identity,),
    )
    return _audit_executable(
        analysis_plan=plan,
        display_name="P0 selected-set composite audit reanalysis",
        components=(*baseline_executable.components, component),
    )


def _criterion(
    *,
    criterion_id: str,
    claim_id: str,
    decision_role: str,
    evidence_mode: str,
    metric: str,
    operator: str,
    threshold: int,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "criterion_id": criterion_id,
        "decision_role": decision_role,
        "evidence_mode": evidence_mode,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
    }


def _composite_criteria() -> tuple[dict[str, Any], ...]:
    values = (
        ("A01-replayed-member-completeness", "audit_reanalysis_integrity", "component", AUDIT_INTEGRITY_MODE, "replayed_member_count", "eq", 6),
        ("C01-feature-prefix-invariance", "audit_reanalysis_integrity", "validity", AUDIT_INTEGRITY_MODE, "prefix_invariance_mismatch_count", "eq", 0),
        ("C02-decision-append-invariance", "audit_reanalysis_integrity", "validity", AUDIT_INTEGRITY_MODE, "append_invariance_mismatch_count", "eq", 0),
        ("C03-decision-time-causality", "audit_reanalysis_integrity", "validity", AUDIT_INTEGRITY_MODE, "causality_violation_count", "eq", 0),
        ("C04-resolved-cost", "audit_reanalysis_integrity", "validity", AUDIT_INTEGRITY_MODE, "unknown_cost_unresolved_signal_count", "eq", 0),
        ("C05-finite-metrics", "audit_reanalysis_integrity", "validity", AUDIT_INTEGRITY_MODE, "nonfinite_metric_count", "eq", 0),
        ("C06-not-economic-composite", "audit_reanalysis_integrity", "component", AUDIT_INTEGRITY_MODE, "economic_composite_count", "eq", 0),
        ("C07-decision-day-attribution", "audit_reanalysis_integrity", "component", AUDIT_INTEGRITY_MODE, "decision_day_attribution_count", "eq", 1),
        ("C08-explicit-calendar", "audit_reanalysis_integrity", "component", AUDIT_INTEGRITY_MODE, "calendar_date_count", "ge", 1),
        ("H01-history-context-bound", "historical_post_selection_diagnostic", "component", AUDIT_INTEGRITY_MODE, "historical_context_record_count", "eq", 1),
        ("H02-no-candidate-authority", "historical_post_selection_diagnostic", "component", AUDIT_INTEGRITY_MODE, "candidate_authority_count", "eq", 0),
        ("H03-point-values-retained", "historical_post_selection_diagnostic", "component", AUDIT_INTEGRITY_MODE, "raw_point_pvalue_record_count", "eq", 6),
        ("H04-mc-upper-values-retained", "historical_post_selection_diagnostic", "component", AUDIT_INTEGRITY_MODE, "raw_monte_carlo_upper_record_count", "eq", 6),
        ("S01-common-parent-artifacts", "within_replayed_set_descriptive_sensitivity", "component", AUDIT_INTEGRITY_MODE, "common_parent_artifact_count", "eq", 3),
        ("S02-family-inventory-completeness", "within_replayed_set_descriptive_sensitivity", "component", AUDIT_INTEGRITY_MODE, "family_inventory_member_count", "eq", 6),
        ("S03-bootstrap-seed-completeness", "within_replayed_set_descriptive_sensitivity", "component", AUDIT_INTEGRITY_MODE, "bootstrap_seed_record_count", "ge", 1),
        ("S04-durable-proof-completeness", "within_replayed_set_descriptive_sensitivity", "component", AUDIT_INTEGRITY_MODE, "durable_proof_artifact_count", "eq", 2),
    )
    return tuple(
        _criterion(
            criterion_id=value[0],
            claim_id=value[1],
            decision_role=value[2],
            evidence_mode=value[3],
            metric=value[4],
            operator=value[5],
            threshold=value[6],
        )
        for value in values
    )


@dataclass(frozen=True, slots=True)
class CompositeValidationPlan:
    mission_id: str
    historical_context: HistoricalSearchContext
    alpha_ppm: int
    bootstrap_samples: int
    block_lengths: tuple[int, ...]
    monte_carlo_confidence_ppm: int
    base_seed: int
    analysis_plan: Mapping[str, Any]
    baseline_executable: ExecutableSpec
    executable: ExecutableSpec
    plan: Mapping[str, Any]

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        expected_analysis = _analysis_plan_manifest(
            historical_context=self.historical_context,
            alpha_ppm=self.alpha_ppm,
            bootstrap_samples=self.bootstrap_samples,
            block_lengths=self.block_lengths,
            monte_carlo_confidence_ppm=self.monte_carlo_confidence_ppm,
            base_seed=self.base_seed,
        )
        if dict(self.analysis_plan) != expected_analysis:
            raise ForestReplayError("composite analysis plan drifted")
        expected_baseline = _build_audit_baseline_executable(expected_analysis)
        if (
            not isinstance(self.baseline_executable, ExecutableSpec)
            or self.baseline_executable.to_identity_payload()
            != expected_baseline.to_identity_payload()
        ):
            raise ForestReplayError("composite baseline differs from analysis plan")
        expected_executable = _build_composite_executable(
            expected_analysis,
            baseline_executable=expected_baseline,
        )
        if (
            not isinstance(self.executable, ExecutableSpec)
            or self.executable.to_identity_payload()
            != expected_executable.to_identity_payload()
        ):
            raise ForestReplayError("composite Executable differs from analysis plan")
        expected_plan = _build_v2_plan(
            mission_id=self.mission_id,
            executable_id=self.executable.identity,
        )
        if dict(self.plan) != expected_plan:
            raise ForestReplayError("composite validator plan drifted")
        canonical_bytes(dict(self.plan))
        self.controlled_chassis()

    @property
    def executable_id(self) -> str:
        return self.executable.identity

    @property
    def plan_hash(self) -> str:
        return sha256(canonical_bytes(dict(self.plan))).hexdigest()

    def controlled_chassis(self) -> ControlledStudyChassis:
        """Return and verify the strict baseline-to-reanalysis Study chassis."""

        chassis = ControlledStudyChassis(
            baseline_executable=self.baseline_executable,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=(
                ResearchLayer.LABEL,
                ResearchLayer.MODEL,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.EXECUTION,
            ),
            embedded_controlled_domains=(ResearchLayer.FEATURE,),
            architecture=ArchitectureChassisSpec.from_executable(
                self.baseline_executable
            ),
        )
        validate_controlled_executable(chassis.to_identity_payload(), self.executable)
        return chassis

    def scientific_binding(self, *, validator_id: str) -> dict[str, Any]:
        _ascii("validator_id", validator_id)
        return {
            "evidence_depth": P0_REPLAY_STAGE,
            "evidence_modes": list(P0_REPLAY_EVIDENCE_MODES),
            "planned_claims": list(P0_REPLAY_CLAIMS),
            "result_manifest_output": P0_COMPOSITE_RESULT_OUTPUT,
            "validation_plan_hash": self.plan_hash,
            "validator_id": validator_id,
        }

    def expected_outputs(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    P0_DAILY_PNL_OUTPUT,
                    P0_INFERENCE_OUTPUT,
                    P0_STATISTICAL_OUTPUT,
                    P0_COMPOSITE_SUPPORT_OUTPUT,
                    P0_COMPOSITE_PLAN_OUTPUT,
                    P0_COMPOSITE_MEASUREMENT_OUTPUT,
                    P0_COMPOSITE_RESULT_OUTPUT,
                    P0_COMPOSITE_SURFACE_OUTPUT,
                    *(_axis_output(spec) for spec in P0_AXIS_SPECS),
                }
            )
        )

    def output_classes(self) -> dict[str, str]:
        durable = {
            P0_COMPOSITE_SUPPORT_OUTPUT,
            P0_COMPOSITE_PLAN_OUTPUT,
            P0_COMPOSITE_MEASUREMENT_OUTPUT,
            P0_COMPOSITE_RESULT_OUTPUT,
            P0_STATISTICAL_OUTPUT,
        }
        return {
            path: (
                "durable_evidence" if path in durable else "reproducible_cache"
            )
            for path in self.expected_outputs()
        }

    def job_input_hashes(self) -> tuple[str, ...]:
        values = (
            self.plan_hash,
            DATASET_SHA256,
            ROLLING_SPLIT_SHA256,
            p0_replay_inventory_sha256(),
            *(spec.legacy_evaluation_sha256 for spec in P0_AXIS_SPECS),
        )
        return tuple(sorted(set(values)))


def _build_v2_plan(*, mission_id: str, executable_id: str) -> dict[str, object]:
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": [],
        "promotion_criterion_ids": [],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    proof_requirements = proof_requirements_for_modes(
        evidence_modes=P0_REPLAY_EVIDENCE_MODES,
        output_names={
            AUDIT_SUPPORT_PROOF_KIND: P0_COMPOSITE_SUPPORT_OUTPUT,
            AUDIT_STATISTICAL_PROOF_KIND: P0_STATISTICAL_OUTPUT,
        },
    )
    return build_validation_plan_v2(
        mission_id=mission_id,
        executable_id=executable_id,
        evidence_depth=P0_REPLAY_STAGE,
        planned_claims=P0_REPLAY_CLAIMS,
        evidence_modes=P0_REPLAY_EVIDENCE_MODES,
        criteria=_composite_criteria(),
        adjudication_profile=profile,
        proof_requirements=proof_requirements,
        candidate_eligible_on_pass=False,
    )


def build_p0_composite_validation_plan(
    *,
    mission_id: str,
    historical_context: HistoricalSearchContext,
    bootstrap_samples: int = selection_module.DEFAULT_BOOTSTRAP_SAMPLES,
    block_lengths: tuple[int, ...] = selection_module.DEFAULT_BLOCK_LENGTHS,
    alpha_ppm: int = selection_module.DEFAULT_ALPHA_PPM,
    monte_carlo_confidence_ppm: int = (
        selection_module.DEFAULT_MONTE_CARLO_CONFIDENCE_PPM
    ),
    base_seed: int = selection_module.DEFAULT_BASE_SEED,
) -> CompositeValidationPlan:
    """Build the composite Executable and validator plan before a Job starts."""

    analysis_plan = _analysis_plan_manifest(
        historical_context=historical_context,
        alpha_ppm=alpha_ppm,
        bootstrap_samples=bootstrap_samples,
        block_lengths=block_lengths,
        monte_carlo_confidence_ppm=monte_carlo_confidence_ppm,
        base_seed=base_seed,
    )
    baseline_executable = _build_audit_baseline_executable(analysis_plan)
    executable = _build_composite_executable(
        analysis_plan,
        baseline_executable=baseline_executable,
    )
    plan = _build_v2_plan(
        mission_id=mission_id,
        executable_id=executable.identity,
    )
    return CompositeValidationPlan(
        mission_id=mission_id,
        historical_context=historical_context,
        alpha_ppm=alpha_ppm,
        bootstrap_samples=bootstrap_samples,
        block_lengths=block_lengths,
        monte_carlo_confidence_ppm=monte_carlo_confidence_ppm,
        base_seed=base_seed,
        analysis_plan=analysis_plan,
        baseline_executable=baseline_executable,
        executable=executable,
        plan=plan,
    )


def _daily_pnl_payload(axes: tuple[AxisReplay, ...]) -> dict[str, Any]:
    if tuple(axis.spec.executable_id for axis in axes) != P0_REPLAY_EXECUTABLE_IDS:
        raise ForestReplayError("replay axes differ from exact P0 inventory")
    calendar = [day for day, _ in axes[0].daily_pnl]
    series: list[dict[str, Any]] = []
    for axis in axes:
        if [day for day, _ in axis.daily_pnl] != calendar:
            raise ForestReplayError("P0 axes do not share an exact calendar")
        series.append(
            {
                "daily_pnl_micropoints": [value for _, value in axis.daily_pnl],
                "hypothesis_id": axis.spec.executable_id,
            }
        )
    return {
        "calendar": calendar,
        "schema": SELECTION_DAILY_PNL_SCHEMA,
        "series": series,
    }


def _verify_replay_result(
    *,
    replay_plan: CompositeValidationPlan,
    axes: tuple[AxisReplay, ...],
    inference: SelectionInferenceResult,
) -> None:
    if (
        replay_plan.analysis_plan.get("implementation_identity")
        != forest_replay_implementation_identity()
        or replay_plan.analysis_plan.get("inventory_artifact_sha256")
        != p0_replay_inventory_sha256()
    ):
        raise ForestReplayError(
            "composite implementation or inventory bytes changed after planning"
        )
    expected_baseline = _build_audit_baseline_executable(
        replay_plan.analysis_plan
    )
    if (
        replay_plan.baseline_executable.to_identity_payload()
        != expected_baseline.to_identity_payload()
    ):
        raise ForestReplayError("audit baseline no longer matches current bytes")
    expected_executable = _build_composite_executable(
        replay_plan.analysis_plan,
        baseline_executable=expected_baseline,
    )
    if (
        replay_plan.executable.to_identity_payload()
        != expected_executable.to_identity_payload()
    ):
        raise ForestReplayError("composite Executable no longer matches current bytes")
    replay_plan.controlled_chassis()
    if tuple(axis.spec.executable_id for axis in axes) != P0_REPLAY_EXECUTABLE_IDS:
        raise ForestReplayError("replay axes differ from exact P0 inventory")
    plan = inference.plan
    if (
        plan.family_id != P0_REPLAY_FAMILY_ID
        or plan.stage != P0_REPLAY_STAGE
        or plan.hypothesis_ids != P0_REPLAY_EXECUTABLE_IDS
        or plan.alpha_ppm != replay_plan.alpha_ppm
        or plan.bootstrap_samples != replay_plan.bootstrap_samples
        or plan.block_lengths != replay_plan.block_lengths
        or plan.monte_carlo_confidence_ppm
        != replay_plan.monte_carlo_confidence_ppm
        or plan.base_seed != replay_plan.base_seed
        or inference.historical_context != replay_plan.historical_context
    ):
        raise ForestReplayError("inference differs from composite preregistration")
    daily = _daily_pnl_payload(axes)
    identity = canonical_digest(domain="selection-daily-pnl", payload=daily)
    if inference.daily_pnl_identity != f"daily-pnl:{identity}":
        raise ForestReplayError("daily PnL artifact differs from inference input")


def _member_diagnostic(
    *, axis: AxisReplay, inference: SelectionInferenceResult, ordinal: int
) -> dict[str, Any]:
    result = inference.hypothesis(axis.spec.executable_id)
    return {
        "decisive_value_kind": "none_post_selection_descriptive_only",
        "legacy_executable_id": axis.spec.executable_id,
        "legacy_study_id": axis.spec.study_id,
        "ordinal": ordinal,
        "raw": {
            "monte_carlo_upper_pvalue_ppm": (
                result.raw_monte_carlo_upper_pvalue_ppm
            ),
            "point_pvalue_ppm": result.raw_point_pvalue_ppm,
        },
        "romano_wolf_within_replayed_set": {
            "monte_carlo_upper_pvalue_ppm": (
                result.romano_wolf_stepdown_monte_carlo_upper_pvalue_ppm
            ),
            "point_pvalue_ppm": result.romano_wolf_stepdown_point_pvalue_ppm,
        },
        "synchronized_max_within_replayed_set": {
            "monte_carlo_upper_pvalue_ppm": (
                result.synchronized_max_monte_carlo_upper_pvalue_ppm
            ),
            "point_pvalue_ppm": result.synchronized_max_point_pvalue_ppm,
        },
        "within_replayed_set_bonferroni": {
            "monte_carlo_upper_pvalue_ppm": (
                result.bonferroni_monte_carlo_upper_pvalue_ppm
            ),
            "point_pvalue_ppm": result.bonferroni_point_pvalue_ppm,
        },
    }


def _support_manifest(
    *,
    replay_plan: CompositeValidationPlan,
    job_id: str,
    job_hash: str,
    axes: tuple[AxisReplay, ...],
    inference: SelectionInferenceResult,
) -> dict[str, Any]:
    _ascii("job_id", job_id)
    _digest("job_hash", job_hash)
    daily = _daily_pnl_payload(axes)
    daily_bytes = canonical_bytes(daily)
    inference_bytes = inference.manifest_bytes()
    statistical_bytes = canonical_bytes(inference.statistical_manifest())
    members = [
        {
            "adapter": axis.spec.adapter,
            "axis_replay_sha256": sha256(
                canonical_bytes(axis.manifest())
            ).hexdigest(),
            "configuration_id": axis.spec.configuration_id,
            "descriptive_metrics": dict(axis.evaluation["metrics"]),
            "legacy_evaluation_sha256": axis.spec.legacy_evaluation_sha256,
            "legacy_executable_id": axis.spec.executable_id,
            "legacy_study_id": axis.spec.study_id,
            "ordinal": ordinal,
        }
        for ordinal, axis in enumerate(axes, start=1)
    ]
    return {
        "analysis_plan": dict(replay_plan.analysis_plan),
        "authority": P0_COMPOSITE_AUTHORITY,
        "calendar": {
            "calendar_identity": inference.calendar_identity,
            "daily_pnl_identity": inference.daily_pnl_identity,
            "date_count": inference.date_count,
            "first_date": inference.first_date,
            "last_date": inference.last_date,
            "missing_day_policy": "exact_shared_calendar_no_implicit_zero_fill",
        },
        "candidate_authority": "none",
        "claim_limits": [
            "child_surfaces_are_support_not_new_study_closes",
            "historical_search_context_is_descriptive_only",
            "observed_development_reanalysis_is_not_confirmation",
            "replay_does_not_create_or_promote_a_candidate",
            "within_replayed_set_familywise_values_are_not_selection_correction",
        ],
        "common_parent_artifacts": {
            "daily_pnl": {
                "output_path": P0_DAILY_PNL_OUTPUT,
                "sha256": sha256(daily_bytes).hexdigest(),
            },
            "inference": {
                "output_path": P0_INFERENCE_OUTPUT,
                "sha256": sha256(inference_bytes).hexdigest(),
            },
            "statistical_inference": {
                "output_path": P0_STATISTICAL_OUTPUT,
                "sha256": sha256(statistical_bytes).hexdigest(),
                "statistical_identity": inference.statistical_identity,
            },
        },
        "baseline_executable_id": replay_plan.baseline_executable.identity,
        "composite_executable_id": replay_plan.executable_id,
        "dataset_sha256": DATASET_SHA256,
        "economic_composite": False,
        "family_inventory_hash": p0_replay_family_inventory_hash(),
        "inventory_artifact_sha256": p0_replay_inventory_sha256(),
        "historical_search_context": inference.historical_context.manifest(),
        "implementation": forest_replay_implementation_manifest(),
        "job_hash": job_hash,
        "job_id": job_id,
        "members": members,
        "mission_id": replay_plan.mission_id,
        "pnl_attribution": dict(P0_PNL_ATTRIBUTION),
        "post_selection_diagnostics": [
            _member_diagnostic(axis=axis, inference=inference, ordinal=ordinal)
            for ordinal, axis in enumerate(axes, start=1)
        ],
        "replayed_set_id": P0_REPLAY_FAMILY_ID,
        "schema": P0_FOREST_SUPPORT_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "statistical_plan": {
            "alpha_ppm": inference.plan.alpha_ppm,
            "base_seed": inference.plan.base_seed,
            "block_lengths": list(inference.plan.block_lengths),
            "bootstrap_samples": inference.plan.bootstrap_samples,
            "decisive_value_kind": "none_post_selection_descriptive_only",
            "monte_carlo_confidence_ppm": (
                inference.plan.monte_carlo_confidence_ppm
            ),
            "ordered_member_ids": list(inference.plan.hypothesis_ids),
            "point_and_monte_carlo_upper_retained_separately": True,
            "seeds": [seed.manifest() for seed in inference.seeds],
        },
    }


def _measurement_metrics(
    *, support: Mapping[str, Any], statistical: Mapping[str, Any]
) -> dict[str, dict[str, int]]:
    members = tuple(support["members"])
    hypotheses = tuple(statistical["hypotheses"])
    validity = {
        metric: sum(
            int(member["descriptive_metrics"][metric]) for member in members
        )
        for metric in _VALIDITY_METRICS
    }
    diagnostic: dict[str, int] = {
        "candidate_authority_count": 0,
        "historical_context_record_count": 1,
        "raw_monte_carlo_upper_record_count": sum(
            int("monte_carlo_upper_pvalue_ppm" in item["raw"])
            for item in hypotheses
        ),
        "raw_point_pvalue_record_count": sum(
            int("point_pvalue_ppm" in item["raw"])
            for item in hypotheses
        ),
    }
    return {
        "audit_reanalysis_integrity": {
            "calendar_date_count": int(support["calendar"]["date_count"]),
            "decision_day_attribution_count": int(
                support["pnl_attribution"]["daily_pnl"] == "decision_day"
            ),
            "economic_composite_count": int(support["economic_composite"]),
            "replayed_member_count": len(members),
            **validity,
        },
        "historical_post_selection_diagnostic": diagnostic,
        "within_replayed_set_descriptive_sensitivity": {
            "bootstrap_seed_record_count": len(statistical["seeds"]),
            "common_parent_artifact_count": len(
                support["common_parent_artifacts"]
            ),
            "durable_proof_artifact_count": 2,
            "family_inventory_member_count": len(members),
        },
    }


@dataclass(frozen=True, slots=True)
class CompositeValidationArtifacts:
    replay_plan: CompositeValidationPlan
    support: Mapping[str, Any]
    statistical: Mapping[str, Any]
    measurement: Mapping[str, Any]
    result: Mapping[str, Any]
    adjudication_state: str

    def __post_init__(self) -> None:
        for value in (
            self.replay_plan.plan,
            self.support,
            self.statistical,
            self.measurement,
            self.result,
        ):
            canonical_bytes(dict(value))
        _ascii("adjudication_state", self.adjudication_state)

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        return sha256(canonical_bytes(dict(value))).hexdigest()

    @property
    def executable_id(self) -> str:
        return self.replay_plan.executable_id

    @property
    def plan(self) -> Mapping[str, Any]:
        return self.replay_plan.plan

    @property
    def plan_hash(self) -> str:
        return self.replay_plan.plan_hash

    @property
    def measurement_hash(self) -> str:
        return self._hash(self.measurement)

    @property
    def result_hash(self) -> str:
        return self._hash(self.result)

    def binding(self, *, validator_id: str) -> dict[str, Any]:
        return self.replay_plan.scientific_binding(validator_id=validator_id)


def _build_validation_artifacts(
    *,
    replay_plan: CompositeValidationPlan,
    job_id: str,
    job_hash: str,
    axes: tuple[AxisReplay, ...],
    inference: SelectionInferenceResult,
) -> CompositeValidationArtifacts:
    _ascii("job_id", job_id)
    _digest("job_hash", job_hash)
    statistical = inference.statistical_manifest()
    support = _support_manifest(
        replay_plan=replay_plan,
        job_id=job_id,
        job_hash=job_hash,
        axes=axes,
        inference=inference,
    )
    proof_requirements = parse_proof_requirements(
        replay_plan.plan["proof_requirements"],
        evidence_modes=P0_REPLAY_EVIDENCE_MODES,
    )
    proof_references = build_proof_references(
        requirements=proof_requirements,
        artifact_hashes={
            P0_COMPOSITE_SUPPORT_OUTPUT: sha256(
                canonical_bytes(support)
            ).hexdigest(),
            P0_STATISTICAL_OUTPUT: sha256(
                canonical_bytes(statistical)
            ).hexdigest(),
        },
    )
    measurement = {
        "evidence_depth": P0_REPLAY_STAGE,
        "evidence_modes": list(P0_REPLAY_EVIDENCE_MODES),
        "executable_id": replay_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": _measurement_metrics(
            support=support,
            statistical=statistical,
        ),
        "mission_id": replay_plan.mission_id,
        "multiplicity": [],
        "proofs": list(proof_references),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    measurement_hash = sha256(canonical_bytes(measurement)).hexdigest()
    result = {
        "evidence_depth": P0_REPLAY_STAGE,
        "executable_id": replay_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": replay_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": measurement_hash,
            }
            for claim_id in P0_REPLAY_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    adjudication = adjudicate_plan_measurement(replay_plan.plan, measurement)
    return CompositeValidationArtifacts(
        replay_plan=replay_plan,
        support=support,
        statistical=statistical,
        measurement=measurement,
        result=result,
        adjudication_state=adjudication.state,
    )


@dataclass(frozen=True, slots=True)
class ForestReplayBundle:
    replay_plan: CompositeValidationPlan
    job_id: str
    job_hash: str
    axes: tuple[AxisReplay, ...]
    inference: SelectionInferenceResult
    validation_artifacts: CompositeValidationArtifacts

    def __post_init__(self) -> None:
        _ascii("job_id", self.job_id)
        _digest("job_hash", self.job_hash)
        _verify_replay_result(
            replay_plan=self.replay_plan,
            axes=self.axes,
            inference=self.inference,
        )
        if self.validation_artifacts.replay_plan != self.replay_plan:
            raise ForestReplayError("validator artifacts bind another replay plan")
        if (
            self.validation_artifacts.measurement["job_id"] != self.job_id
            or self.validation_artifacts.measurement["job_hash"] != self.job_hash
        ):
            raise ForestReplayError("validator artifacts bind another Job")

    @property
    def mission_id(self) -> str:
        return self.replay_plan.mission_id

    @property
    def executable_id(self) -> str:
        return self.replay_plan.executable_id

    def daily_pnl_artifact(self) -> dict[str, Any]:
        return _daily_pnl_payload(self.axes)

    def support_manifest(self) -> dict[str, Any]:
        return dict(self.validation_artifacts.support)

    def statistical_manifest(self) -> dict[str, Any]:
        return dict(self.validation_artifacts.statistical)

    def surface_manifest(self) -> dict[str, Any]:
        support_bytes = canonical_bytes(self.support_manifest())
        return {
            "authority": P0_COMPOSITE_AUTHORITY,
            "candidate_authority": "none",
            "baseline_executable_id": (
                self.replay_plan.baseline_executable.identity
            ),
            "composite_executable_id": self.executable_id,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "mission_id": self.mission_id,
            "one_scientific_subject": True,
            "schema": P0_FOREST_REPLAY_SCHEMA,
            "support_sha256": sha256(support_bytes).hexdigest(),
            "validation": {
                "adjudication_state": (
                    self.validation_artifacts.adjudication_state
                ),
                "measurement_output": P0_COMPOSITE_MEASUREMENT_OUTPUT,
                "measurement_sha256": (
                    self.validation_artifacts.measurement_hash
                ),
                "plan_output": P0_COMPOSITE_PLAN_OUTPUT,
                "plan_sha256": self.validation_artifacts.plan_hash,
                "result_output": P0_COMPOSITE_RESULT_OUTPUT,
                "result_sha256": self.validation_artifacts.result_hash,
            },
        }

    def artifact_bytes(self) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {
            P0_DAILY_PNL_OUTPUT: canonical_bytes(self.daily_pnl_artifact()),
            P0_INFERENCE_OUTPUT: self.inference.manifest_bytes(),
            P0_STATISTICAL_OUTPUT: canonical_bytes(
                self.statistical_manifest()
            ),
            P0_COMPOSITE_SUPPORT_OUTPUT: canonical_bytes(
                self.support_manifest()
            ),
            P0_COMPOSITE_PLAN_OUTPUT: canonical_bytes(
                dict(self.validation_artifacts.plan)
            ),
            P0_COMPOSITE_MEASUREMENT_OUTPUT: canonical_bytes(
                dict(self.validation_artifacts.measurement)
            ),
            P0_COMPOSITE_RESULT_OUTPUT: canonical_bytes(
                dict(self.validation_artifacts.result)
            ),
        }
        for axis in self.axes:
            payloads[_axis_output(axis.spec)] = canonical_bytes(axis.manifest())
        payloads[P0_COMPOSITE_SURFACE_OUTPUT] = canonical_bytes(
            self.surface_manifest()
        )
        return dict(sorted(payloads.items()))

    def output_classes(self) -> dict[str, str]:
        paths = tuple(self.artifact_bytes())
        if paths != self.replay_plan.expected_outputs():
            raise ForestReplayError("Job outputs differ from preregistration")
        return self.replay_plan.output_classes()

    def output_hashes(self) -> dict[str, str]:
        return {
            path: sha256(content).hexdigest()
            for path, content in self.artifact_bytes().items()
        }

    def write_artifacts(self, output_root: str | Path) -> dict[str, str]:
        """Idempotently materialize the exact one-Job output surface."""

        root = Path(output_root).resolve()
        hashes: dict[str, str] = {}
        for relative_path, content in self.artifact_bytes().items():
            path = (root / relative_path).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ForestReplayError("artifact path escapes output root") from exc
            if path.exists():
                if path.read_bytes() != content:
                    raise ForestReplayError(
                        "existing forest replay artifact has different bytes"
                    )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            hashes[relative_path] = sha256(content).hexdigest()
        return hashes


def build_p0_forest_bundle(
    *,
    replay_plan: CompositeValidationPlan,
    job_id: str,
    job_hash: str,
    axes: tuple[AxisReplay, ...],
    inference: SelectionInferenceResult,
) -> ForestReplayBundle:
    """Build one Job-bound validation bundle after the Job is known."""

    _verify_replay_result(
        replay_plan=replay_plan,
        axes=axes,
        inference=inference,
    )
    artifacts = _build_validation_artifacts(
        replay_plan=replay_plan,
        job_id=job_id,
        job_hash=job_hash,
        axes=axes,
        inference=inference,
    )
    return ForestReplayBundle(
        replay_plan=replay_plan,
        job_id=job_id,
        job_hash=job_hash,
        axes=axes,
        inference=inference,
        validation_artifacts=artifacts,
    )


def compute_p0_forest_replay(
    repository_root: str | Path,
    *,
    replay_plan: CompositeValidationPlan,
    job_id: str,
    job_hash: str,
) -> ForestReplayBundle:
    """Execute the preregistered composite replay inside its one Job."""

    axes = replay_p0_axes(repository_root)
    inference = infer_p0_simultaneous_forest(
        {
            axis.spec.executable_id: axis.daily_pnl_mapping() for axis in axes
        },
        historical_context=replay_plan.historical_context,
        alpha_ppm=replay_plan.alpha_ppm,
        bootstrap_samples=replay_plan.bootstrap_samples,
        block_lengths=replay_plan.block_lengths,
        monte_carlo_confidence_ppm=replay_plan.monte_carlo_confidence_ppm,
        base_seed=replay_plan.base_seed,
    )
    return build_p0_forest_bundle(
        replay_plan=replay_plan,
        job_id=job_id,
        job_hash=job_hash,
        axes=axes,
        inference=inference,
    )


__all__ = [
    "AxisReplay",
    "CompositeValidationArtifacts",
    "CompositeValidationPlan",
    "ForestReplayBundle",
    "ForestReplayError",
    "P0_AXIS_REPLAY_SCHEMA",
    "P0_AXIS_SPECS",
    "P0_COMPOSITE_AUTHORITY",
    "P0_COMPOSITE_MEASUREMENT_OUTPUT",
    "P0_COMPOSITE_PLAN_OUTPUT",
    "P0_COMPOSITE_RESULT_OUTPUT",
    "P0_COMPOSITE_SUPPORT_OUTPUT",
    "P0_FOREST_REPLAY_SCHEMA",
    "P0_FOREST_SUPPORT_SCHEMA",
    "P0_PNL_ATTRIBUTION",
    "P0_REPLAY_CLAIMS",
    "P0_REPLAY_EVIDENCE_MODES",
    "P0_STATISTICAL_OUTPUT",
    "P0AxisSpec",
    "build_p0_composite_validation_plan",
    "build_p0_forest_bundle",
    "compute_p0_forest_replay",
    "forest_replay_dependency_graph",
    "forest_replay_dependency_paths",
    "forest_replay_implementation_artifact",
    "forest_replay_implementation_identity",
    "forest_replay_implementation_manifest",
    "p0_replay_family_inventory",
    "p0_replay_family_inventory_hash",
    "replay_p0_axes",
]
