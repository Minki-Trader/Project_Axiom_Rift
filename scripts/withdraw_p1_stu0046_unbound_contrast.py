"""Withdraw the unstarted STU-0046 contrast Decision with no bound Study.

The default mode is read only.  ``--apply`` materializes the exact intended
snapshot and audit evidence, then records one additive Writer withdrawal.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.decision_withdrawal import (  # noqa: E402
    PortfolioDecisionWithdrawalReason,
    PortfolioExecutionPlanWithdrawalManifest,
)
import run_remaining_p1_fixed_hold_family as runner  # noqa: E402


DECISION_ID = (
    "decision:"
    "b9fa67f5002babf409d82396fc30afc034ff4d4e28e9961af462e7a1d31f5de1"
)
DECISION_OPERATION_ID = "p1-stu0046-gap-event-replay-v1-bridge-decision"
DECISION_AUTHORITY_REVISION = 5493
DECISION_AUTHORITY_EVENT_ID = (
    "e3dd98d6db7e29d56229a243e4dd0c3951dd8087d91b3e479181c299bf7cfe7e"
)
PREDECESSOR_REVISION = 5492
PREDECESSOR_EVENT_ID = (
    "d9a4ca3405545ada89376e60241ee1336c4acffc775e882c9cc5097eb5344f0f"
)
BASE_SNAPSHOT_ID = (
    "portfolio:"
    "b028d44ccfa145c66bb894be12c1516741c79cd195c9f0294ac73ef2d038d4c9"
)
TARGET_AXIS_ID = "axis-stu0032-distribution-asymmetry-replay-bridge"
TARGET_AXIS_IDENTITY = (
    "axis:"
    "f5e16bd8ae8d0671a28f999113402f6bf2888161988b71e33b9c51eee12a185b"
)
STUDY_DIAGNOSIS_ID = (
    "diagnosis:"
    "d805fc2624588982305af5753da9a97c04ffde60f9190abeb7cb8e4a8daae148"
)
CHOSEN_ACTION = "contrast"
STUDY_ID = "STU-0116"
BATCH_DISPLAY_ID = "BAT-0116"
FINDING_ID = "P1-STU0046-EXECUTION-PLAN-001"
WITHDRAWAL_OPERATION_ID = "p1-stu0046-unbound-contrast-withdrawal-v1"
EXPECTED_PROPOSED_AXIS_IDENTITY = (
    "axis:"
    "2bf613c49617cebb70cb29b752ad007dd0ebb3ad6f4d95da7f00a4c5489842b4"
)
EXPECTED_PROPOSED_SNAPSHOT_ID = (
    "portfolio:"
    "092fd145375afbbbc7f00fc42997065cfe7034aa8c9af55153a19dea7110908f"
)
EXPECTED_PROPOSED_SNAPSHOT_ARTIFACT_HASH = (
    "5c7bf0d5cf8846588e6e6a340d2964ac4d3d31d763efa717517f9176ea39a4a5"
)
EXPECTED_REPORT_ARTIFACT_HASH = (
    "8c91441ce4759217fa3add03b23a6ef741f0438503b59d9dcccb4743fe39e22d"
)
EXPECTED_MANIFEST_ARTIFACT_HASH = (
    "5ca410d3a8f4efe34f2987299338f24c5d853ee679a98667dc7fefaadb567a7d"
)


def _digest(document: bytes) -> str:
    return sha256(document).hexdigest()


def _authority() -> runner.RunAuthority:
    route = replace(
        runner.FAMILY_ROUTES["stu0046"],
        operation_prefix="p1-stu0046-gap-event-replay-v1-",
    )
    return runner.RunAuthority(
        route=route,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        predecessor_revision=PREDECESSOR_REVISION,
        predecessor_event_id=PREDECESSOR_EVENT_ID,
    )


def build_plan(writer: StateWriter) -> dict[str, Any]:
    design = runner.build_design(writer, _authority())
    proposed = design.expanded_snapshot
    proposed_axis = design.replay_axis
    with writer.open_stable_index() as (control, index):
        action = control.get("next_action")
        decision = index.get("portfolio-decision", DECISION_ID)
        operation = index.get("operation", DECISION_OPERATION_ID)
        if (
            control.get("revision") != DECISION_AUTHORITY_REVISION
            or control.get("heads", {}).get("journal", {}).get("event_id")
            != DECISION_AUTHORITY_EVENT_ID
            or not isinstance(action, Mapping)
            or action.get("kind") != "execute_portfolio_decision"
            or action.get("decision_id") != DECISION_ID
            or action.get("portfolio_snapshot_id") != BASE_SNAPSHOT_ID
            or action.get("target_id") != TARGET_AXIS_ID
            or action.get("target_axis_identity") != TARGET_AXIS_IDENTITY
            or action.get("study_diagnosis_id") != STUDY_DIAGNOSIS_ID
            or decision is None
            or operation is None
            or operation.status != "success"
            or operation.authority_sequence != DECISION_AUTHORITY_REVISION
            or operation.authority_event_id != DECISION_AUTHORITY_EVENT_ID
        ):
            raise RuntimeError("STU-0046 unbound Decision boundary drifted")

    proposed_bytes = canonical_bytes(proposed.to_identity_payload())
    report_bytes = (
        "# STU-0046 Execution Plan Audit\n\n"
        f"- {FINDING_ID}:\n"
        f"  decision {DECISION_ID}\n"
        f"  operation {DECISION_OPERATION_ID}\n"
        f"  authority event {DECISION_AUTHORITY_EVENT_ID}\n"
        f"  base snapshot {BASE_SNAPSHOT_ID}\n"
        f"  target axis {TARGET_AXIS_IDENTITY}\n"
        f"  chosen action {CHOSEN_ACTION}\n"
        f"  intended snapshot {proposed.identity}\n"
        f"  intended axis {proposed_axis.identity}\n"
        f"  intended Study {STUDY_ID}\n"
        f"  diagnosis {STUDY_DIAGNOSIS_ID}\n"
        "  failure scientific execution action cannot authorize a Portfolio "
        "snapshot mutation and no Study or trial was started\n"
    ).encode("ascii")
    manifest = PortfolioExecutionPlanWithdrawalManifest(
        report_artifact_hash=_digest(report_bytes),
        report_finding_id=FINDING_ID,
        decision_id=DECISION_ID,
        decision_operation_id=DECISION_OPERATION_ID,
        decision_authority_revision=DECISION_AUTHORITY_REVISION,
        decision_authority_event_id=DECISION_AUTHORITY_EVENT_ID,
        portfolio_snapshot_id=BASE_SNAPSHOT_ID,
        target_axis_id=TARGET_AXIS_ID,
        target_axis_identity=TARGET_AXIS_IDENTITY,
        chosen_action=CHOSEN_ACTION,
        proposed_snapshot_artifact_hash=_digest(proposed_bytes),
        proposed_snapshot_id=proposed.identity,
        proposed_axis_id=proposed_axis.axis_id,
        proposed_axis_identity=proposed_axis.identity,
        intended_study_id=STUDY_ID,
        study_diagnosis_id=STUDY_DIAGNOSIS_ID,
        reason_code=(
            PortfolioDecisionWithdrawalReason
            .UNBOUND_STRUCTURAL_EXECUTION_PLAN
        ),
        reason=(
            "the accepted contrast action was incorrectly used as structural "
            "axis admission and has no exact executable Study plan"
        ),
    )
    manifest.require_report(report_bytes)
    manifest_bytes = canonical_bytes(manifest.to_identity_payload())
    plan = {
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_artifact_hash": _digest(manifest_bytes),
        "proposed_axis_identity": proposed_axis.identity,
        "proposed_snapshot_bytes": proposed_bytes,
        "proposed_snapshot_id": proposed.identity,
        "proposed_snapshot_artifact_hash": _digest(proposed_bytes),
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
        raise RuntimeError("STU-0046 execution-plan withdrawal drifted")
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
    result = writer.withdraw_unbound_execution_plan_portfolio_decision(
        manifest_artifact_hash=plan["manifest_artifact_hash"],
        operation_id=WITHDRAWAL_OPERATION_ID,
    )
    return {
        "event_id": result.event_id,
        "operation_id": WITHDRAWAL_OPERATION_ID,
        "result": result.result,
        "revision": result.revision,
    }


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply the exact STU-0046 Decision withdrawal."
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
    summary = {
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
    if arguments.apply:
        summary["mode"] = "applied"
        summary["transition"] = apply_plan(writer, plan)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
