#!/usr/bin/env python3
"""Render a read-only, head-bound research-history map from the local index."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
from typing import Any


def _records(connection: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT record_id, subject, status, payload_json, authority_sequence
        FROM records
        WHERE kind = ?
        ORDER BY authority_sequence, record_id
        """,
        (kind,),
    ).fetchall()
    return [
        {
            "authority_sequence": row["authority_sequence"],
            "payload": json.loads(row["payload_json"]),
            "record_id": row["record_id"],
            "status": row["status"],
            "subject": row["subject"],
        }
        for row in rows
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


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    control = json.loads(
        (root / "state" / "control.json").read_text(encoding="ascii")
    )
    index_path = (root / "local" / "index.sqlite").resolve()
    if not index_path.is_file():
        raise FileNotFoundError("local/index.sqlite is absent; recover the projection first")
    connection = sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        _assert_projection_head(connection, control)
        studies = _records(connection, "study-open")
        closes = _records(connection, "study-close")
        kpis = _records(connection, "study-kpi")
        diagnoses = _records(connection, "study-diagnosis")
        decisions = _records(connection, "portfolio-decision")
        trials = _records(connection, "trial")
        memories = _records(connection, "negative-memory")
        mission_closes = _records(connection, "mission-close")
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
        question = payload.get("question", {})
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
                "diagnosis_confidence": (
                    None
                    if diagnosis is None
                    else diagnosis["payload"].get("confidence")
                ),
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
    evidence_state_counts = Counter(
        row["evidence_state"] for row in study_rows if row["evidence_state"] is not None
    )
    component_counts: Counter[str] = Counter()
    for row in study_rows:
        component_counts.update(row["component_domains"])
    return {
        "history_head": {
            "event_id": control["heads"]["journal"]["event_id"],
            "revision": control["revision"],
        },
        "schema": "research_history_audit.v1",
        "studies": study_rows,
        "summary": {
            "architecture_family_study_counts": dict(
                sorted(architecture_counts.items(), key=lambda item: str(item[0]))
            ),
            "component_domain_study_counts": dict(sorted(component_counts.items())),
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
