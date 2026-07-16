"""Withdraw the unstarted STU-0051 duplicate-mechanism bridge Decision.

The default mode is read only.  ``--apply`` materializes the exact rejected
snapshot and audit evidence, then records one additive Writer withdrawal.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    _projection_payloads,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.decision_withdrawal import (  # noqa: E402
    PortfolioDecisionWithdrawalReason,
    PortfolioStructuralDecisionWithdrawalManifest,
)
from axiom_rift.research.portfolio import (  # noqa: E402
    PortfolioAxis,
    PortfolioSnapshot,
    ResearchLayer,
)
from axiom_rift.research.portfolio_projection import (  # noqa: E402
    component_surface_registry,
    portfolio_axes_from_projection,
)
from axiom_rift.research.volatility_duration_replay import (  # noqa: E402
    volatility_duration_replay_controlled_chassis,
)
from axiom_rift.research.volatility_duration_replay_profile import (  # noqa: E402
    STU0051_CAUSAL_QUESTION,
    require_volatility_duration_family_authority,
    require_volatility_duration_historical_context,
    volatility_duration_replay_members,
)
from run_p0_stu0051_completed_bar_replay import (  # noqa: E402
    EXPECTED_ARCHITECTURE_FAMILY,
    HISTORICAL_CONTEXT_COUNT,
    HISTORICAL_FAMILY_AUTHORITY_ID,
    mission_spec,
    semantic_question_lineage,
)


DECISION_ID = (
    "decision:"
    "e7426fddeb1faae73ddaa947cba33ce30057921fd68fbd5fbd3f232382d9f13c"
)
DECISION_OPERATION_ID = "p0-stu0051-completed-bar-replay-v1-bridge-decision"
DECISION_AUTHORITY_REVISION = 5393
DECISION_AUTHORITY_EVENT_ID = (
    "5ab33e295bc99830c7980af20d6660d8ee9003ae8bfafd359f7a84aead1749e0"
)
BASE_SNAPSHOT_ID = (
    "portfolio:"
    "46f69a1437c5cffb133ceb1e90213c87ba8de918c7d3405bf0b43deeaf566e9c"
)
TARGET_AXIS_ID = "axis-stu0051-volatility-duration-replay-bridge"
TARGET_AXIS_IDENTITY = (
    "axis:"
    "5d0a3d0be812333675de2eeae04f6102eccd7388e03e3918756eb28fe7c55571"
)
PROPOSED_AXIS_ID = "axis-stu0051-completed-bar-replay-correction-v1"
MECHANISM_FAMILY = "prospective-stu0051-volatility-duration-family-replay"
WHY_NOW = (
    "the P0 correction queue requires a completed-bar replay of the locally "
    "executable family after its prior satisfaction was invalidated"
)
STOP_OR_REOPEN = (
    "stop after all four members; reopen only under a typed replay resume "
    "condition or registered development material"
)
OPPORTUNITY_COST_BASIS = (
    "retain the complete forest and spend one Batch on exact replay"
)
FINDING_ID = "P0-STU0051-STRUCTURAL-BRIDGE-001"
WITHDRAWAL_OPERATION_ID = "p0-stu0051-invalid-bridge-withdrawal-v1"
EXPECTED_PROPOSED_AXIS_IDENTITY = (
    "axis:"
    "71be55d1cfbe5ddb21fb7e76ae14cfaf708f0b29dd63bab38303ec68d921fd0e"
)
EXPECTED_PROPOSED_SNAPSHOT_ID = (
    "portfolio:"
    "fbcda2fdf91cfbbb6e0eb00e21783b09e0a415fa3ec933a48328177924c2afe8"
)
EXPECTED_PROPOSED_SNAPSHOT_ARTIFACT_HASH = (
    "4e721f70fe26a244fa823524f3c2405a146982dd8d8b4f73f5846bd818d5bc13"
)
EXPECTED_REPORT_ARTIFACT_HASH = (
    "ee77440706b8d5813ba6906dc4f2de79a8fa0f8b5e3c75cd68b91e8afce3bd2f"
)
EXPECTED_MANIFEST_ARTIFACT_HASH = (
    "834e7f3fdc711f98cb726d63124739cbc268b60d370f99f5c377b3a063498bee"
)


def _digest(document: bytes) -> str:
    return sha256(document).hexdigest()


def _require_current_boundary(
    control: Mapping[str, Any],
    *,
    decision_payload: Mapping[str, Any],
    decision_operation: Any,
) -> None:
    next_action = control.get("next_action")
    if (
        control.get("revision") != DECISION_AUTHORITY_REVISION
        or control.get("heads", {}).get("journal", {}).get("event_id")
        != DECISION_AUTHORITY_EVENT_ID
        or not isinstance(next_action, Mapping)
        or next_action.get("kind") != "record_portfolio_snapshot"
        or next_action.get("action") != "new_mechanism"
        or next_action.get("decision_id") != DECISION_ID
        or next_action.get("portfolio_snapshot_id") != BASE_SNAPSHOT_ID
        or next_action.get("target_id") != TARGET_AXIS_ID
        or next_action.get("target_axis_identity") != TARGET_AXIS_IDENTITY
        or decision_payload.get("portfolio_snapshot_id") != BASE_SNAPSHOT_ID
        or decision_payload.get("target_axis_identity") != TARGET_AXIS_IDENTITY
        or decision_operation.status != "success"
        or decision_operation.authority_sequence
        != DECISION_AUTHORITY_REVISION
        or decision_operation.authority_event_id
        != DECISION_AUTHORITY_EVENT_ID
    ):
        raise RuntimeError("STU-0051 invalid bridge authority boundary drifted")


def _build_rejected_snapshot(
    writer: StateWriter,
) -> tuple[PortfolioSnapshot, PortfolioAxis, PortfolioAxis]:
    spec = mission_spec()
    family_authority = require_volatility_duration_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
    )
    members = volatility_duration_replay_members(
        spec,
        historical_context_count=HISTORICAL_CONTEXT_COUNT,
        historical_family=family_authority.family,
        historical_family_authority_id=family_authority.identity,
    )
    require_volatility_duration_historical_context(
        writer,
        spec=spec,
        members=members,
        historical_context_count=HISTORICAL_CONTEXT_COUNT,
    )
    chassis = volatility_duration_replay_controlled_chassis(
        historical_context_prior_global_exposure_count=HISTORICAL_CONTEXT_COUNT
    )
    if chassis.architecture.identity != EXPECTED_ARCHITECTURE_FAMILY:
        raise RuntimeError("STU-0051 rejected bridge chassis drifted")

    with writer.open_stable_index() as (control, index):
        decision = index.get("portfolio-decision", DECISION_ID)
        decision_operation = index.get("operation", DECISION_OPERATION_ID)
        snapshot_record = index.get("portfolio-snapshot", BASE_SNAPSHOT_ID)
        if (
            decision is None
            or decision_operation is None
            or snapshot_record is None
            or not isinstance(decision.payload, Mapping)
        ):
            raise RuntimeError("STU-0051 invalid bridge projection is incomplete")
        _require_current_boundary(
            control,
            decision_payload=decision.payload,
            decision_operation=decision_operation,
        )
        raw_axes = snapshot_record.payload.get("axes")
        if not isinstance(raw_axes, list) or any(
            not isinstance(axis, Mapping) for axis in raw_axes
        ):
            raise RuntimeError("STU-0051 base Portfolio axes are malformed")
        components = component_surface_registry(
            _projection_payloads(index, members, raw_axes)
        )
        prior_axes = portfolio_axes_from_projection(raw_axes, components)

    conflicting = tuple(
        axis for axis in prior_axes if axis.axis_id == TARGET_AXIS_ID
    )
    if len(conflicting) != 1 or conflicting[0].identity != TARGET_AXIS_IDENTITY:
        raise RuntimeError("STU-0051 conflicting axis projection drifted")
    proposed_axis = PortfolioAxis(
        axis_id=PROPOSED_AXIS_ID,
        causal_question=STU0051_CAUSAL_QUESTION,
        mechanism_family=MECHANISM_FAMILY,
        primary_research_layer=ResearchLayer.SYNTHESIS,
        system_architecture_family=chassis.architecture.identity,
        changed_domains=tuple(chassis.changed_domains),
        controlled_domains=tuple(chassis.controlled_domains),
        why_now=WHY_NOW,
        stop_or_reopen_condition=STOP_OR_REOPEN,
        architecture_chassis=chassis.architecture,
    )
    if (
        proposed_axis.causal_question != conflicting[0].causal_question
        or proposed_axis.mechanism_family != conflicting[0].mechanism_family
    ):
        raise RuntimeError("STU-0051 rejected bridge is not an exact duplicate family")
    proposed_snapshot = PortfolioSnapshot(
        mission_id=spec.mission_id,
        axes=(*prior_axes, proposed_axis),
        opportunity_cost_basis=OPPORTUNITY_COST_BASIS,
        research_intake_id=snapshot_record.payload.get("research_intake_id"),
        exhaustion_standard=snapshot_record.payload.get("exhaustion_standard"),
    )
    return proposed_snapshot, proposed_axis, conflicting[0]


def build_plan(writer: StateWriter) -> dict[str, Any]:
    proposed, proposed_axis, conflicting_axis = _build_rejected_snapshot(writer)
    lineage = semantic_question_lineage()
    proposed_bytes = canonical_bytes(proposed.to_identity_payload())
    report_bytes = (
        "# STU-0051 Structural Decision Audit\n\n"
        f"- {FINDING_ID}:\n"
        f"  decision {DECISION_ID}\n"
        f"  operation {DECISION_OPERATION_ID}\n"
        f"  authority event {DECISION_AUTHORITY_EVENT_ID}\n"
        f"  proposed snapshot {proposed.identity}\n"
        f"  proposed axis {proposed_axis.identity}\n"
        f"  duplicate family {MECHANISM_FAMILY}\n"
        f"  conflicting axis {conflicting_axis.identity}\n"
        f"  semantic lineage {lineage.identity}\n"
        f"  semantic core {lineage.successor_core_id}\n"
    ).encode("ascii")
    manifest = PortfolioStructuralDecisionWithdrawalManifest(
        report_artifact_hash=_digest(report_bytes),
        report_finding_id=FINDING_ID,
        decision_id=DECISION_ID,
        decision_operation_id=DECISION_OPERATION_ID,
        decision_authority_revision=DECISION_AUTHORITY_REVISION,
        decision_authority_event_id=DECISION_AUTHORITY_EVENT_ID,
        portfolio_snapshot_id=BASE_SNAPSHOT_ID,
        target_axis_id=TARGET_AXIS_ID,
        target_axis_identity=TARGET_AXIS_IDENTITY,
        proposed_snapshot_artifact_hash=_digest(proposed_bytes),
        proposed_snapshot_id=proposed.identity,
        proposed_axis_id=PROPOSED_AXIS_ID,
        proposed_axis_identity=proposed_axis.identity,
        duplicate_mechanism_family=MECHANISM_FAMILY,
        conflicting_axis_id=conflicting_axis.axis_id,
        conflicting_axis_identity=conflicting_axis.identity,
        semantic_question_lineage=lineage,
        reason_code=(
            PortfolioDecisionWithdrawalReason
            .NEW_MECHANISM_DUPLICATES_EXISTING_FAMILY
        ),
        reason=(
            "the completed-bar replay revises the selectable same-mechanism "
            "axis protocol and cannot add a new mechanism"
        ),
    )
    manifest.require_report(report_bytes)
    manifest_bytes = canonical_bytes(manifest.to_identity_payload())
    plan = {
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_artifact_hash": _digest(manifest_bytes),
        "proposed_snapshot_bytes": proposed_bytes,
        "proposed_snapshot_id": proposed.identity,
        "proposed_snapshot_artifact_hash": _digest(proposed_bytes),
        "proposed_axis_identity": proposed_axis.identity,
        "report_bytes": report_bytes,
        "report_artifact_hash": _digest(report_bytes),
    }
    if (
        plan["proposed_axis_identity"] != EXPECTED_PROPOSED_AXIS_IDENTITY
        or plan["proposed_snapshot_id"] != EXPECTED_PROPOSED_SNAPSHOT_ID
        or plan["proposed_snapshot_artifact_hash"]
        != EXPECTED_PROPOSED_SNAPSHOT_ARTIFACT_HASH
        or plan["report_artifact_hash"] != EXPECTED_REPORT_ARTIFACT_HASH
        or plan["manifest_artifact_hash"] != EXPECTED_MANIFEST_ARTIFACT_HASH
    ):
        raise RuntimeError("STU-0051 structural withdrawal frozen plan drifted")
    return plan


def apply_plan(writer: StateWriter, plan: Mapping[str, Any]) -> dict[str, Any]:
    for name, document_key, hash_key in (
        (
            "proposed snapshot",
            "proposed_snapshot_bytes",
            "proposed_snapshot_artifact_hash",
        ),
        ("audit report", "report_bytes", "report_artifact_hash"),
        ("withdrawal manifest", "manifest_bytes", "manifest_artifact_hash"),
    ):
        document = plan[document_key]
        expected_hash = plan[hash_key]
        if not isinstance(document, bytes) or not isinstance(expected_hash, str):
            raise RuntimeError(f"{name} plan is malformed")
        artifact = writer.evidence.finalize(document)
        if artifact.sha256 != expected_hash:
            raise RuntimeError(f"{name} materialization drifted")
    result = writer.withdraw_structurally_invalid_portfolio_decision(
        manifest_artifact_hash=plan["manifest_artifact_hash"],
        operation_id=WITHDRAWAL_OPERATION_ID,
    )
    return {
        "event_id": result.event_id,
        "operation_id": WITHDRAWAL_OPERATION_ID,
        "result": result.result,
        "revision": result.revision,
    }


def _summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": DECISION_ID,
        "manifest_artifact_hash": plan["manifest_artifact_hash"],
        "mode": "read_only_plan",
        "proposed_axis_identity": plan["proposed_axis_identity"],
        "proposed_snapshot_artifact_hash": (
            plan["proposed_snapshot_artifact_hash"]
        ),
        "proposed_snapshot_id": plan["proposed_snapshot_id"],
        "report_artifact_hash": plan["report_artifact_hash"],
        "withdrawal_operation_id": WITHDRAWAL_OPERATION_ID,
    }


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply the exact STU-0051 bridge withdrawal."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="materialize evidence and record the additive Writer withdrawal",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    writer = StateWriter(ROOT)
    plan = build_plan(writer)
    summary = _summary(plan)
    if arguments.apply:
        summary["mode"] = "applied"
        summary["transition"] = apply_plan(writer, plan)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
