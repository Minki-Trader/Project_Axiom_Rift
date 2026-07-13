#!/usr/bin/env python3
"""Render a head-bound research-history map from Journal-authorized index rows."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_SRC = _REPOSITORY_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from axiom_rift.core.canonical import parse_canonical  # noqa: E402
from axiom_rift.core.identity import canonical_digest  # noqa: E402
from axiom_rift.storage.index import IndexRecord  # noqa: E402
from axiom_rift.storage.journal import DurableJournal  # noqa: E402


_RESEARCH_LAYERS = frozenset(
    {
        "data_source",
        "feature",
        "label",
        "model",
        "objective",
        "calibration",
        "selector",
        "trade",
        "lifecycle",
        "risk",
        "regime",
        "execution",
        "synthesis",
        "portfolio",
    }
)


def _record_digest(record: IndexRecord, payload_json: str) -> str:
    return canonical_digest(
        domain="index-record-projection",
        payload={
            "event_sequence": record.event_sequence,
            "event_stream": record.event_stream,
            "fingerprint": record.fingerprint,
            "kind": record.kind,
            "payload": parse_canonical(payload_json),
            "record_id": record.record_id,
            "status": record.status,
            "subject": record.subject,
            "authority_sequence": record.authority_sequence,
            "authority_event_id": record.authority_event_id,
            "authority_offset": record.authority_offset,
        },
    )


def _projection_mapping(record: IndexRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "record_id": record.record_id,
        "subject": record.subject,
        "status": record.status,
        "fingerprint": record.fingerprint,
        "payload": dict(record.payload),
        "event_stream": record.event_stream,
        "event_sequence": record.event_sequence,
    }


def _decode_authorized_record(
    row: sqlite3.Row,
    journal: DurableJournal,
    event_cache: dict[tuple[int, int, str], dict[str, Any]],
) -> IndexRecord:
    payload_json = row["payload_json"]
    record = IndexRecord(
        kind=row["kind"],
        record_id=row["record_id"],
        subject=row["subject"],
        status=row["status"],
        fingerprint=row["fingerprint"],
        payload=parse_canonical(payload_json),
        event_stream=row["event_stream"],
        event_sequence=row["event_sequence"],
        authority_sequence=row["authority_sequence"],
        authority_event_id=row["authority_event_id"],
        authority_offset=row["authority_offset"],
    )
    if _record_digest(record, payload_json) != row["record_digest"]:
        raise RuntimeError(
            f"research-history record digest mismatch: {record.kind}:{record.record_id}"
        )
    if (
        record.authority_sequence is None
        or record.authority_event_id is None
        or record.authority_offset is None
    ):
        raise RuntimeError(
            f"research-history record lacks Journal authority: "
            f"{record.kind}:{record.record_id}"
        )
    authority_key = (
        record.authority_offset,
        record.authority_sequence,
        record.authority_event_id,
    )
    event = event_cache.get(authority_key)
    if event is None:
        event = journal.read_event_at(
            offset=record.authority_offset,
            expected_sequence=record.authority_sequence,
            expected_event_id=record.authority_event_id,
        )
        event_cache[authority_key] = event
    projected = _projection_mapping(record)
    matches = [item for item in event.get("index_records", []) if item == projected]
    if len(matches) != 1:
        raise RuntimeError(
            f"research-history record is not a unique Journal member: "
            f"{record.kind}:{record.record_id}"
        )
    return record


def _records(
    connection: sqlite3.Connection,
    journal: DurableJournal,
    event_cache: dict[tuple[int, int, str], dict[str, Any]],
    kind: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT kind, record_id, subject, status, fingerprint, payload_json,
               event_stream, event_sequence, authority_sequence,
               authority_event_id, authority_offset, record_digest
        FROM records
        WHERE kind = ?
        ORDER BY authority_sequence, record_id
        """,
        (kind,),
    ).fetchall()
    records = [
        _decode_authorized_record(row, journal, event_cache) for row in rows
    ]
    return [
        {
            "authority_sequence": record.authority_sequence,
            "payload": dict(record.payload),
            "record_id": record.record_id,
            "status": record.status,
            "subject": record.subject,
        }
        for record in records
    ]


def _assert_projection_head(
    connection: sqlite3.Connection,
    control: dict[str, Any],
) -> None:
    row = connection.execute(
        """
        SELECT record_count, projection_digest, projection_valid
        FROM projection_stats
        WHERE singleton = 1
        """
    ).fetchone()
    expected = control["heads"]["index"]
    if (
        row is None
        or row["projection_valid"] != 1
        or row["record_count"] != expected["required_record_count"]
        or row["projection_digest"] != expected["required_projection_digest"]
    ):
        raise RuntimeError("local index does not match the authoritative control head")


def _domain_values(value: object) -> list[str]:
    candidates: list[object]
    if isinstance(value, dict):
        candidates = list(value)
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    elif isinstance(value, str):
        candidates = [value]
    else:
        candidates = []
    return sorted(
        {
            item
            for item in candidates
            if isinstance(item, str) and item in _RESEARCH_LAYERS
        }
    )


def _declared_domains(payload: dict[str, Any], name: str) -> list[str]:
    value = payload.get(name)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or item not in _RESEARCH_LAYERS for item in value
    ):
        return []
    return sorted(set(value))


def _domain_alignment(
    payload: dict[str, Any],
    question: dict[str, Any],
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    declared_changed = _declared_domains(payload, "changed_domains")
    declared_controlled = _declared_domains(payload, "controlled_domains")
    question_changed = _domain_values(question.get("changed_variables"))
    question_controlled = _domain_values(question.get("controlled_variables"))
    if not declared_changed or not declared_controlled:
        status = "legacy_unclassified"
    elif not question_changed or not question_controlled:
        status = "question_unclassified"
    elif (
        question_changed == declared_changed
        and question_controlled == declared_controlled
    ):
        status = "aligned"
    else:
        status = "mismatch"
    return (
        status,
        declared_changed,
        declared_controlled,
        question_changed,
        question_controlled,
    )


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    control = json.loads(
        (root / "state" / "control.json").read_text(encoding="ascii")
    )
    index_path = (root / "local" / "index.sqlite").resolve()
    if not index_path.is_file():
        raise FileNotFoundError("local/index.sqlite is absent; recover the projection first")
    journal = DurableJournal(root / "records" / "journal.jsonl")
    connection = sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    event_cache: dict[tuple[int, int, str], dict[str, Any]] = {}
    try:
        _assert_projection_head(connection, control)
        studies = _records(connection, journal, event_cache, "study-open")
        closes = _records(connection, journal, event_cache, "study-close")
        kpis = _records(connection, journal, event_cache, "study-kpi")
        diagnoses = _records(connection, journal, event_cache, "study-diagnosis")
        decisions = _records(connection, journal, event_cache, "portfolio-decision")
        trials = _records(connection, journal, event_cache, "trial")
        memories = _records(connection, journal, event_cache, "negative-memory")
        mission_closes = _records(connection, journal, event_cache, "mission-close")
    finally:
        connection.close()

    close_by_study = {
        record["subject"].removeprefix("Study:"): record for record in closes
    }
    kpi_by_study = {record["record_id"]: record for record in kpis}
    diagnosis_by_study = {
        record["subject"].removeprefix("Study:"): record
        for record in diagnoses
    }
    decision_by_id = {record["record_id"]: record for record in decisions}
    memories_by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        study_id = memory["payload"].get("study_id")
        if isinstance(study_id, str):
            memories_by_study[study_id].append(memory)
    component_domains_by_study: dict[str, set[str]] = defaultdict(set)
    for trial in trials:
        study_id = trial["payload"].get("study_id")
        executable = trial["payload"].get("executable")
        manifests = (
            None
            if not isinstance(executable, dict)
            else executable.get("component_manifests")
        )
        if not isinstance(study_id, str) or not isinstance(manifests, list):
            continue
        for manifest in manifests:
            protocol = (
                None
                if not isinstance(manifest, dict)
                else manifest.get("protocol")
            )
            if isinstance(protocol, str) and protocol:
                component_domains_by_study[study_id].add(
                    protocol.split(".", 1)[0]
                )

    study_rows: list[dict[str, Any]] = []
    for record in studies:
        study_id = record["record_id"]
        payload = record["payload"]
        raw_question = payload.get("question", {})
        question = raw_question if isinstance(raw_question, dict) else {}
        close = close_by_study.get(study_id)
        kpi = kpi_by_study.get(study_id)
        diagnosis = diagnosis_by_study.get(study_id)
        decision = decision_by_id.get(payload.get("portfolio_decision_id"))
        chosen_action = None
        if decision is not None:
            options = {
                option.get("option_id"): option
                for option in decision["payload"].get("options", [])
                if isinstance(option, dict)
            }
            chosen = options.get(decision["payload"].get("chosen_option_id"))
            if isinstance(chosen, dict):
                chosen_action = chosen.get("action")
        metrics = {} if kpi is None else kpi["payload"].get("metrics", {})
        negative_rows = memories_by_study.get(study_id, [])
        (
            alignment,
            declared_changed,
            declared_controlled,
            question_changed,
            question_controlled,
        ) = _domain_alignment(payload, question)
        study_rows.append(
            {
                "architecture_family": payload.get(
                    "system_architecture_family", "legacy_unclassified"
                ),
                "causal_question": question.get("causal_question"),
                "changed_variables": question.get("changed_variables", []),
                "component_domains": sorted(
                    component_domains_by_study.get(study_id, set())
                ),
                "controlled_variables": question.get("controlled_variables", []),
                "declared_changed_domains": declared_changed,
                "declared_controlled_domains": declared_controlled,
                "diagnosis_confidence": (
                    None
                    if diagnosis is None
                    else diagnosis["payload"].get("confidence")
                ),
                "domain_alignment": alignment,
                "evidence_completion_record_id": (
                    None
                    if kpi is None
                    else kpi["payload"].get("completion_record_id")
                ),
                "evidence_state": None if diagnosis is None else diagnosis["status"],
                "kpi": metrics,
                "mechanism_family": payload.get("mechanism_family"),
                "mission_id": payload.get("mission_id"),
                "negative_memory_count": len(negative_rows),
                "outcome": None if close is None else close["status"],
                "portfolio_action": chosen_action,
                "primary_research_layer": payload.get(
                    "primary_research_layer", "legacy_unclassified"
                ),
                "question_changed_domains": question_changed,
                "question_controlled_domains": question_controlled,
                "reopen_conditions": sorted(
                    {
                        memory["payload"].get("reopen_condition")
                        for memory in negative_rows
                        if isinstance(
                            memory["payload"].get("reopen_condition"), str
                        )
                    }
                ),
                "study_id": study_id,
            }
        )

    layer_counts = Counter(row["primary_research_layer"] for row in study_rows)
    architecture_counts = Counter(row["architecture_family"] for row in study_rows)
    mechanism_counts = Counter(row["mechanism_family"] for row in study_rows)
    outcome_counts = Counter(row["outcome"] for row in study_rows)
    alignment_counts = Counter(row["domain_alignment"] for row in study_rows)
    evidence_state_counts = Counter(
        row["evidence_state"] for row in study_rows if row["evidence_state"] is not None
    )
    component_counts: Counter[str] = Counter()
    for row in study_rows:
        component_counts.update(row["component_domains"])
    verified_record_count = sum(
        len(records)
        for records in (
            studies,
            closes,
            kpis,
            diagnoses,
            decisions,
            trials,
            memories,
            mission_closes,
        )
    )
    return {
        "history_head": {
            "event_id": control["heads"]["journal"]["event_id"],
            "revision": control["revision"],
        },
        "schema": "research_history_audit.v2",
        "studies": study_rows,
        "summary": {
            "architecture_family_study_counts": dict(
                sorted(architecture_counts.items(), key=lambda item: str(item[0]))
            ),
            "authority_verified_event_count": len(event_cache),
            "authority_verified_record_count": verified_record_count,
            "component_domain_study_counts": dict(sorted(component_counts.items())),
            "domain_alignment_counts": dict(sorted(alignment_counts.items())),
            "domain_alignment_mismatch_study_ids": sorted(
                row["study_id"]
                for row in study_rows
                if row["domain_alignment"] == "mismatch"
            ),
            "evidence_state_counts": dict(sorted(evidence_state_counts.items())),
            "legacy_unclassified_study_count": layer_counts.get(
                "legacy_unclassified", 0
            ),
            "mechanism_family_study_counts": dict(
                sorted(mechanism_counts.items(), key=lambda item: str(item[0]))
            ),
            "mission_outcome_counts": dict(
                sorted(Counter(row["status"] for row in mission_closes).items())
            ),
            "negative_memory_count": len(memories),
            "outcome_counts": dict(
                sorted(outcome_counts.items(), key=lambda item: str(item[0]))
            ),
            "primary_research_layer_study_counts": dict(sorted(layer_counts.items())),
            "study_count": len(study_rows),
            "study_kpi_count": len(kpis),
            "trial_count": len(trials),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--study-id")
    parser.add_argument("--indent", type=int)
    arguments = parser.parse_args()
    audit = build_audit(arguments.root)
    if arguments.study_id is not None:
        audit["studies"] = [
            row
            for row in audit["studies"]
            if row["study_id"] == arguments.study_id
        ]
        if not audit["studies"]:
            raise SystemExit(f"unknown Study: {arguments.study_id}")
    elif arguments.summary_only:
        audit.pop("studies")
    print(
        json.dumps(
            audit,
            ensure_ascii=True,
            indent=arguments.indent,
            separators=None if arguments.indent is not None else (",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
