#!/usr/bin/env python3
"""Activate the fail-closed atomic scientific proof validator."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.study_close_git import (  # noqa: E402
    require_study_close_guard_ready,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry  # noqa: E402
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.protocol import (  # noqa: E402
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


OPERATION_ID = (
    "project-goal-audit-v2-atomic-scientific-proof-enforcement-v1"
)
AUDIT_REPORT = Path(
    "records/audits/2026-07-16_atomic_scientific_proof_enforcement.md"
)
EXPECTED_REPORT_SHA256 = (
    "1494319972cb6063a4b17aa4b6c4990c8fa3af0977e3fd878b5df15859f7bc97"
)
EXPECTED_REPORT_SIZE = 3207
EXPECTED_REPORT_MARKERS = (
    "status: repaired_pending_activation",
    "The proof parser also accepted that generic envelope as an alternative",
    "## Quant-Team Review",
    "scientific_trial_delta: 0",
    "historical_verdict_delta: 0",
)


def _read_audit_report(root: Path = ROOT) -> bytes:
    content = (root / AUDIT_REPORT).read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("atomic proof audit report is not ASCII") from exc
    if (
        len(content) != EXPECTED_REPORT_SIZE
        or sha256(content).hexdigest() != EXPECTED_REPORT_SHA256
        or any(text.count(marker) != 1 for marker in EXPECTED_REPORT_MARKERS)
    ):
        raise RuntimeError("atomic proof audit report bytes differ")
    return content


def plan_activation(root: Path = ROOT) -> dict[str, object]:
    report = _read_audit_report(root)
    return {
        "audit_report_sha256": sha256(report).hexdigest(),
        "authority_manifest_digest": StateWriter(root).read_control()["authority"][
            "manifest_digest"
        ],
        "operation_id": OPERATION_ID,
        "schema": "atomic_scientific_proof_activation_plan.v1",
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }


def apply_activation(root: Path = ROOT) -> dict[str, object]:
    require_study_close_guard_ready(root)
    report = _read_audit_report(root)
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("atomic proof activation requires control")
    before = deepcopy(before)
    report_artifact = writer.evidence.finalize(report)
    activation = writer.activate_research_protocol(
        activation=ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            authority_manifest_digest=before["authority"]["manifest_digest"],
            audit_artifact_hash=report_artifact.sha256,
        ),
        operation_id=OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    after = writer.read_control()
    if after is None:
        raise RuntimeError("atomic proof activation lost control")
    for field in ("authority", "initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"atomic proof activation changed {field}")
    event_delta = int(not activation.reused)
    if after["revision"] != before["revision"] + event_delta:
        raise RuntimeError("atomic proof activation revision differs")
    return {
        "audit_artifact_hash": report_artifact.sha256,
        "event_id": activation.event_id,
        "reused": activation.reused,
        "revision": after["revision"],
        "schema": "atomic_scientific_proof_activation_result.v1",
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the typed research-protocol activation",
    )
    args = parser.parse_args()
    result = apply_activation(ROOT) if args.apply else plan_activation(ROOT)
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
