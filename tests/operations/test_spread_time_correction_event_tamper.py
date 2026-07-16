from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
from typing import Any, Mapping

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


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "apply_spread_time_semantics_correction.py"


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


@pytest.fixture(scope="module")
def correction_module():
    name = "apply_spread_time_semantics_correction_event_tamper_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _semantic_row(ordinal: int) -> dict[str, Any]:
    return {
        "event_sequence": ordinal,
        "event_stream": f"tamper-test:{ordinal}",
        "fingerprint": _digest(f"semantic-{ordinal}"),
        "kind": "tamper-test-semantic",
        "payload": {"ordinal": ordinal, "zero_delta": 0},
        "record_id": f"tamper-test:{_digest(str(ordinal))}",
        "status": "recorded",
        "subject": f"Mission:tamper-{ordinal}",
    }


def _result(ordinal: int) -> dict[str, Any]:
    return {"ordinal": ordinal, "zero_delta": 0}


def _control(ordinal: int) -> dict[str, Any]:
    return {
        "authority": {"manifest_digest": _digest("authority")},
        "marker": ordinal,
        "next_action": {"kind": "portfolio_decision"},
        "scientific": {"active_mission": "MIS-TAMPER"},
    }


def _core() -> CorrectionPlanCore:
    intents = []
    for ordinal in range(1, 8):
        semantic = _semantic_row(ordinal)
        result = _result(ordinal)
        intents.append(
            CorrectionEventIntent(
                action=f"tamper-step-{ordinal}",
                event_kind=f"tamper_event_{ordinal}",
                subject=f"Mission:tamper-{ordinal}",
                binding={
                    "control_projection_sha256": sha256(
                        canonical_bytes(_control(ordinal))
                    ).hexdigest(),
                    "operation_result": result,
                    "semantic_record_count": 1,
                    "semantic_row_sha256": [
                        sha256(canonical_bytes(semantic)).hexdigest()
                    ],
                },
            )
        )
    return CorrectionPlanCore(
        operation_namespace="tamper-test-correction",
        baseline=CorrectionBaseline(
            control_revision=20,
            journal_sequence=30,
            journal_event_id=_digest("baseline-event"),
            journal_path="records/journal/journal-000002.jsonl",
            control_sha256=_digest("baseline-control"),
            journal_sha256=_digest("baseline-journal"),
            journal_start_offset=1_000,
            journal_size_bytes=200,
            authority_manifest_digest=_digest("authority"),
            index_record_count=50,
            index_projection_digest=_digest("baseline-projection"),
            mission_id="MIS-TAMPER",
            initiative_id="INI-TAMPER",
            next_action_kind="portfolio_decision",
            code_checkpoint_commit="1" * 40,
            code_checkpoint_tree="2" * 40,
            origin_main_commit="3" * 40,
            journal_manifest_sha256=_digest("journal-manifest"),
        ),
        prospective_authority_manifest_digest=_digest("prospective-authority"),
        authority_files=(
            AuthorityFileBinding(
                path="OPERATING_DIRECTION.md",
                predecessor_sha256=_digest("old-authority-file"),
                prospective_sha256=_digest("new-authority-file"),
            ),
        ),
        code_checkpoint_files=(),
        execution_files=(
            CorrectionExecutionFileBinding(
                path="scripts/apply_spread_time_semantics_correction.py",
                sha256=_digest("reviewed-script"),
            ),
        ),
        evidence_bindings=(
            CorrectionEvidenceBinding(
                role="tamper-test-audit",
                sha256=_digest("audit"),
            ),
        ),
        event_intents=tuple(intents),
        purpose="prove every correction event fails closed before append",
    )


def _projection_member_digest(record: Mapping[str, Any]) -> str:
    return canonical_digest(
        domain="index-projection-member",
        payload={
            "event_sequence": record.get("event_sequence"),
            "event_stream": record.get("event_stream"),
            "fingerprint": record.get("fingerprint"),
            "kind": record.get("kind"),
            "payload": record.get("payload"),
            "record_id": record.get("record_id"),
            "status": record.get("status"),
            "subject": record.get("subject"),
        },
    )


def _reseal_event(
    event: dict[str, Any],
    *,
    cursor: Any,
) -> None:
    projection = cursor.index_projection_digest
    for row in event["index_records"]:
        projection = canonical_digest(
            domain="index-projection-chain",
            payload={
                "member": _projection_member_digest(row),
                "previous": projection,
            },
        )
    event["index_projection_digest"] = projection
    event["index_record_count"] = (
        cursor.index_record_count + 1 + len(event["index_records"])
    )
    event["event_id"] = canonical_digest(
        domain="journal-event",
        payload={key: value for key, value in event.items() if key != "event_id"},
    )


def _events_and_cursors(module: Any, core: CorrectionPlanCore):
    cursor = module._IndependentEventCursor(
        journal_offset=(
            core.baseline.journal_start_offset
            + core.baseline.journal_size_bytes
        ),
        previous_event_id=core.baseline.journal_event_id,
        index_record_count=core.baseline.index_record_count,
        index_projection_digest=core.baseline.index_projection_digest,
    )
    result = []
    for ordinal, action in enumerate(core.events, 1):
        prior = cursor
        payload = {"ordinal": ordinal}
        operation_result = _result(ordinal)
        operation = {
            "event_sequence": None,
            "event_stream": None,
            "fingerprint": canonical_digest(
                domain="operation",
                payload={"event_kind": action.event_kind, "payload": payload},
            ),
            "kind": "operation",
            "payload": {
                "event_kind": action.event_kind,
                "result": operation_result,
            },
            "record_id": action.operation_id,
            "status": "success",
            "subject": action.subject,
        }
        event = {
            "control": _control(ordinal),
            "event_id": "",
            "event_kind": action.event_kind,
            "index_projection_digest": "",
            "index_record_count": 0,
            "index_records": [operation, _semantic_row(ordinal)],
            "journal_offset": prior.journal_offset,
            "occurred_at_utc": f"2000-01-01T00:00:00.{ordinal:06d}Z",
            "operation_id": action.operation_id,
            "payload": payload,
            "previous_event_id": prior.previous_event_id,
            "schema": "journal_event",
            "sequence": core.baseline.journal_sequence + ordinal,
            "subject": action.subject,
        }
        _reseal_event(event, cursor=prior)
        cursor = module._require_independent_event_envelope(
            core,
            ordinal,
            event,
            prior,
            occurred_at_utc=event["occurred_at_utc"],
        )
        result.append((event, prior, cursor))
    return result


class _FakePreappendWriter:
    def __init__(self, module: Any, core: CorrectionPlanCore) -> None:
        self.module = module
        self.core = core
        self.journal: list[dict[str, Any]] = []
        self.state = {"revision": core.baseline.control_revision}

    def append(
        self,
        *,
        ordinal: int,
        event: Mapping[str, Any],
        cursor: Any,
    ) -> Any:
        rows = event["index_records"][1:]
        observed_result = event["index_records"][0]["payload"]["result"]
        dynamic = (
            self.module._DynamicActionExpectation(
                event_payload=event["payload"],
                operation_result=_result(ordinal),
                semantic_rows=(_semantic_row(ordinal),),
            )
            if ordinal in {5, 6}
            else None
        )
        self.module._require_exact_bound_rows_and_result(
            ordinal=ordinal,
            binding=self.core.events[ordinal - 1].binding,
            rows=rows,
            result=observed_result,
            dynamic_expectation=dynamic,
        )
        next_cursor = self.module._require_independent_event_envelope(
            self.core,
            ordinal,
            event,
            cursor,
            occurred_at_utc=event["occurred_at_utc"],
        )
        self.journal.append(deepcopy(dict(event)))
        self.state["revision"] += 1
        return next_cursor


def _tamper(event: dict[str, Any], attack: str, cursor: Any) -> None:
    if attack == "control_digest":
        event["control"]["marker"] = 999
        _reseal_event(event, cursor=cursor)
    elif attack == "sequence":
        event["sequence"] += 1
        _reseal_event(event, cursor=cursor)
    elif attack == "previous_event_id":
        event["previous_event_id"] = _digest("foreign-previous")
        _reseal_event(event, cursor=cursor)
    elif attack == "journal_offset":
        event["journal_offset"] += 1
        _reseal_event(event, cursor=cursor)
    elif attack == "index_record_count":
        _reseal_event(event, cursor=cursor)
        event["index_record_count"] += 1
        event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={
                key: value for key, value in event.items() if key != "event_id"
            },
        )
    elif attack == "index_projection_digest":
        _reseal_event(event, cursor=cursor)
        event["index_projection_digest"] = _digest("foreign-projection")
        event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={
                key: value for key, value in event.items() if key != "event_id"
            },
        )
    elif attack == "semantic_field":
        event["index_records"][1]["status"] = "foreign"
        _reseal_event(event, cursor=cursor)
    elif attack == "semantic_field_missing":
        del event["index_records"][1]["status"]
        _reseal_event(event, cursor=cursor)
    elif attack == "semantic_field_extra":
        event["index_records"][1]["foreign"] = True
        _reseal_event(event, cursor=cursor)
    elif attack == "result_missing":
        del event["index_records"][0]["payload"]["result"]["zero_delta"]
        _reseal_event(event, cursor=cursor)
    elif attack == "result_extra":
        event["index_records"][0]["payload"]["result"]["foreign"] = True
        _reseal_event(event, cursor=cursor)
    elif attack == "event_id":
        event["event_id"] = _digest("foreign-event")
    else:  # pragma: no cover - the parameter inventory is fixed below.
        raise AssertionError(attack)


@pytest.mark.parametrize("ordinal", range(1, 8))
@pytest.mark.parametrize(
    "attack",
    (
        "control_digest",
        "sequence",
        "previous_event_id",
        "journal_offset",
        "index_record_count",
        "index_projection_digest",
        "semantic_field",
        "semantic_field_missing",
        "semantic_field_extra",
        "result_missing",
        "result_extra",
        "event_id",
    ),
)
def test_all_seven_events_reject_tampering_before_append(
    correction_module: Any,
    ordinal: int,
    attack: str,
) -> None:
    core = _core()
    event, prior, _next_cursor = _events_and_cursors(
        correction_module,
        core,
    )[ordinal - 1]
    forged = deepcopy(event)
    _tamper(forged, attack, prior)
    writer = _FakePreappendWriter(correction_module, core)
    journal_before = canonical_bytes(writer.journal)
    state_before = canonical_bytes(writer.state)

    with pytest.raises(correction_module.SpreadTimeCorrectionError):
        writer.append(
            ordinal=ordinal,
            event=forged,
            cursor=prior,
        )

    assert canonical_bytes(writer.journal) == journal_before
    assert canonical_bytes(writer.state) == state_before


def test_valid_events_cross_the_same_preappend_gate(
    correction_module: Any,
) -> None:
    core = _core()
    writer = _FakePreappendWriter(correction_module, core)
    for ordinal, (event, prior, expected_cursor) in enumerate(
        _events_and_cursors(correction_module, core),
        1,
    ):
        observed_cursor = writer.append(
            ordinal=ordinal,
            event=event,
            cursor=prior,
        )
        assert observed_cursor == expected_cursor
    assert len(writer.journal) == 7
    assert writer.state == {"revision": core.baseline.control_revision + 7}
