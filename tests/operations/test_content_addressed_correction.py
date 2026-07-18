from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import axiom_rift.operations.content_addressed_correction as correction_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    AuthorityFileBinding,
    ContentAddressedCorrectionError,
    CorrectionBaseline,
    CorrectionEventIntent,
    CorrectionEventReceiptBinding,
    CorrectionEvidenceBinding,
    CorrectionExecutionFileBinding,
    CorrectionPlanCore,
    CorrectionReceiptEnvelope,
    capture_local_correction_checkpoint,
    correction_suffix_from_journal,
    require_correction_journal_storage_headroom,
    require_exact_correction_receipts,
    require_local_main_correction_boundary,
)
from axiom_rift.storage.journal import DurableJournal


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _baseline(
    *,
    journal_bytes: bytes = b"baseline\n",
    checkpoint_commit: str = "1" * 40,
    checkpoint_tree: str = "2" * 40,
    origin_commit: str = "3" * 40,
    control_sha256: str | None = None,
) -> CorrectionBaseline:
    return CorrectionBaseline(
        control_revision=10,
        journal_sequence=10,
        journal_event_id=_digest("event-10"),
        journal_path="records/journal.jsonl",
        control_sha256=control_sha256 or _digest("control"),
        journal_sha256=sha256(journal_bytes).hexdigest(),
        journal_start_offset=0,
        journal_size_bytes=len(journal_bytes),
        authority_manifest_digest=_digest("old-authority"),
        index_record_count=25,
        index_projection_digest=_digest("projection"),
        mission_id="MIS-0006",
        initiative_id="INI-0025",
        next_action_kind="portfolio_decision",
        code_checkpoint_commit=checkpoint_commit,
        code_checkpoint_tree=checkpoint_tree,
        origin_main_commit=origin_commit,
    )


def _core(
    *,
    baseline: CorrectionBaseline | None = None,
    authority_files: tuple[AuthorityFileBinding, ...] | None = None,
    checkpoint_files: tuple[object, ...] = (),
    execution_files: tuple[CorrectionExecutionFileBinding, ...] | None = None,
    prospective_authority_manifest_digest: str | None = None,
) -> CorrectionPlanCore:
    return CorrectionPlanCore(
        operation_namespace="test-correction",
        baseline=baseline or _baseline(),
        prospective_authority_manifest_digest=(
            _digest("new-authority")
            if prospective_authority_manifest_digest is None
            else prospective_authority_manifest_digest
        ),
        authority_files=authority_files
        or (
            AuthorityFileBinding(
                path="authority.txt",
                predecessor_sha256=_digest("old-file"),
                prospective_sha256=_digest("new-file"),
            ),
        ),
        code_checkpoint_files=checkpoint_files,  # type: ignore[arg-type]
        execution_files=execution_files
        or (
            CorrectionExecutionFileBinding(
                path="runner.py",
                sha256=_digest("runner"),
            ),
        ),
        evidence_bindings=(
            CorrectionEvidenceBinding(role="audit-report", sha256=_digest("report")),
        ),
        event_intents=tuple(
            CorrectionEventIntent(
                action=f"step-{ordinal}",
                event_kind=f"event_{ordinal}",
                subject="Authority:active" if ordinal == 1 else "Mission:active",
                binding={"ordinal": ordinal, "semantic_record_count": 1},
            )
            for ordinal in range(1, 8)
        ),
        purpose="exercise exact correction delivery",
    )


def test_implementation_only_correction_binds_unchanged_authority() -> None:
    baseline = _baseline()
    unchanged = AuthorityFileBinding(
        path="authority.txt",
        predecessor_sha256=_digest("same-file"),
        prospective_sha256=_digest("same-file"),
    )
    core = CorrectionPlanCore(
        operation_namespace="implementation-correction",
        baseline=baseline,
        prospective_authority_manifest_digest=(
            baseline.authority_manifest_digest
        ),
        authority_files=(unchanged,),
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
                sha256=_digest("diagnosis-audit"),
            ),
        ),
        event_intents=(
            CorrectionEventIntent(
                action="diagnosis-correction",
                event_kind="study_diagnoses_corrected",
                subject="Mission:MIS-0006",
                binding={"semantic_record_count": 15},
            ),
        ),
        purpose="apply an existing authority without gratuitous migration",
    )
    assert core.authority_replacements == ()
    assert (
        core.prospective_authority_manifest_digest
        == core.baseline.authority_manifest_digest
    )


def test_correction_rejects_authority_bytes_and_manifest_disagreement() -> None:
    baseline = _baseline()
    unchanged = AuthorityFileBinding(
        path="authority.txt",
        predecessor_sha256=_digest("same-file"),
        prospective_sha256=_digest("same-file"),
    )
    with pytest.raises(
        ContentAddressedCorrectionError,
        match="authority inventory is not exact",
    ):
        _core(baseline=baseline, authority_files=(unchanged,))
    changed = AuthorityFileBinding(
        path="authority.txt",
        predecessor_sha256=_digest("old-file"),
        prospective_sha256=_digest("new-file"),
    )
    with pytest.raises(
        ContentAddressedCorrectionError,
        match="authority inventory is not exact",
    ):
        _core(
            baseline=baseline,
            authority_files=(changed,),
            prospective_authority_manifest_digest=(
                baseline.authority_manifest_digest
            ),
        )


def _member_digest(record: dict[str, object]) -> str:
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


def _events_and_envelope(
    core: CorrectionPlanCore,
) -> tuple[list[dict[str, object]], CorrectionReceiptEnvelope]:
    events: list[dict[str, object]] = []
    receipts: list[CorrectionEventReceiptBinding] = []
    previous = core.baseline.journal_event_id
    projection = core.baseline.index_projection_digest
    record_count = core.baseline.index_record_count
    journal_offset = (
        core.baseline.journal_start_offset
        + core.baseline.journal_size_bytes
    )
    for item in core.events:
        payload = {"ordinal": item.ordinal}
        result = {"ordinal": item.ordinal}
        operation = {
            "event_sequence": None,
            "event_stream": None,
            "fingerprint": canonical_digest(
                domain="operation",
                payload={"event_kind": item.event_kind, "payload": payload},
            ),
            "kind": "operation",
            "payload": {"event_kind": item.event_kind, "result": result},
            "record_id": item.operation_id,
            "status": "success",
            "subject": item.subject,
        }
        semantic = {
            "event_sequence": 1,
            "event_stream": f"test:{item.ordinal}",
            "fingerprint": _digest(f"semantic-{item.ordinal}"),
            "kind": "test-semantic",
            "payload": {"ordinal": item.ordinal},
            "record_id": f"test-semantic:{_digest(str(item.ordinal))}",
            "status": "recorded",
            "subject": item.subject,
        }
        rows = [operation, semantic]
        for row in rows:
            projection = canonical_digest(
                domain="index-projection-chain",
                payload={"member": _member_digest(row), "previous": projection},
            )
        record_count += 1 + len(rows)
        event: dict[str, object] = {
            "control": {"ordinal": item.ordinal},
            "event_id": "",
            "event_kind": item.event_kind,
            "index_projection_digest": projection,
            "index_record_count": record_count,
            "index_records": rows,
            "journal_offset": journal_offset,
            "occurred_at_utc": f"2000-01-01T00:00:00.{item.ordinal:06d}Z",
            "operation_id": item.operation_id,
            "payload": payload,
            "previous_event_id": previous,
            "schema": "journal_event",
            "sequence": core.baseline.journal_sequence + item.ordinal,
            "subject": item.subject,
        }
        event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={key: value for key, value in event.items() if key != "event_id"},
        )
        journal_offset += len(canonical_bytes(event)) + 1
        previous = event["event_id"]  # type: ignore[assignment]
        receipts.append(
            CorrectionEventReceiptBinding(
                canonical_event_byte_count=len(canonical_bytes(event)) + 1,
                canonical_event_sha256=sha256(canonical_bytes(event)).hexdigest(),
                event_id=event["event_id"],  # type: ignore[arg-type]
                occurred_at_utc=event["occurred_at_utc"],  # type: ignore[arg-type]
                journal_offset=event["journal_offset"],  # type: ignore[arg-type]
                event_payload_sha256=sha256(canonical_bytes(payload)).hexdigest(),
                control_projection_sha256=sha256(
                    canonical_bytes(event["control"])
                ).hexdigest(),
                operation_result_sha256=sha256(canonical_bytes(result)).hexdigest(),
                semantic_index_records_sha256=sha256(
                    canonical_bytes([semantic])
                ).hexdigest(),
                semantic_index_record_count=1,
            )
        )
        events.append(event)
    return events, CorrectionReceiptEnvelope(
        core=core,
        event_receipts=tuple(receipts),
    )


def _journal(core: CorrectionPlanCore, suffix: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        *(
            {"event_id": _digest(f"old-{ordinal}")}
            for ordinal in range(1, core.baseline.journal_sequence)
        ),
        {"event_id": core.baseline.journal_event_id},
        *suffix,
    ]


def test_core_and_post_execution_envelope_round_trip_are_separate() -> None:
    core = _core()
    rebuilt_core = CorrectionPlanCore.from_bytes(
        core.core_bytes,
        expected_core_hash=core.core_hash,
    )
    events, envelope = _events_and_envelope(core)
    rebuilt_envelope = CorrectionReceiptEnvelope.from_bytes(
        envelope.artifact_bytes,
        expected_artifact_hash=envelope.artifact_hash,
        expected_core_hash=core.core_hash,
    )

    assert rebuilt_core == core
    assert rebuilt_envelope == envelope
    assert all(core.core_hash in item.operation_id for item in core.events)
    assert all(envelope.artifact_hash not in item.operation_id for item in core.events)
    assert len(require_exact_correction_receipts(envelope, events)) == 7


def test_core_receipt_and_exact_size_tampering_fail_closed() -> None:
    core = _core()
    events, envelope = _events_and_envelope(core)

    changed_core = json.loads(core.core_bytes.decode("ascii"))
    changed_core["event_intents"][0]["binding"]["ordinal"] = 99
    with pytest.raises(ContentAddressedCorrectionError):
        CorrectionPlanCore.from_bytes(
            canonical_bytes(changed_core),
            expected_core_hash=core.core_hash,
        )

    changed_envelope = json.loads(envelope.artifact_bytes.decode("ascii"))
    changed_envelope["event_receipts"][0]["receipt"][
        "canonical_event_byte_count"
    ] += 1
    forged = CorrectionReceiptEnvelope.from_bytes(canonical_bytes(changed_envelope))
    with pytest.raises(ContentAddressedCorrectionError):
        require_exact_correction_receipts(forged, events)
    with pytest.raises(ContentAddressedCorrectionError):
        CorrectionReceiptEnvelope.from_bytes(
            canonical_bytes(changed_envelope),
            expected_artifact_hash=envelope.artifact_hash,
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("occurred_at_utc", "2000-01-01T00:00:09Z"),
        ("journal_offset", 9999),
        ("payload", {"ordinal": 99}),
        ("control", {"ordinal": 99}),
        ("index_projection_digest", _digest("foreign-projection")),
    ),
)
def test_self_hashed_event_tampering_is_rejected(
    field: str,
    value: object,
) -> None:
    core = _core()
    events, envelope = _events_and_envelope(core)
    forged = [dict(event) for event in events]
    forged[0][field] = value
    forged[0]["event_id"] = canonical_digest(
        domain="journal-event",
        payload={key: item for key, item in forged[0].items() if key != "event_id"},
    )
    with pytest.raises(ContentAddressedCorrectionError):
        require_exact_correction_receipts(envelope, forged[:1])


def test_core_headroom_uses_journal_max_and_envelope_cannot_authorize_remaining() -> None:
    core = _core()
    _events, envelope = _events_and_envelope(core)
    manifest = {
        "active_segment": {"first_sequence": 1, "path": core.baseline.journal_path},
        "schema": "journal_manifest_v1",
    }
    remaining_bound = core.event_count * DurableJournal.MAX_EVENT_BYTES
    with pytest.raises(ContentAddressedCorrectionError):
        require_correction_journal_storage_headroom(
            core,
            suffix=(),
            journal_manifest=manifest,
            active_segment_bytes=(
                DurableJournal.MAX_SEGMENT_BYTES - remaining_bound + 1
            ),
        )
    with pytest.raises(ContentAddressedCorrectionError):
        require_correction_journal_storage_headroom(
            envelope,
            suffix=(),
            journal_manifest=manifest,
            active_segment_bytes=0,
        )


def _run(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def test_local_guard_allows_unrelated_python_and_rejects_import_load_shadows() -> None:
    with TemporaryDirectory() as temporary:
        top = Path(temporary)
        bare = top / "origin.git"
        root = top / "work"
        _run(top, "init", "--bare", str(bare))
        root.mkdir()
        _run(root, "init")
        _run(root, "config", "core.autocrlf", "false")
        _run(root, "config", "user.email", "test@example.invalid")
        _run(root, "config", "user.name", "Axiom Test")
        _run(root, "branch", "-M", "main")
        (root / "state").mkdir()
        (root / "records").mkdir()
        old_authority = b"old authority\n"
        new_authority = b"new authority\n"
        journal_bytes = b"baseline journal\n"
        event_id = _digest("event-10")
        authority_digest = _digest("old-authority")
        control = {
            "authority": {"manifest_digest": authority_digest},
            "heads": {"journal": {"event_id": event_id, "sequence": 10}},
        }
        control_bytes = canonical_bytes(control)
        (root / "state" / "control.json").write_bytes(control_bytes)
        (root / "records" / "journal.jsonl").write_bytes(journal_bytes)
        (root / "authority.txt").write_bytes(old_authority)
        (root / "runner.py").write_text("VALUE = 1\n", encoding="ascii")
        _run(root, "add", ".")
        _run(root, "commit", "-m", "baseline")
        _run(root, "remote", "add", "origin", str(bare))
        _run(root, "push", "-u", "origin", "main")
        (root / "authority.txt").write_bytes(new_authority)
        (root / "runner.py").write_text("VALUE = 2\n", encoding="ascii")
        _run(root, "add", "authority.txt", "runner.py")
        _run(root, "commit", "-m", "unpublished checkpoint")

        real_subprocess_run = subprocess.run
        checkpoint_git_calls: list[tuple[str, ...]] = []

        def checkpoint_run(*args, **kwargs):
            checkpoint_git_calls.append(tuple(args[0]))
            return real_subprocess_run(*args, **kwargs)

        with patch.object(
            correction_module.subprocess,
            "run",
            side_effect=checkpoint_run,
        ):
            checkpoint = capture_local_correction_checkpoint(
                root,
                execution_paths=(root / "runner.py",),
            )
        assert sum(
            command[1:3] == ("cat-file", "--batch")
            for command in checkpoint_git_calls
        ) == 1
        assert not any(
            command[1] == "show"
            or command[1:3] == ("cat-file", "-e")
            for command in checkpoint_git_calls
        )
        baseline = _baseline(
            journal_bytes=journal_bytes,
            checkpoint_commit=checkpoint["code_checkpoint_commit"],
            checkpoint_tree=checkpoint["code_checkpoint_tree"],
            origin_commit=checkpoint["origin_main_commit"],
            control_sha256=sha256(control_bytes).hexdigest(),
        )
        core = _core(
            baseline=baseline,
            authority_files=(
                AuthorityFileBinding(
                    path="authority.txt",
                    predecessor_sha256=sha256(old_authority).hexdigest(),
                    prospective_sha256=sha256(new_authority).hexdigest(),
                ),
            ),
            checkpoint_files=checkpoint["code_checkpoint_files"],
            execution_files=checkpoint["execution_files"],
        )
        base_journal = _journal(core, [])
        (root / "notes.py").write_text("VALUE = 'unrelated'\n", encoding="ascii")
        boundary_git_calls: list[tuple[str, ...]] = []

        def boundary_run(*args, **kwargs):
            boundary_git_calls.append(tuple(args[0]))
            return real_subprocess_run(*args, **kwargs)

        with patch.object(
            correction_module.subprocess,
            "run",
            side_effect=boundary_run,
        ):
            result = require_local_main_correction_boundary(
                root,
                core,
                current_control=control,
                journal_events=base_journal,
            )
        assert sum(
            command[1:3] == ("cat-file", "--batch")
            for command in boundary_git_calls
        ) == 3
        assert not any(
            command[1] == "show"
            or command[1:3] == ("cat-file", "-e")
            for command in boundary_git_calls
        )
        assert result["structural_core_prefix_count"] == 0
        assert result["excluded_untracked_non_authority_paths"] == ["notes.py"]

        events, _envelope = _events_and_envelope(core)
        event = deepcopy(events[0])
        event["control"] = {
            "authority": {
                "manifest_digest": core.prospective_authority_manifest_digest,
            },
        }
        event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={
                key: value for key, value in event.items() if key != "event_id"
            },
        )
        current_control = deepcopy(event["control"])
        current_control["revision"] = event["sequence"]
        current_control["heads"] = {
            "journal": {
                "event_id": event["event_id"],
                "sequence": event["sequence"],
            },
            "index": {
                "required_sequence": event["sequence"],
                "required_record_count": event["index_record_count"],
                "required_projection_digest": event[
                    "index_projection_digest"
                ],
            },
        }
        current_control["control_hash"] = canonical_digest(
            domain="control",
            payload=current_control,
        )
        (root / "state" / "control.json").write_bytes(
            canonical_bytes(current_control)
        )
        forged_event = deepcopy(event)
        forged_event["occurred_at_utc"] = "2001-01-01T00:00:00.000001Z"
        forged_event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={
                key: value
                for key, value in forged_event.items()
                if key != "event_id"
            },
        )
        (root / "records" / "journal.jsonl").write_bytes(
            journal_bytes + canonical_bytes(forged_event) + b"\n"
        )
        with pytest.raises(
            ContentAddressedCorrectionError,
            match="exact supplied correction prefix",
        ):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=current_control,
                journal_events=_journal(core, [event]),
            )

        (root / "records" / "journal.jsonl").write_bytes(
            journal_bytes + canonical_bytes(event) + b"\n"
        )
        tampered_control = deepcopy(current_control)
        tampered_control["next_action"] = {"kind": "foreign"}
        tampered_control["control_hash"] = canonical_digest(
            domain="control",
            payload={
                key: value
                for key, value in tampered_control.items()
                if key != "control_hash"
            },
        )
        (root / "state" / "control.json").write_bytes(
            canonical_bytes(tampered_control)
        )
        with pytest.raises(
            ContentAddressedCorrectionError,
            match="exact supplied correction prefix",
        ):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=tampered_control,
                journal_events=_journal(core, [event]),
            )

        (root / "state" / "control.json").write_bytes(
            canonical_bytes(current_control) + b" "
        )
        with pytest.raises(
            ContentAddressedCorrectionError,
            match="exact supplied correction prefix",
        ):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=current_control,
                journal_events=_journal(core, [event]),
            )
        (root / "state" / "control.json").write_bytes(control_bytes)
        (root / "records" / "journal.jsonl").write_bytes(journal_bytes)

        (root / "SiteCustomIze.py").write_text("VALUE = 1\n", encoding="ascii")
        with pytest.raises(ContentAddressedCorrectionError):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=control,
                journal_events=base_journal,
            )
        (root / "SiteCustomIze.py").unlink()
        package = root / "sitecustomize"
        package.mkdir()
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="ascii")
        with pytest.raises(ContentAddressedCorrectionError):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=control,
                journal_events=base_journal,
            )
        (package / "__init__.py").unlink()
        package.rmdir()
        (root / "src").mkdir()
        (root / "src" / "shadow.pyd").write_bytes(b"foreign extension")
        with pytest.raises(ContentAddressedCorrectionError):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=control,
                journal_events=base_journal,
            )
        (root / "src" / "shadow.pyd").unlink()
        (root / "scripts").mkdir()
        (root / "scripts" / "sitecustomize.py").write_text(
            "VALUE = 1\n",
            encoding="ascii",
        )
        with pytest.raises(ContentAddressedCorrectionError):
            require_local_main_correction_boundary(
                root,
                core,
                current_control=control,
                journal_events=base_journal,
            )
        (root / "scripts" / "sitecustomize.py").unlink()
        (root / "scripts").rmdir()

        tracked_attack: Path | None = None
        for relative in (
            "SiteCustomIze/__init__.py",
            "src/shadow.pyd",
            "scripts/usercustomize/__init__.py",
            "usercustomize.pyc",
        ):
            if tracked_attack is not None:
                tracked_attack.unlink()
                parent = tracked_attack.parent
                if parent != root and not any(parent.iterdir()):
                    parent.rmdir()
                _run(
                    root,
                    "add",
                    "-u",
                    "--",
                    tracked_attack.relative_to(root).as_posix(),
                )
            tracked_attack = root / relative
            tracked_attack.parent.mkdir(parents=True, exist_ok=True)
            tracked_attack.write_bytes(b"tracked automatic load shadow")
            _run(root, "add", "--", relative)
            _run(root, "commit", "-m", f"tracked attack {relative}")
            attack_checkpoint = capture_local_correction_checkpoint(
                root,
                execution_paths=(root / "runner.py",),
            )
            attack_core = _core(
                baseline=_baseline(
                    journal_bytes=journal_bytes,
                    checkpoint_commit=attack_checkpoint[
                        "code_checkpoint_commit"
                    ],
                    checkpoint_tree=attack_checkpoint["code_checkpoint_tree"],
                    origin_commit=attack_checkpoint["origin_main_commit"],
                    control_sha256=sha256(control_bytes).hexdigest(),
                ),
                authority_files=(
                    AuthorityFileBinding(
                        path="authority.txt",
                        predecessor_sha256=sha256(old_authority).hexdigest(),
                        prospective_sha256=sha256(new_authority).hexdigest(),
                    ),
                ),
                checkpoint_files=attack_checkpoint["code_checkpoint_files"],
                execution_files=attack_checkpoint["execution_files"],
            )
            with pytest.raises(
                ContentAddressedCorrectionError,
                match="tracked Python automatic-load or binary shadow",
            ):
                require_local_main_correction_boundary(
                    root,
                    attack_core,
                    current_control=control,
                    journal_events=_journal(attack_core, []),
                )
