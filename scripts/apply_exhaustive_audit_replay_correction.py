"""Plan or apply the current authority and replay-satisfaction correction.

The checked-out authority documents intentionally contain the prospective
replacement bytes.  The canonical control head still binds their predecessor.
For the migration only, this script reconstructs that exact predecessor from a
Git object in a temporary Foundation root.  The StateWriter then authenticates
the old boundary, activates the current bytes, and returns to the normal root.

Omitting ``--apply`` is read-only.  The mutation path requires one unpublished,
fully committed local-main code checkpoint whose parent delivery remains an
ancestor at ``origin/main``.  It then leaves only the exact correction suffix
for a second local commit, so both commits can be delivered by one non-force
fast-forward push.  Stable operation ids allow an interrupted suffix to be
observed safely.  ``--recover`` is an explicit capability for reconciling only
this correction's interrupted Journal suffix before the local-main preflight
and missing-suffix execution.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_projection import (
    prepare_satisfaction_invalidation,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplaySatisfactionInvalidationAuditManifest,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView
from axiom_rift.storage.journal import DurableJournal


PREDECESSOR_COMMIT = "6a09cde22d5f81511f59db3464d804cb34c98ac9"
PREDECESSOR_AUTHORITY_DIGEST = (
    "76358fc4032e756916dc8250c86511e4c6aefcf488940e2a3b47fd3bca07c8a1"
)
AUTHORITY_PATHS_CHANGED = (
    "contracts/evidence.yaml",
    "contracts/operations.yaml",
    "contracts/runtime.yaml",
    "contracts/science.yaml",
)
REVIEWED_AUTHORITY_REPLACEMENT_SHA256 = {
    "contracts/evidence.yaml": (
        "4c030111f4b9db1e03ee85ac17fd776f5c9db6aa89709c1307cca87185409d12"
    ),
    "contracts/operations.yaml": (
        "d7c4c1ac850b266e5526d29c85708de40fe692167034a3bf6dea7773dbf0bd1a"
    ),
    "contracts/runtime.yaml": (
        "aaf31605b22752bc3d6b9a4c5ffb8800a78face6f5d8c36ba6a2dc0c9da55c73"
    ),
    "contracts/science.yaml": (
        "53cf5dade48c9df2c055edd48e507eaafdc4ec196e193533ea83e26d7e7c1ba6"
    ),
}
REPLAY_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
)
HISTORICAL_FAMILY_SOURCE = (
    "src/axiom_rift/research/historical_family_stu0061.py"
)
REVIEWED_HISTORICAL_FAMILY_SOURCE_SHA256 = (
    "215282cdc5a63d11d248817be5dc0e807aa3d882429625e71ba33099ca073ee4"
)
AUTHORITY_OPERATION_ID = "mis0006-exhaustive-audit-authority-v1"
INVALIDATION_OPERATION_ID = "mis0006-stu0061-satisfaction-invalidation-v1"
REVIEWED_INVALIDATION_MANIFEST_SHA256 = (
    "bd4fb7dec0854a3ce08468bacc9a89c416aa3b272f9f46d8ac8e29356fdac883"
)
AUTHORITY_REASON = (
    "bind exhaustive audit repair replay and prospective judgment contracts"
)
LOCAL_GIT_TIMEOUT_SECONDS = 2 * 60
CORRECTION_JOURNAL_EVENT_UPPER_BOUND = 2
_JOURNAL_EVENT_FIELDS = {
    "control",
    "event_id",
    "event_kind",
    "index_projection_digest",
    "index_record_count",
    "index_records",
    "journal_offset",
    "occurred_at_utc",
    "operation_id",
    "payload",
    "previous_event_id",
    "schema",
    "sequence",
    "subject",
}


def _historical_family_authority() -> HistoricalFamilyAuthority:
    source = ROOT / HISTORICAL_FAMILY_SOURCE
    if source.is_file() and sha256(source.read_bytes()).hexdigest() != (
        REVIEWED_HISTORICAL_FAMILY_SOURCE_SHA256
    ):
        raise RuntimeError("reviewed STU-0061 family source bytes drifted")
    family = historical_family_from_manifest(
        STU0061_HISTORICAL_FAMILY.manifest()
    )
    authority = HistoricalFamilyAuthority(
        replay_obligation_id=REPLAY_OBLIGATION_ID,
        family=family,
        reconstruction_source_path=HISTORICAL_FAMILY_SOURCE,
        reconstruction_source_sha256=(
            REVIEWED_HISTORICAL_FAMILY_SOURCE_SHA256
        ),
        reconstruction_only_parameter_names=("family_id",),
    )
    if (
        family.original_study_id != "STU-0061"
        or family.target_historical_executable_id
        != STU0061_HISTORICAL_FAMILY.target_historical_executable_id
    ):
        raise RuntimeError("reviewed STU-0061 historical family drifted")
    return authority


def _historical_family_authority_record(
    authority: HistoricalFamilyAuthority,
) -> IndexRecord:
    return IndexRecord(
        kind="historical-family-authority",
        record_id=authority.identity,
        subject=f"ReplayObligation:{REPLAY_OBLIGATION_ID}",
        status="accepted",
        fingerprint=authority.identity.removeprefix(
            "historical-family-authority:"
        ),
        payload=authority.to_identity_payload(),
    )


def _accepted_historical_family_authorities(
    index: LocalIndex | LocalIndexView,
) -> tuple[IndexRecord, ...]:
    subject = f"ReplayObligation:{REPLAY_OBLIGATION_ID}"
    return tuple(
        record
        for record in index.records_by_subject_status(subject, "accepted")
        if record.kind == "historical-family-authority"
    )


def _require_no_prior_historical_family_authority(
    index: LocalIndex | LocalIndexView,
) -> None:
    if _accepted_historical_family_authorities(index):
        raise RuntimeError(
            "recovery refuses a pre-existing or duplicate accepted "
            "historical family authority"
        )


def _require_canonical_historical_family_authority(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    *,
    event: Mapping[str, object],
    operation_record: IndexRecord,
    result: Mapping[str, object],
) -> None:
    authority = _historical_family_authority()
    expected = _historical_family_authority_record(authority)
    accepted = _accepted_historical_family_authorities(index)
    canonical = index.get("historical-family-authority", authority.identity)
    rows = event.get("index_records")
    family_rows = (
        []
        if not isinstance(rows, list)
        else [
            row
            for row in rows
            if isinstance(row, Mapping)
            and row.get("kind") == "historical-family-authority"
        ]
    )
    expected_mapping = writer._index_mapping(expected)
    if (
        len(accepted) != 1
        or accepted[0].record_id != authority.identity
        or canonical is None
        or writer._index_mapping(canonical) != expected_mapping
        or canonical.authority_sequence != operation_record.authority_sequence
        or canonical.authority_event_id != operation_record.authority_event_id
        or canonical.authority_offset != operation_record.authority_offset
        or family_rows != [expected_mapping]
        or result.get("historical_family_authority_id") != authority.identity
    ):
        raise RuntimeError(
            "canonical historical family authority is not atomic or unique"
        )


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=check,
        capture_output=True,
        timeout=LOCAL_GIT_TIMEOUT_SECONDS,
    )


def _git_text(*arguments: str) -> str:
    return _git(*arguments).stdout.decode("ascii").strip()


def _predecessor_bytes(relative: str) -> bytes:
    result = _git("show", f"{PREDECESSOR_COMMIT}:{relative}")
    if not result.stdout:
        raise RuntimeError(f"predecessor authority is empty: {relative}")
    return result.stdout


def _control() -> dict[str, object]:
    try:
        value = json.loads((ROOT / "state" / "control.json").read_text("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("canonical control is unavailable") from exc
    if not isinstance(value, dict) or not isinstance(value.get("authority"), dict):
        raise RuntimeError("canonical control authority is malformed")
    return value


def _authority_paths(control: Mapping[str, object]) -> tuple[str, ...]:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise RuntimeError("canonical authority manifest is absent")
    operating = authority.get("operating_direction")
    contracts = authority.get("contracts")
    foundation = authority.get("foundation_inputs")
    if (
        not isinstance(operating, str)
        or not isinstance(contracts, list)
        or not isinstance(foundation, list)
        or any(not isinstance(item, str) for item in [*contracts, *foundation])
    ):
        raise RuntimeError("canonical authority path inventory is malformed")
    paths = tuple([operating, *contracts, *foundation])
    if len(paths) != len(set(paths)):
        raise RuntimeError("canonical authority paths are duplicated")
    return paths


def _manifest_digest(paths: tuple[str, ...], *, root: Path = ROOT) -> str:
    hashes = {
        relative: sha256((root / relative).read_bytes()).hexdigest()
        for relative in paths
    }
    return canonical_digest(
        domain="authority-manifest",
        payload=dict(sorted(hashes.items())),
    )


def _authority_replacements(
    paths: tuple[str, ...],
) -> dict[str, bytes]:
    changed: dict[str, bytes] = {}
    for relative in paths:
        current = (ROOT / relative).read_bytes()
        if current != _predecessor_bytes(relative):
            changed[relative] = current
    if tuple(sorted(changed)) != AUTHORITY_PATHS_CHANGED:
        raise RuntimeError(
            "authority drift differs from the reviewed four-contract replacement"
        )
    observed = {
        relative: sha256(content).hexdigest()
        for relative, content in sorted(changed.items())
    }
    if observed != REVIEWED_AUTHORITY_REPLACEMENT_SHA256:
        raise RuntimeError(
            "authority replacement bytes differ from the exact reviewed checkpoint"
        )
    return changed


def _authority_migration_spec(
    paths: tuple[str, ...],
) -> dict[str, object]:
    replacements = _authority_replacements(paths)
    reviewed = _reviewed_authority_migration_spec(paths)
    prospective_digest = _manifest_digest(paths)
    if prospective_digest != reviewed["prospective_digest"]:
        raise RuntimeError(
            "authority replacement manifest differs from the reviewed checkpoint"
        )
    return {**reviewed, "replacements": replacements}


def _reviewed_authority_migration_spec(
    paths: tuple[str, ...],
) -> dict[str, object]:
    """Rebuild the immutable migration identity without current worktree bytes."""

    if tuple(sorted(REVIEWED_AUTHORITY_REPLACEMENT_SHA256)) != (
        AUTHORITY_PATHS_CHANGED
    ):
        raise RuntimeError("reviewed authority replacement inventory drifted")
    predecessor_hashes = {
        relative: sha256(_predecessor_bytes(relative)).hexdigest()
        for relative in paths
    }
    predecessor_digest = canonical_digest(
        domain="authority-manifest",
        payload=dict(sorted(predecessor_hashes.items())),
    )
    if predecessor_digest != PREDECESSOR_AUTHORITY_DIGEST:
        raise RuntimeError("Git predecessor does not match canonical authority")
    prospective_hashes = {
        **predecessor_hashes,
        **REVIEWED_AUTHORITY_REPLACEMENT_SHA256,
    }
    prospective_digest = canonical_digest(
        domain="authority-manifest",
        payload=dict(sorted(prospective_hashes.items())),
    )
    rows = [
        {
            "artifact_sha256": REVIEWED_AUTHORITY_REPLACEMENT_SHA256[relative],
            "new_sha256": REVIEWED_AUTHORITY_REPLACEMENT_SHA256[relative],
            "old_sha256": predecessor_hashes[relative],
            "path": relative,
        }
        for relative in AUTHORITY_PATHS_CHANGED
    ]
    payload = {
        "boundary": "active_stable",
        "holdout_delta": 0,
        "new_manifest_digest": prospective_digest,
        "old_manifest_digest": PREDECESSOR_AUTHORITY_DIGEST,
        "reason": AUTHORITY_REASON,
        "replacements": rows,
        "schema": "authority_manifest_migration.v1",
        "scientific_claim": "none",
        "trial_delta": 0,
    }
    return {
        "migration_id": canonical_digest(
            domain="authority-manifest-migration",
            payload=payload,
        ),
        "payload": payload,
        "prospective_digest": prospective_digest,
    }


def _reviewed_invalidation_manifest(
    plan: object,
) -> ReplaySatisfactionInvalidationAuditManifest:
    if (
        not isinstance(plan, Mapping)
        or set(plan)
        != {
            "audit_manifest",
            "audit_manifest_sha256",
            "operation",
            "schema",
        }
        or plan.get("schema") != "replay_satisfaction_invalidation_plan.v1"
        or plan.get("operation")
        != "invalidate_historical_replay_satisfaction"
        or plan.get("audit_manifest_sha256")
        != REVIEWED_INVALIDATION_MANIFEST_SHA256
        or sha256(canonical_bytes(plan.get("audit_manifest"))).hexdigest()
        != REVIEWED_INVALIDATION_MANIFEST_SHA256
    ):
        raise RuntimeError(
            "replay invalidation plan differs from the reviewed manifest"
        )
    try:
        manifest = ReplaySatisfactionInvalidationAuditManifest.from_mapping(
            plan["audit_manifest"]
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "reviewed replay invalidation manifest is malformed"
        ) from exc
    if manifest.obligation_id != REPLAY_OBLIGATION_ID:
        raise RuntimeError(
            "reviewed replay invalidation manifest targets another obligation"
        )
    return manifest


def _opened_reviewed_invalidation_manifest(
    writer: StateWriter,
) -> ReplaySatisfactionInvalidationAuditManifest:
    try:
        manifest_bytes = writer.evidence.read_verified(
            REVIEWED_INVALIDATION_MANIFEST_SHA256
        )
        manifest = ReplaySatisfactionInvalidationAuditManifest.from_bytes(
            manifest_bytes
        )
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "correction lacks the reviewed invalidation manifest"
        ) from exc
    if (
        sha256(manifest_bytes).hexdigest()
        != REVIEWED_INVALIDATION_MANIFEST_SHA256
        or canonical_bytes(manifest.to_identity_payload()) != manifest_bytes
        or manifest.obligation_id != REPLAY_OBLIGATION_ID
    ):
        raise RuntimeError("correction invalidation manifest differs from review")
    return manifest


def _evidence_manifest(content: bytes) -> dict[str, object]:
    digest = sha256(content).hexdigest()
    return {
        "relative_path": f"sha256/{digest[:2]}/{digest}",
        "sha256": digest,
        "size_bytes": len(content),
    }


def _verified_evidence_manifests(
    writer: StateWriter,
    contents: tuple[bytes, ...],
) -> list[dict[str, object]]:
    manifests: list[dict[str, object]] = []
    observed: set[str] = set()
    for content in contents:
        digest = sha256(content).hexdigest()
        if digest in observed:
            continue
        observed.add(digest)
        try:
            durable = writer.evidence.read_verified(digest)
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise RuntimeError(
                "correction recovery lacks its exact durable evidence"
            ) from exc
        if durable != content:
            raise RuntimeError(
                "correction recovery evidence differs from its reviewed bytes"
            )
        manifests.append(_evidence_manifest(content))
    return manifests


def _operation_index_record(
    *,
    operation_id: str,
    event_kind: str,
    subject: str,
    committed_payload: Mapping[str, object],
    result: Mapping[str, object],
) -> IndexRecord:
    return IndexRecord(
        kind="operation",
        record_id=operation_id,
        subject=subject,
        status="success",
        fingerprint=canonical_digest(
            domain="operation",
            payload={
                "event_kind": event_kind,
                "payload": dict(committed_payload),
            },
        ),
        payload={"event_kind": event_kind, "result": dict(result)},
    )


def _require_prefix_index(
    index: LocalIndex | LocalIndexView,
    *,
    control: Mapping[str, object],
) -> None:
    heads = control.get("heads")
    index_head = None if not isinstance(heads, Mapping) else heads.get("index")
    journal_head = None if not isinstance(heads, Mapping) else heads.get("journal")
    if not isinstance(index_head, Mapping) or not isinstance(journal_head, Mapping):
        raise RuntimeError("correction recovery control heads are malformed")
    digest, valid = index.projection_guard()
    if (
        not valid
        or index.record_count() != index_head.get("required_record_count")
        or digest != index_head.get("required_projection_digest")
        or index_head.get("required_sequence") != journal_head.get("sequence")
    ):
        raise RuntimeError(
            "correction recovery index is not the exact control-head projection"
        )


def _require_exact_suffix_event(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    *,
    event: Mapping[str, object],
    expected_event_kind: str,
    expected_operation_id: str,
    expected_subject: str,
    expected_payload: Mapping[str, object],
    expected_control: Mapping[str, object],
    expected_records: tuple[IndexRecord, ...],
) -> None:
    expected_mappings = [
        writer._index_mapping(record) for record in expected_records
    ]
    if (
        set(event) != _JOURNAL_EVENT_FIELDS
        or event.get("schema") != "journal_event"
        or event.get("event_kind") != expected_event_kind
        or event.get("operation_id") != expected_operation_id
        or event.get("subject") != expected_subject
        or event.get("payload") != dict(expected_payload)
        or event.get("control") != dict(expected_control)
        or event.get("index_records") != expected_mappings
        or event.get("index_record_count")
        != index.record_count() + 1 + len(expected_records)
        or event.get("index_projection_digest")
        != index.projected_digest(expected_records)
    ):
        raise RuntimeError(
            f"recovery refuses a foreign {expected_event_kind} Journal suffix"
        )


def _require_exact_authority_suffix(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    *,
    control: Mapping[str, object],
    paths: tuple[str, ...],
    event: Mapping[str, object],
) -> None:
    if (
        event.get("event_kind") != "authority_migrated"
        or event.get("operation_id") != AUTHORITY_OPERATION_ID
        or event.get("subject") != "Authority:active"
    ):
        raise RuntimeError("recovery refuses a foreign authority Journal suffix")
    spec = _authority_migration_spec(paths)
    migration_payload = spec["payload"]
    replacements = spec["replacements"]
    prospective_digest = spec["prospective_digest"]
    migration_id = spec["migration_id"]
    assert isinstance(migration_payload, Mapping)
    assert isinstance(replacements, Mapping)
    assert isinstance(prospective_digest, str)
    assert isinstance(migration_id, str)
    evidence = _verified_evidence_manifests(
        writer,
        tuple(replacements[relative] for relative in sorted(replacements)),
    )
    committed_payload = {**dict(migration_payload), "evidence": evidence}
    result = {
        "migration_id": migration_id,
        "new_manifest_digest": prospective_digest,
    }
    body = writer._body(dict(control))
    body["authority"]["manifest_digest"] = prospective_digest
    operation = _operation_index_record(
        operation_id=AUTHORITY_OPERATION_ID,
        event_kind="authority_migrated",
        subject="Authority:active",
        committed_payload=committed_payload,
        result=result,
    )
    migration = IndexRecord(
        kind="authority-migration",
        record_id=migration_id,
        subject="Authority:active",
        status="activated",
        fingerprint=migration_id,
        payload=dict(migration_payload),
    )
    _require_exact_suffix_event(
        writer,
        index,
        event=event,
        expected_event_kind="authority_migrated",
        expected_operation_id=AUTHORITY_OPERATION_ID,
        expected_subject="Authority:active",
        expected_payload=committed_payload,
        expected_control=body,
        expected_records=(operation, migration),
    )


def _require_exact_invalidation_suffix(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    *,
    control: Mapping[str, object],
    event: Mapping[str, object],
) -> None:
    if (
        event.get("event_kind")
        != "historical_replay_satisfaction_invalidated"
        or event.get("operation_id") != INVALIDATION_OPERATION_ID
        or event.get("subject") != "Mission:active"
    ):
        raise RuntimeError("recovery refuses a foreign invalidation Journal suffix")
    manifest = _opened_reviewed_invalidation_manifest(writer)
    science = control.get("scientific")
    next_action = control.get("next_action")
    mission_id = (
        None if not isinstance(science, Mapping) else science.get("active_mission")
    )
    if not isinstance(mission_id, str) or not isinstance(next_action, Mapping):
        raise RuntimeError("correction recovery lacks a stable Mission boundary")
    _require_no_prior_historical_family_authority(index)
    records, constraints, result = prepare_satisfaction_invalidation(
        index,
        mission_id=mission_id,
        obligation_id=REPLAY_OBLIGATION_ID,
        manifest=manifest,
        audit_manifest_hash=REVIEWED_INVALIDATION_MANIFEST_SHA256,
    )
    family_authority = _historical_family_authority()
    family_record = _historical_family_authority_record(family_authority)
    records.append(family_record)
    result = {
        **result,
        "historical_family_authority_id": family_authority.identity,
    }
    _validate_invalidation_result(
        result,
        expected_satisfaction_record_id=manifest.satisfaction_record_id,
    )
    committed_payload = {
        "audit_manifest_hash": REVIEWED_INVALIDATION_MANIFEST_SHA256,
        "historical_family_authority": (
            family_authority.to_identity_payload()
        ),
        "obligation_id": REPLAY_OBLIGATION_ID,
        "satisfaction_record_id": manifest.satisfaction_record_id,
        "evidence": [],
    }
    body = writer._body(dict(control))
    body["next_action"] = writer._with_replay_scheduler_constraints(
        dict(next_action),
        constraints,
    )
    operation = _operation_index_record(
        operation_id=INVALIDATION_OPERATION_ID,
        event_kind="historical_replay_satisfaction_invalidated",
        subject="Mission:active",
        committed_payload=committed_payload,
        result=result,
    )
    _require_exact_suffix_event(
        writer,
        index,
        event=event,
        expected_event_kind="historical_replay_satisfaction_invalidated",
        expected_operation_id=INVALIDATION_OPERATION_ID,
        expected_subject="Mission:active",
        expected_payload=committed_payload,
        expected_control=body,
        expected_records=(operation, *records),
    )


@contextmanager
def _predecessor_foundation(paths: tuple[str, ...]) -> Iterator[Path]:
    with TemporaryDirectory(prefix="axiom-authority-predecessor-") as temporary:
        root = Path(temporary).resolve()
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_predecessor_bytes(relative))
        if _manifest_digest(paths, root=root) != PREDECESSOR_AUTHORITY_DIGEST:
            raise RuntimeError("Git predecessor does not match canonical authority")
        yield root


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_authority_result(
    result: object,
    *,
    expected_authority_digest: str,
    expected_migration_id: str,
) -> Mapping[str, object]:
    if (
        not isinstance(result, Mapping)
        or set(result) != {"migration_id", "new_manifest_digest"}
        or result.get("new_manifest_digest") != expected_authority_digest
        or result.get("migration_id") != expected_migration_id
        or not _is_digest(expected_migration_id)
    ):
        raise RuntimeError("authority migration operation result is not exact")
    return result


def _validate_invalidation_result(
    result: object,
    *,
    expected_satisfaction_record_id: str,
) -> Mapping[str, object]:
    if not isinstance(result, Mapping) or set(result) != {
        "audit_manifest_hash",
        "candidate_delta",
        "holdout_reveal_delta",
        "historical_family_authority_id",
        "invalidated_satisfaction_record_id",
        "pending_replay_obligation_ids",
        "replay_obligation_id",
        "scientific_claim_delta",
        "scientific_satisfaction_delta",
        "scientific_trial_delta",
    }:
        raise RuntimeError("replay invalidation operation result is malformed")
    pending_ids = result.get("pending_replay_obligation_ids")
    satisfaction_id = result.get("invalidated_satisfaction_record_id")
    if (
        result.get("replay_obligation_id") != REPLAY_OBLIGATION_ID
        or result.get("historical_family_authority_id")
        != _historical_family_authority().identity
        or any(
            result.get(field) != 0
            for field in (
                "candidate_delta",
                "holdout_reveal_delta",
                "scientific_claim_delta",
                "scientific_satisfaction_delta",
                "scientific_trial_delta",
            )
        )
        or result.get("audit_manifest_hash")
        != REVIEWED_INVALIDATION_MANIFEST_SHA256
        or satisfaction_id != expected_satisfaction_record_id
        or not isinstance(satisfaction_id, str)
        or not satisfaction_id.startswith("historical-replay-satisfaction:")
        or not _is_digest(satisfaction_id.removeprefix("historical-replay-satisfaction:"))
        or not isinstance(pending_ids, list)
        or any(not isinstance(item, str) for item in pending_ids)
        or pending_ids != [REPLAY_OBLIGATION_ID]
    ):
        raise RuntimeError("replay invalidation operation result is not exact")
    return result


def _operation(
    writer: StateWriter,
    operation_id: str,
    *,
    expected_event_kind: str,
    expected_authority_digest: str | None = None,
    expected_migration_id: str | None = None,
    expected_obligation_id: str | None = None,
) -> dict[str, object] | None:
    with writer._open_authoritative_index() as index:
        record = index.get("operation", operation_id)
    if record is None:
        return None
    result = record.payload.get("result")
    if (
        record.status != "success"
        or record.payload.get("event_kind") != expected_event_kind
        or not isinstance(result, Mapping)
        or not isinstance(record.authority_sequence, int)
        or not _is_digest(record.authority_event_id)
        or not isinstance(record.authority_offset, int)
        or set(record.payload) != {"event_kind", "result"}
    ):
        raise RuntimeError(f"canonical operation is not successful: {operation_id}")
    event = writer.journal.read_event_at(
        offset=record.authority_offset,
        expected_sequence=record.authority_sequence,
        expected_event_id=record.authority_event_id,
    )
    rows = event.get("index_records")
    if (
        event.get("event_kind") != expected_event_kind
        or event.get("operation_id") != operation_id
        or event.get("subject") != record.subject
        or not isinstance(rows, list)
        or rows.count(writer._index_mapping(record)) != 1
    ):
        raise RuntimeError(f"canonical operation is cross-event: {operation_id}")
    if expected_authority_digest is not None:
        if expected_migration_id is None:
            raise RuntimeError("authority migration identity expectation is absent")
        _validate_authority_result(
            result,
            expected_authority_digest=expected_authority_digest,
            expected_migration_id=expected_migration_id,
        )
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise RuntimeError("authority migration Journal payload is malformed")
        evidence = payload.get("evidence")
        migration_payload = {
            key: value for key, value in payload.items() if key != "evidence"
        }
        if (
            not isinstance(evidence, list)
            or canonical_digest(
                domain="authority-manifest-migration",
                payload=migration_payload,
            )
            != expected_migration_id
        ):
            raise RuntimeError("authority migration Journal payload is not exact")
    if expected_obligation_id is not None:
        if expected_obligation_id != REPLAY_OBLIGATION_ID:
            raise RuntimeError("unexpected replay invalidation obligation")
        manifest = _opened_reviewed_invalidation_manifest(writer)
        _validate_invalidation_result(
            result,
            expected_satisfaction_record_id=manifest.satisfaction_record_id,
        )
        if event.get("payload") != {
            "audit_manifest_hash": REVIEWED_INVALIDATION_MANIFEST_SHA256,
            "evidence": [],
            "historical_family_authority": (
                _historical_family_authority().to_identity_payload()
            ),
            "obligation_id": REPLAY_OBLIGATION_ID,
            "satisfaction_record_id": manifest.satisfaction_record_id,
        }:
            raise RuntimeError("replay invalidation Journal payload is not exact")
        with writer._open_authoritative_index() as index:
            _require_canonical_historical_family_authority(
                writer,
                index,
                event=event,
                operation_record=record,
                result=result,
            )
    return {
        "authority_event_id": record.authority_event_id,
        "authority_sequence": record.authority_sequence,
        "event_kind": record.payload.get("event_kind"),
        "operation_id": operation_id,
        "result": dict(result),
    }


def _reviewed_authority_operation(
    writer: StateWriter,
    *,
    paths: tuple[str, ...],
) -> dict[str, object] | None:
    """Validate the exact correction event even after later authority changes."""

    spec = _reviewed_authority_migration_spec(paths)
    prospective_digest = spec["prospective_digest"]
    migration_id = spec["migration_id"]
    migration_payload = spec["payload"]
    assert isinstance(prospective_digest, str)
    assert isinstance(migration_id, str)
    assert isinstance(migration_payload, Mapping)
    operation = _operation(
        writer,
        AUTHORITY_OPERATION_ID,
        expected_event_kind="authority_migrated",
        expected_authority_digest=prospective_digest,
        expected_migration_id=migration_id,
    )
    if operation is None:
        return None
    with writer._open_authoritative_index() as index:
        record = index.get("operation", AUTHORITY_OPERATION_ID)
    if record is None:
        raise RuntimeError("authority migration operation disappeared")
    event = writer.journal.read_event_at(
        offset=record.authority_offset,
        expected_sequence=record.authority_sequence,
        expected_event_id=record.authority_event_id,
    )
    contents: list[bytes] = []
    for relative in AUTHORITY_PATHS_CHANGED:
        digest = REVIEWED_AUTHORITY_REPLACEMENT_SHA256[relative]
        try:
            contents.append(writer.evidence.read_verified(digest))
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise RuntimeError(
                "completed correction lacks reviewed authority evidence"
            ) from exc
    expected_payload = {
        **dict(migration_payload),
        "evidence": [_evidence_manifest(content) for content in contents],
    }
    if event.get("payload") != expected_payload:
        raise RuntimeError(
            "completed authority correction differs from the reviewed event"
        )
    return operation


def _require_recoverable_suffix(
    writer: StateWriter,
    *,
    control: Mapping[str, object],
    paths: tuple[str, ...],
) -> str:
    """Allow projection-only repair or one exact correction Journal event."""

    heads = control.get("heads")
    if not isinstance(heads, Mapping) or not isinstance(heads.get("journal"), Mapping):
        raise RuntimeError("canonical control Journal head is malformed")
    journal_head = heads["journal"]
    sequence = journal_head.get("sequence")
    event_id = journal_head.get("event_id")
    if type(sequence) is not int or sequence < 1 or not isinstance(event_id, str):
        raise RuntimeError("canonical control Journal head is malformed")
    events = writer.journal.read_all()
    if sequence > len(events) or events[sequence - 1].get("event_id") != event_id:
        raise RuntimeError("canonical control does not name a Journal prefix")
    suffix = events[sequence:]
    if not suffix:
        return "projection_only"
    if len(suffix) != 1:
        raise RuntimeError("recovery refuses a multi-event Journal suffix")
    event = suffix[0]
    if (
        event.get("sequence") != sequence + 1
        or event.get("previous_event_id") != event_id
    ):
        raise RuntimeError("recovery Journal suffix is not contiguous")
    active_digest = control.get("authority", {}).get("manifest_digest")  # type: ignore[union-attr]
    prospective_digest = _manifest_digest(paths)
    with writer._open_authoritative_index() as index:
        _require_prefix_index(index, control=control)
        if active_digest == PREDECESSOR_AUTHORITY_DIGEST:
            _require_exact_authority_suffix(
                writer,
                index,
                control=control,
                paths=paths,
                event=event,
            )
            return "authority_migrated"
        if active_digest == prospective_digest:
            _require_exact_invalidation_suffix(
                writer,
                index,
                control=control,
                event=event,
            )
            return "historical_replay_satisfaction_invalidated"
    raise RuntimeError("recovery control authority is not a correction boundary")


@contextmanager
def _control_authority_writer(
    control: Mapping[str, object],
    paths: tuple[str, ...],
) -> Iterator[StateWriter]:
    active_digest = control.get("authority", {}).get("manifest_digest")  # type: ignore[union-attr]
    prospective_digest = _manifest_digest(paths)
    if active_digest == PREDECESSOR_AUTHORITY_DIGEST:
        with _predecessor_foundation(paths) as foundation_root:
            yield StateWriter(ROOT, foundation_root=foundation_root)
        return
    if active_digest == prospective_digest:
        yield StateWriter(ROOT)
        return
    raise RuntimeError("control authority is neither predecessor nor replacement")


def _prepare_projection(*, explicit_recovery: bool) -> dict[str, object]:
    control = _control()
    paths = _authority_paths(control)
    with _control_authority_writer(control, paths) as writer:
        try:
            stable = writer.require_stable_head()
        except RecoveryRequired:
            if not explicit_recovery:
                raise
            suffix = _require_recoverable_suffix(
                writer,
                control=control,
                paths=paths,
            )
            return {
                "mode": "explicit_recovery",
                "recoverable_suffix": suffix,
                **writer.recover(),
            }
    return {
        "control_revision": stable["control_revision"],
        "index_record_count": stable["index_record_count"],
        "journal_event_id": stable["journal_event_id"],
        "mode": "stable_head_no_recovery",
        "projection_digest": stable["projection_digest"],
    }


def _journal_worktree_path() -> str:
    manifest_path = ROOT / "records" / "journal" / "manifest.json"
    if not manifest_path.exists():
        legacy = ROOT / "records" / "journal.jsonl"
        if not legacy.is_file():
            raise RuntimeError("canonical Journal path is unavailable")
        return "records/journal.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("canonical Journal manifest is malformed") from exc
    active = None if not isinstance(manifest, Mapping) else manifest.get("active_segment")
    relative = None if not isinstance(active, Mapping) else active.get("path")
    if (
        manifest.get("schema") != "journal_manifest_v1"
        or not isinstance(relative, str)
        or not relative.startswith("records/journal/")
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or not (ROOT / relative).is_file()
    ):
        raise RuntimeError("canonical Journal active path is malformed")
    return relative


def _git_ref_blob(ref: str, relative: str) -> bytes:
    return _git("show", f"{ref}:{relative}").stdout


def _git_blob(relative: str) -> bytes:
    return _git_ref_blob("HEAD", relative)


def _require_local_authority_code_checkpoint(
    paths: tuple[str, ...],
) -> None:
    replacements = _authority_replacements(paths)
    for relative in paths:
        current = (ROOT / relative).read_bytes()
        if _git_ref_blob("HEAD", relative) != current:
            raise RuntimeError(
                "authority-changing code must be fully committed at local main HEAD"
            )
        if _git_ref_blob("origin/main", relative) != _predecessor_bytes(relative):
            raise RuntimeError(
                "origin/main authority is outside the reviewed predecessor boundary"
            )
    if {
        relative: sha256(_git_ref_blob("HEAD", relative)).hexdigest()
        for relative in sorted(replacements)
    } != REVIEWED_AUTHORITY_REPLACEMENT_SHA256:
        raise RuntimeError(
            "local main HEAD lacks the exact reviewed authority replacement bytes"
        )


def _require_local_baseline_at_head() -> str:
    journal_path = _journal_worktree_path()
    baseline_paths = ["state/control.json", journal_path]
    manifest_path = "records/journal/manifest.json"
    if (ROOT / manifest_path).is_file():
        baseline_paths.append(manifest_path)
    for relative in baseline_paths:
        head = _git_ref_blob("HEAD", relative)
        origin = _git_ref_blob("origin/main", relative)
        if head != origin:
            raise RuntimeError(
                "local code checkpoint changed the canonical control or Journal baseline"
            )
        if relative == manifest_path and (ROOT / relative).read_bytes() != head:
            raise RuntimeError(
                "Journal manifest worktree bytes differ from local main HEAD"
            )
    return journal_path


def _require_correction_journal_headroom(
    *,
    control: Mapping[str, object],
    journal_path: str,
) -> dict[str, object]:
    """Prove that this bounded one-off correction cannot rotate a segment."""

    try:
        baseline_control = json.loads(
            _git_blob("state/control.json").decode("ascii")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local HEAD correction control is malformed") from exc
    baseline_heads = (
        None
        if not isinstance(baseline_control, Mapping)
        else baseline_control.get("heads")
    )
    baseline_journal_head = (
        None
        if not isinstance(baseline_heads, Mapping)
        else baseline_heads.get("journal")
    )
    current_heads = control.get("heads")
    current_journal_head = (
        None if not isinstance(current_heads, Mapping) else current_heads.get("journal")
    )
    baseline_sequence = (
        None
        if not isinstance(baseline_journal_head, Mapping)
        else baseline_journal_head.get("sequence")
    )
    current_sequence = (
        None
        if not isinstance(current_journal_head, Mapping)
        else current_journal_head.get("sequence")
    )
    if (
        isinstance(baseline_sequence, bool)
        or not isinstance(baseline_sequence, int)
        or baseline_sequence < 1
        or isinstance(current_sequence, bool)
        or not isinstance(current_sequence, int)
        or current_sequence < baseline_sequence
    ):
        raise RuntimeError("correction Journal sequence boundary is malformed")
    already_present = current_sequence - baseline_sequence
    if already_present > CORRECTION_JOURNAL_EVENT_UPPER_BOUND:
        raise RuntimeError("correction Journal delta exceeds its two-event boundary")
    remaining = CORRECTION_JOURNAL_EVENT_UPPER_BOUND - already_present
    manifest_path = ROOT / "records" / "journal" / "manifest.json"
    if not manifest_path.is_file():
        return {
            "already_present": already_present,
            "correction_event_upper_bound": CORRECTION_JOURNAL_EVENT_UPPER_BOUND,
            "layout": "legacy",
            "remaining": remaining,
            "schema": "authority_correction_journal_headroom.v1",
            "segmented_rollover_allowed": False,
        }
    try:
        manifest = json.loads(manifest_path.read_text("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("canonical Journal manifest is malformed") from exc
    active = None if not isinstance(manifest, Mapping) else manifest.get(
        "active_segment"
    )
    first_sequence = (
        None if not isinstance(active, Mapping) else active.get("first_sequence")
    )
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema") != "journal_manifest_v1"
        or not isinstance(active, Mapping)
        or active.get("path") != journal_path
        or isinstance(first_sequence, bool)
        or not isinstance(first_sequence, int)
        or first_sequence < 1
        or current_sequence < first_sequence - 1
    ):
        raise RuntimeError("canonical Journal headroom boundary is malformed")
    active_path = ROOT / journal_path
    try:
        active_size = active_path.stat().st_size
    except OSError as exc:
        raise RuntimeError("canonical Journal active segment is unavailable") from exc
    active_event_count = max(0, current_sequence - first_sequence + 1)
    event_upper_bound = CORRECTION_JOURNAL_EVENT_UPPER_BOUND
    correction_byte_upper_bound = event_upper_bound * DurableJournal.MAX_EVENT_BYTES
    remaining_byte_upper_bound = remaining * DurableJournal.MAX_EVENT_BYTES
    if (
        active_event_count + remaining
        > DurableJournal.MAX_SEGMENT_EVENTS
        or active_size + remaining_byte_upper_bound
        > DurableJournal.MAX_SEGMENT_BYTES
    ):
        raise RuntimeError(
            "correction lacks exact two-event Journal segment headroom; "
            "segmented rollover is not authorized by this one-off delivery"
        )
    return {
        "active_event_count": active_event_count,
        "active_segment_bytes": active_size,
        "already_present": already_present,
        "correction_event_byte_upper_bound": correction_byte_upper_bound,
        "correction_event_upper_bound": event_upper_bound,
        "layout": "segmented",
        "max_segment_bytes": DurableJournal.MAX_SEGMENT_BYTES,
        "max_segment_events": DurableJournal.MAX_SEGMENT_EVENTS,
        "remaining": remaining,
        "remaining_event_byte_upper_bound": remaining_byte_upper_bound,
        "schema": "authority_correction_journal_headroom.v1",
        "segmented_rollover_allowed": False,
    }


def _require_head_correction_suffix(
    writer: StateWriter,
    *,
    control: Mapping[str, object],
    paths: tuple[str, ...],
) -> tuple[str, ...]:
    journal_path = _journal_worktree_path()
    baseline_control_bytes = _git_blob("state/control.json")
    baseline_journal_bytes = _git_blob(journal_path)
    try:
        baseline_control = json.loads(baseline_control_bytes.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("delivered control blob is malformed") from exc
    baseline_heads = (
        None
        if not isinstance(baseline_control, Mapping)
        else baseline_control.get("heads")
    )
    baseline_journal_head = (
        None
        if not isinstance(baseline_heads, Mapping)
        else baseline_heads.get("journal")
    )
    baseline_authority = (
        None
        if not isinstance(baseline_control, Mapping)
        else baseline_control.get("authority")
    )
    current_heads = control.get("heads")
    current_journal_head = (
        None if not isinstance(current_heads, Mapping) else current_heads.get("journal")
    )
    current_authority = control.get("authority")
    if (
        not isinstance(baseline_journal_head, Mapping)
        or not isinstance(baseline_authority, Mapping)
        or not isinstance(current_journal_head, Mapping)
        or not isinstance(current_authority, Mapping)
    ):
        raise RuntimeError("local HEAD correction control heads are malformed")
    baseline_sequence = baseline_journal_head.get("sequence")
    baseline_event_id = baseline_journal_head.get("event_id")
    events = writer.journal.read_all()
    if (
        type(baseline_sequence) is not int
        or baseline_sequence < 1
        or not isinstance(baseline_event_id, str)
        or baseline_sequence > len(events)
        or events[baseline_sequence - 1].get("event_id") != baseline_event_id
    ):
        raise RuntimeError("local HEAD Journal is not a prefix of correction state")
    suffix = tuple(events[baseline_sequence:])
    observed = tuple(
        (event.get("operation_id"), event.get("event_kind")) for event in suffix
    )
    baseline_digest = baseline_authority.get("manifest_digest")
    prospective_digest = _manifest_digest(paths)
    if baseline_digest == PREDECESSOR_AUTHORITY_DIGEST:
        allowed = {
            (),
            ((AUTHORITY_OPERATION_ID, "authority_migrated"),),
            (
                (AUTHORITY_OPERATION_ID, "authority_migrated"),
                (
                    INVALIDATION_OPERATION_ID,
                    "historical_replay_satisfaction_invalidated",
                ),
            ),
        }
        expected_digest = (
            PREDECESSOR_AUTHORITY_DIGEST if not suffix else prospective_digest
        )
    elif baseline_digest == prospective_digest:
        allowed = {
            (),
            (
                (
                    INVALIDATION_OPERATION_ID,
                    "historical_replay_satisfaction_invalidated",
                ),
            ),
        }
        expected_digest = prospective_digest
    else:
        raise RuntimeError("local HEAD authority is outside the correction boundary")
    if observed not in allowed:
        raise RuntimeError("Git delivery guard refuses a foreign correction suffix")
    expected_sequence = baseline_sequence + len(suffix)
    expected_event_id = baseline_event_id if not suffix else suffix[-1].get("event_id")
    if (
        current_authority.get("manifest_digest") != expected_digest
        or current_journal_head.get("sequence") != expected_sequence
        or current_journal_head.get("event_id") != expected_event_id
    ):
        raise RuntimeError("correction state differs from its exact Journal suffix")
    current_control_bytes = (ROOT / "state" / "control.json").read_bytes()
    current_journal_bytes = (ROOT / journal_path).read_bytes()
    if (
        not current_journal_bytes.startswith(baseline_journal_bytes)
        or bool(suffix)
        != (current_journal_bytes != baseline_journal_bytes)
        or bool(suffix)
        != (current_control_bytes != baseline_control_bytes)
    ):
        raise RuntimeError("correction working bytes are not an append-only Git suffix")
    expected_changed = (
        ("state/control.json", journal_path) if suffix else ()
    )
    migration_spec = _authority_migration_spec(paths)
    migration_id = migration_spec["migration_id"]
    assert isinstance(migration_id, str)
    for operation_id, event_kind in observed:
        if operation_id == AUTHORITY_OPERATION_ID:
            operation = _operation(
                writer,
                AUTHORITY_OPERATION_ID,
                expected_event_kind=event_kind,
                expected_authority_digest=prospective_digest,
                expected_migration_id=migration_id,
            )
        elif operation_id == INVALIDATION_OPERATION_ID:
            operation = _operation(
                writer,
                INVALIDATION_OPERATION_ID,
                expected_event_kind=event_kind,
                expected_obligation_id=REPLAY_OBLIGATION_ID,
            )
        else:  # pragma: no cover - guarded by the exact allowed suffix above.
            raise RuntimeError("Git delivery guard found a foreign operation")
        if operation is None:
            raise RuntimeError("Git delivery guard lost a correction operation")
    return expected_changed


def _require_local_main_checkpoint(
    writer: StateWriter,
    *,
    control: Mapping[str, object],
    paths: tuple[str, ...],
) -> dict[str, object]:
    if _git_text("branch", "--show-current") != "main":
        raise RuntimeError("correction apply requires local main")
    head = _git_text("rev-parse", "HEAD")
    origin = _git_text("rev-parse", "origin/main")
    if head == origin:
        raise RuntimeError(
            "correction apply requires an unpublished local authority code checkpoint"
        )
    ancestry = _git(
        "merge-base",
        "--is-ancestor",
        "origin/main",
        "HEAD",
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError(
            "correction apply refuses divergent or non-ancestor origin/main"
        )
    if _git("diff", "--cached", "--quiet", check=False).returncode != 0:
        raise RuntimeError("correction apply requires an empty Git index")
    _require_local_authority_code_checkpoint(paths)
    journal_path = _require_local_baseline_at_head()
    journal_headroom = _require_correction_journal_headroom(
        control=control,
        journal_path=journal_path,
    )
    expected_changed = _require_head_correction_suffix(
        writer,
        control=control,
        paths=paths,
    )
    changed = tuple(sorted(
        line
        for line in _git_text("diff", "--name-only").splitlines()
        if line
    ))
    if changed != tuple(sorted(expected_changed)):
        raise RuntimeError(
            "correction apply has unrelated or undelivered tracked changes"
        )
    untracked_correction = tuple(
        line
        for line in _git_text(
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "state/control.json",
            "records/journal",
            "records/journal.jsonl",
        ).splitlines()
        if line
    )
    if untracked_correction:
        raise RuntimeError("correction apply has a foreign untracked Journal path")
    return {
        "code_checkpoint_head": head,
        "correction_commit_paths": ["state/control.json", journal_path],
        "delivery_mode": "single_non_force_fast_forward_push_after_correction_commit",
        "force_push_allowed": False,
        "journal_headroom": journal_headroom,
        "origin_main": origin,
        "origin_main_is_strict_ancestor": True,
        "schema": "authority_correction_local_main_boundary.v1",
    }


def _read_only_plan() -> dict[str, object]:
    control = _control()
    paths = _authority_paths(control)
    active_digest = control["authority"]["manifest_digest"]  # type: ignore[index]
    reviewed = _reviewed_authority_migration_spec(paths)
    prospective_digest = reviewed["prospective_digest"]
    assert isinstance(prospective_digest, str)
    plan: dict[str, object] | None = None
    authority_operation: dict[str, object] | None = None
    invalidation_operation: dict[str, object] | None = None
    mode = "pending_correction"
    if active_digest == PREDECESSOR_AUTHORITY_DIGEST:
        replacements = _authority_replacements(paths)
        with _predecessor_foundation(paths) as foundation_root:
            writer = StateWriter(ROOT, foundation_root=foundation_root)
            writer.require_stable_head()
            plan = writer.plan_historical_replay_satisfaction_invalidation(
                obligation_id=REPLAY_OBLIGATION_ID
            )
            _reviewed_invalidation_manifest(plan)
    else:
        writer = StateWriter(ROOT)
        writer.require_stable_head()
        authority_operation = _reviewed_authority_operation(
            writer,
            paths=paths,
        )
        if authority_operation is None:
            raise RuntimeError(
                "active authority lacks the reviewed correction ancestor"
            )
        invalidation_operation = _operation(
            writer,
            INVALIDATION_OPERATION_ID,
            expected_event_kind="historical_replay_satisfaction_invalidated",
            expected_obligation_id=REPLAY_OBLIGATION_ID,
        )
        if invalidation_operation is not None:
            mode = "completed_immutable_ancestor"
        else:
            if active_digest != prospective_digest:
                raise RuntimeError(
                    "incomplete correction was superseded by later authority"
                )
            _authority_replacements(paths)
            plan = writer.plan_historical_replay_satisfaction_invalidation(
                obligation_id=REPLAY_OBLIGATION_ID
            )
            _reviewed_invalidation_manifest(plan)
    return {
        "active_authority_manifest_digest": active_digest,
        "authority_operation": authority_operation,
        "authority_operation_id": AUTHORITY_OPERATION_ID,
        "authority_replacement_sha256": dict(
            sorted(REVIEWED_AUTHORITY_REPLACEMENT_SHA256.items())
        ),
        "invalidation_operation": invalidation_operation,
        "invalidation_operation_id": INVALIDATION_OPERATION_ID,
        "historical_family_authority": (
            _historical_family_authority().to_identity_payload()
        ),
        "historical_family_authority_id": (
            _historical_family_authority().identity
        ),
        "mode": mode,
        "prospective_authority_manifest_digest": prospective_digest,
        "replay_invalidation_plan": plan,
        "replay_obligation_id": REPLAY_OBLIGATION_ID,
        "schema": "exhaustive_audit_replay_correction_plan.v1",
    }


def _completed_apply_result(
    plan: Mapping[str, object],
    *,
    recovery: Mapping[str, object],
) -> dict[str, object]:
    return {
        "authority_operation": plan["authority_operation"],
        "authority_transition": None,
        "invalidation_operation": plan["invalidation_operation"],
        "local_main_delivery_boundary": None,
        "recovery": dict(recovery),
        "schema": "exhaustive_audit_replay_correction_result.v1",
        "stable_revision": _control()["revision"],
    }


def _is_superseded_completed_correction(
    plan: Mapping[str, object],
) -> bool:
    """Return whether later authority makes the old delivery path inapplicable."""

    return (
        plan.get("mode") == "completed_immutable_ancestor"
        and plan.get("active_authority_manifest_digest")
        != plan.get("prospective_authority_manifest_digest")
    )


def apply(*, explicit_recovery: bool = False) -> dict[str, object]:
    before: dict[str, object] | None
    try:
        before = _read_only_plan()
    except RecoveryRequired:
        if not explicit_recovery:
            raise
        before = None
    if before is not None and _is_superseded_completed_correction(before):
        return _completed_apply_result(
            before,
            recovery={
                "mode": "not_required_completed_immutable_ancestor",
                "recovery_requested": explicit_recovery,
            },
        )
    recovery = _prepare_projection(explicit_recovery=explicit_recovery)
    if before is None:
        before = _read_only_plan()
    if _is_superseded_completed_correction(before):
        return _completed_apply_result(before, recovery=recovery)
    control = _control()
    active_digest = control["authority"]["manifest_digest"]  # type: ignore[index]
    paths = _authority_paths(control)
    with _control_authority_writer(control, paths) as delivery_writer:
        delivery_writer.require_stable_head()
        delivery_boundary = _require_local_main_checkpoint(
            delivery_writer,
            control=control,
            paths=paths,
        )
    replacements = _authority_replacements(paths)
    migration_spec = _authority_migration_spec(paths)
    migration_id = migration_spec["migration_id"]
    assert isinstance(migration_id, str)
    authority_result: dict[str, object] | None = None
    if active_digest == PREDECESSOR_AUTHORITY_DIGEST:
        with _predecessor_foundation(paths) as foundation_root:
            predecessor_writer = StateWriter(
                ROOT,
                foundation_root=foundation_root,
            )
            transition = predecessor_writer.migrate_authority(
                replacements=replacements,
                reason=AUTHORITY_REASON,
                operation_id=AUTHORITY_OPERATION_ID,
                allow_active_stable_boundary=True,
            )
            authority_result = {
                "event_id": transition.event_id,
                "result": dict(transition.result),
                "reused": transition.reused,
                "revision": transition.revision,
            }

    writer = StateWriter(ROOT)
    stable = writer.require_stable_head()
    expected_digest = before["prospective_authority_manifest_digest"]
    if stable["control"]["authority"]["manifest_digest"] != expected_digest:
        raise RuntimeError("authority migration did not activate the reviewed bytes")
    authority_operation = _operation(
        writer,
        AUTHORITY_OPERATION_ID,
        expected_event_kind="authority_migrated",
        expected_authority_digest=str(expected_digest),
        expected_migration_id=migration_id,
    )
    if authority_operation is None:
        raise RuntimeError("authority migration operation is absent")
    existing = _operation(
        writer,
        INVALIDATION_OPERATION_ID,
        expected_event_kind="historical_replay_satisfaction_invalidated",
        expected_obligation_id=REPLAY_OBLIGATION_ID,
    )
    if existing is not None:
        return {
            "authority_operation": authority_operation,
            "authority_transition": authority_result,
            "invalidation_operation": existing,
            "local_main_delivery_boundary": delivery_boundary,
            "recovery": recovery,
            "schema": "exhaustive_audit_replay_correction_result.v1",
            "stable_revision": stable["control_revision"],
        }

    plan = writer.plan_historical_replay_satisfaction_invalidation(
        obligation_id=REPLAY_OBLIGATION_ID
    )
    _reviewed_invalidation_manifest(plan)
    prior_plan = before.get("replay_invalidation_plan")
    if prior_plan is not None and canonical_bytes(plan) != canonical_bytes(prior_plan):
        raise RuntimeError("replay invalidation plan changed across authority migration")
    manifest_bytes = canonical_bytes(plan["audit_manifest"])
    artifact = writer.evidence.finalize(manifest_bytes)
    if artifact.sha256 != plan["audit_manifest_sha256"]:
        raise RuntimeError("replay invalidation artifact identity drifted")
    transition = writer.invalidate_historical_replay_satisfaction(
        obligation_id=REPLAY_OBLIGATION_ID,
        audit_manifest_hash=artifact.sha256,
        operation_id=INVALIDATION_OPERATION_ID,
        historical_family_authority=_historical_family_authority(),
    )
    return {
        "authority_operation": authority_operation,
        "authority_transition": authority_result,
        "invalidation_transition": {
            "event_id": transition.event_id,
            "result": dict(transition.result),
            "reused": transition.reused,
            "revision": transition.revision,
        },
        "local_main_delivery_boundary": delivery_boundary,
        "recovery": recovery,
        "schema": "exhaustive_audit_replay_correction_result.v1",
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or explicitly apply the current exhaustive-audit authority "
            "and STU-0061 replay-satisfaction correction."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="mutate canonical authority through the typed StateWriter chain",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="explicitly authorize projection recovery before correction apply",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.recover and not arguments.apply:
        raise SystemExit("--recover requires --apply")
    result = (
        apply(explicit_recovery=arguments.recover)
        if arguments.apply
        else _read_only_plan()
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
