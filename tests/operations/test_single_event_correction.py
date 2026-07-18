from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    AuthorityFileBinding,
    CorrectionBaseline,
    CorrectionEventIntent,
    CorrectionEvidenceBinding,
    CorrectionExecutionFileBinding,
    CorrectionPlanCore,
)
from axiom_rift.operations.single_event_correction import (
    SingleEventCorrectionBinding,
    SingleEventCorrectionError,
    build_single_correction_event,
    correction_event_receipt,
    require_bound_single_correction_suffix,
)


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _binding() -> SingleEventCorrectionBinding:
    return SingleEventCorrectionBinding(
        control_projection={"next_action": {"kind": "portfolio_decision"}},
        event_payload={"audit_id": "diagnosis-audit", "evidence": []},
        operation_result={"corrected_diagnosis_count": 1},
        semantic_index_records=(
            {
                "event_sequence": 1,
                "event_stream": "diagnosis:one",
                "fingerprint": _digest("correction"),
                "kind": "study-diagnosis-correction",
                "payload": {"effective_evidence_state": "absent_information"},
                "record_id": "diagnosis-correction:" + _digest("correction"),
                "status": "absent_information",
                "subject": "Study:STU-0001",
            },
        ),
        guards={"runtime": {"safe": True}},
    )


def _core(binding: SingleEventCorrectionBinding | None = None) -> CorrectionPlanCore:
    authority = _digest("authority")
    return CorrectionPlanCore(
        operation_namespace="single-diagnosis-correction",
        baseline=CorrectionBaseline(
            control_revision=10,
            journal_sequence=10,
            journal_event_id=_digest("event-10"),
            journal_path="records/journal.jsonl",
            control_sha256=_digest("control"),
            journal_sha256=_digest("journal"),
            journal_start_offset=100,
            journal_size_bytes=200,
            authority_manifest_digest=authority,
            index_record_count=30,
            index_projection_digest=_digest("projection"),
            mission_id="MIS-0006",
            initiative_id="INI-0025",
            next_action_kind="portfolio_decision",
            code_checkpoint_commit="1" * 40,
            code_checkpoint_tree="2" * 40,
            origin_main_commit="3" * 40,
        ),
        prospective_authority_manifest_digest=authority,
        authority_files=(
            AuthorityFileBinding(
                path="OPERATING_DIRECTION.md",
                predecessor_sha256=_digest("direction"),
                prospective_sha256=_digest("direction"),
            ),
        ),
        code_checkpoint_files=(),
        execution_files=(
            CorrectionExecutionFileBinding(
                path="runner.py",
                sha256=_digest("runner"),
            ),
        ),
        evidence_bindings=(
            CorrectionEvidenceBinding(
                role="diagnosis-audit",
                sha256=_digest("audit"),
            ),
        ),
        event_intents=(
            CorrectionEventIntent(
                action="diagnosis-correction",
                event_kind="study_diagnoses_corrected",
                subject="Mission:MIS-0006",
                binding=(binding or _binding()).to_payload(),
            ),
        ),
        purpose="exercise one independently assembled correction event",
    )


def test_full_mapping_builds_one_exact_event_and_receipt() -> None:
    core = _core()
    event = build_single_correction_event(
        core,
        occurred_at_utc="2026-07-18T00:00:00Z",
    )
    receipt = correction_event_receipt(event)
    assert event["operation_id"] == core.events[0].operation_id
    assert event["index_record_count"] == 33
    assert event["journal_offset"] == 300
    assert len(event["index_records"]) == 2
    assert receipt.event_id == event["event_id"]
    assert receipt.canonical_event_byte_count == len(canonical_bytes(event)) + 1


def test_mapping_digest_tamper_and_operation_impersonation_fail_closed() -> None:
    payload = _binding().to_payload()
    payload["operation_result_sha256"] = _digest("forged")
    with pytest.raises(
        SingleEventCorrectionError,
        match="mapping or digest drifted",
    ):
        SingleEventCorrectionBinding.from_mapping(payload)

    record = dict(_binding().semantic_index_records[0])
    record["kind"] = "operation"
    with pytest.raises(
        SingleEventCorrectionError,
        match="impersonate envelope authority",
    ):
        replace(_binding(), semantic_index_records=(record,))


def test_existing_suffix_must_match_the_core_bound_full_event() -> None:
    core = _core()
    event = build_single_correction_event(
        core,
        occurred_at_utc="2026-07-18T00:00:00Z",
    )
    assert require_bound_single_correction_suffix(core, (event,)) == (event,)

    forged = deepcopy(event)
    semantic = forged["index_records"][1]
    semantic["payload"]["effective_evidence_state"] = "supported"
    forged_digest = canonical_digest(
        domain="study-diagnosis-correction",
        payload=semantic["payload"],
    )
    semantic["fingerprint"] = forged_digest
    semantic["record_id"] = "diagnosis-correction:" + forged_digest
    projection = core.baseline.index_projection_digest
    for row in forged["index_records"]:
        member = canonical_digest(
            domain="index-projection-member",
            payload={
                "event_sequence": row["event_sequence"],
                "event_stream": row["event_stream"],
                "fingerprint": row["fingerprint"],
                "kind": row["kind"],
                "payload": row["payload"],
                "record_id": row["record_id"],
                "status": row["status"],
                "subject": row["subject"],
            },
        )
        projection = canonical_digest(
            domain="index-projection-chain",
            payload={"member": member, "previous": projection},
        )
    forged["index_projection_digest"] = projection
    forged["event_id"] = canonical_digest(
        domain="journal-event",
        payload={key: value for key, value in forged.items() if key != "event_id"},
    )
    with pytest.raises(
        SingleEventCorrectionError,
        match="core-bound full event",
    ):
        require_bound_single_correction_suffix(core, (forged,))

    with pytest.raises(
        SingleEventCorrectionError,
        match="canonical UTC",
    ):
        build_single_correction_event(
            core,
            occurred_at_utc="2026-07-18T00:00:00+00:00",
        )


@pytest.mark.parametrize("mode", ("--plan", "--apply", "--recover"))
def test_exact_entrypoint_modes_require_isolated_no_site_startup(
    mode: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/apply_claim_scoped_diagnosis_corrections.py"),
            mode,
        ],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode != 0
    assert "exact diagnosis correction modes require" in (
        completed.stdout + completed.stderr
    )
