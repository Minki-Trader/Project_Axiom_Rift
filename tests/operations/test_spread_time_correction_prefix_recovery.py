from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Sequence

import pytest

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
    require_exact_correction_receipts,
    require_local_main_correction_boundary,
)
from axiom_rift.storage.evidence import EvidenceStore


REPO_ROOT = Path(__file__).resolve().parents[2]
APPLY_SCRIPT = REPO_ROOT / "scripts" / "apply_spread_time_semantics_correction.py"


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def _member_digest(record: Mapping[str, object]) -> str:
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


def _baseline_control(
    *,
    sequence: int,
    event_id: str,
    authority_manifest_digest: str,
    index_record_count: int,
    index_projection_digest: str,
) -> dict[str, object]:
    return _assemble_control(
        body=_control_body(
            authority_manifest_digest=authority_manifest_digest,
        ),
        revision=sequence,
        journal_sequence=sequence,
        journal_event_id=event_id,
        index_record_count=index_record_count,
        index_projection_digest=index_projection_digest,
    )


def _control_body(
    *,
    authority_manifest_digest: str,
    ordinal: int | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "control_state",
        "authority": {"manifest_digest": authority_manifest_digest},
        "mission": {
            "mission_id": "MIS-0006",
            "initiative_id": "INI-0025",
        },
        "next_action": {"kind": "portfolio_decision"},
    }
    if ordinal is not None:
        body["correction"] = {"ordinal": ordinal}
    return body


def _assemble_control(
    *,
    body: Mapping[str, object],
    revision: int,
    journal_sequence: int,
    journal_event_id: str,
    index_record_count: int,
    index_projection_digest: str,
) -> dict[str, object]:
    assert not {"control_hash", "heads", "revision"}.intersection(body)
    assembled = dict(body)
    assembled["revision"] = revision
    assembled["heads"] = {
        "journal": {
            "sequence": journal_sequence,
            "event_id": journal_event_id,
        },
        "index": {
            "required_sequence": journal_sequence,
            "required_record_count": index_record_count,
            "required_projection_digest": index_projection_digest,
        },
    }
    assembled["control_hash"] = canonical_digest(
        domain="control",
        payload=assembled,
    )
    return assembled


def _core(
    *,
    baseline: CorrectionBaseline,
    authority_file: AuthorityFileBinding,
    checkpoint_files: Sequence[object],
    execution_files: Sequence[CorrectionExecutionFileBinding],
) -> CorrectionPlanCore:
    return CorrectionPlanCore(
        operation_namespace="test-spread-time-prefix",
        baseline=baseline,
        prospective_authority_manifest_digest=_digest("prospective-authority"),
        authority_files=(authority_file,),
        code_checkpoint_files=tuple(checkpoint_files),  # type: ignore[arg-type]
        execution_files=tuple(execution_files),
        evidence_bindings=(
            CorrectionEvidenceBinding(
                role="audit-report",
                sha256=_digest("audit-report"),
            ),
        ),
        event_intents=tuple(
            CorrectionEventIntent(
                action=f"step-{ordinal}",
                event_kind=f"spread_time_event_{ordinal}",
                subject=(
                    "Authority:active" if ordinal == 1 else "Mission:active"
                ),
                binding={
                    "ordinal": ordinal,
                    "semantic_record_count": 1,
                },
            )
            for ordinal in range(1, 8)
        ),
        purpose="exercise exact spread/time prefix recovery",
    )


def _events_and_envelope(
    core: CorrectionPlanCore,
) -> tuple[tuple[dict[str, object], ...], CorrectionReceiptEnvelope]:
    events: list[dict[str, object]] = []
    receipts: list[CorrectionEventReceiptBinding] = []
    previous_event_id = core.baseline.journal_event_id
    projection_digest = core.baseline.index_projection_digest
    index_record_count = core.baseline.index_record_count
    journal_offset = (
        core.baseline.journal_start_offset
        + core.baseline.journal_size_bytes
    )
    for intent in core.events:
        payload = {"ordinal": intent.ordinal}
        result = {"ordinal": intent.ordinal}
        operation = {
            "event_sequence": None,
            "event_stream": None,
            "fingerprint": canonical_digest(
                domain="operation",
                payload={"event_kind": intent.event_kind, "payload": payload},
            ),
            "kind": "operation",
            "payload": {"event_kind": intent.event_kind, "result": result},
            "record_id": intent.operation_id,
            "status": "success",
            "subject": intent.subject,
        }
        semantic = {
            "event_sequence": 1,
            "event_stream": f"spread-time-prefix:{intent.ordinal}",
            "fingerprint": _digest(f"semantic-{intent.ordinal}"),
            "kind": "spread-time-prefix-record",
            "payload": {"ordinal": intent.ordinal},
            "record_id": f"spread-time-prefix:{_digest(str(intent.ordinal))}",
            "status": "recorded",
            "subject": intent.subject,
        }
        index_records = [operation, semantic]
        for record in index_records:
            projection_digest = canonical_digest(
                domain="index-projection-chain",
                payload={
                    "member": _member_digest(record),
                    "previous": projection_digest,
                },
            )
        index_record_count += 1 + len(index_records)
        event: dict[str, object] = {
            "control": _control_body(
                authority_manifest_digest=(
                    core.prospective_authority_manifest_digest
                ),
                ordinal=intent.ordinal,
            ),
            "event_id": "",
            "event_kind": intent.event_kind,
            "index_projection_digest": projection_digest,
            "index_record_count": index_record_count,
            "index_records": index_records,
            "journal_offset": journal_offset,
            "occurred_at_utc": (
                f"2000-01-01T00:00:00.{intent.ordinal:06d}Z"
            ),
            "operation_id": intent.operation_id,
            "payload": payload,
            "previous_event_id": previous_event_id,
            "schema": "journal_event",
            "sequence": core.baseline.journal_sequence + intent.ordinal,
            "subject": intent.subject,
        }
        event["event_id"] = canonical_digest(
            domain="journal-event",
            payload={
                key: value for key, value in event.items() if key != "event_id"
            },
        )
        framed_size = len(canonical_bytes(event)) + 1
        receipts.append(
            CorrectionEventReceiptBinding(
                canonical_event_byte_count=framed_size,
                canonical_event_sha256=sha256(
                    canonical_bytes(event)
                ).hexdigest(),
                event_id=event["event_id"],  # type: ignore[arg-type]
                occurred_at_utc=event["occurred_at_utc"],  # type: ignore[arg-type]
                journal_offset=event["journal_offset"],  # type: ignore[arg-type]
                event_payload_sha256=sha256(
                    canonical_bytes(payload)
                ).hexdigest(),
                control_projection_sha256=sha256(
                    canonical_bytes(event["control"])
                ).hexdigest(),
                operation_result_sha256=sha256(
                    canonical_bytes(result)
                ).hexdigest(),
                semantic_index_records_sha256=sha256(
                    canonical_bytes([semantic])
                ).hexdigest(),
                semantic_index_record_count=1,
            )
        )
        journal_offset += framed_size
        previous_event_id = event["event_id"]  # type: ignore[assignment]
        events.append(event)
    return tuple(events), CorrectionReceiptEnvelope(
        core=core,
        event_receipts=tuple(receipts),
    )


def _journal_events(
    core: CorrectionPlanCore,
    suffix: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return (
        *(
            {"event_id": _digest(f"predecessor-{sequence}")}
            for sequence in range(1, core.baseline.journal_sequence)
        ),
        {"event_id": core.baseline.journal_event_id},
        *suffix,
    )


def _control_for_prefix(
    core: CorrectionPlanCore,
    suffix: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not suffix:
        return _baseline_control(
            sequence=core.baseline.journal_sequence,
            event_id=core.baseline.journal_event_id,
            authority_manifest_digest=(
                core.baseline.authority_manifest_digest
            ),
            index_record_count=core.baseline.index_record_count,
            index_projection_digest=(
                core.baseline.index_projection_digest
            ),
        )
    event = suffix[-1]
    body = event["control"]
    assert isinstance(body, Mapping)
    return _assemble_control(
        body=body,
        revision=int(event["sequence"]),
        journal_sequence=int(event["sequence"]),
        journal_event_id=str(event["event_id"]),
        index_record_count=int(event["index_record_count"]),
        index_projection_digest=str(event["index_projection_digest"]),
    )


def _journal_bytes(
    baseline: bytes,
    suffix: Sequence[Mapping[str, object]],
) -> bytes:
    return baseline + b"".join(canonical_bytes(dict(event)) + b"\n" for event in suffix)


@dataclass(frozen=True, slots=True)
class _TempCorrectionRepository:
    root: Path
    core: CorrectionPlanCore
    events: tuple[dict[str, object], ...]
    envelope: CorrectionReceiptEnvelope
    baseline_control_bytes: bytes
    baseline_journal_bytes: bytes

    def write_prefix(
        self,
        count: int,
        *,
        control_count: int | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        suffix = self.events[:count]
        projected = suffix[: count if control_count is None else control_count]
        (self.root / "state" / "control.json").write_bytes(
            canonical_bytes(_control_for_prefix(self.core, projected))
        )
        (self.root / "records" / "journal.jsonl").write_bytes(
            _journal_bytes(self.baseline_journal_bytes, suffix)
        )
        return _journal_events(self.core, suffix)


def _temp_correction_repository(tmp_path: Path) -> _TempCorrectionRepository:
    top = tmp_path / "prefix-repository"
    origin = top / "origin.git"
    root = top / "work"
    top.mkdir()
    _git(top, "init", "--bare", str(origin))
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Axiom Test")
    _git(root, "branch", "-M", "main")

    baseline_sequence = 1
    baseline_event_id = _digest("baseline-event")
    old_manifest = _digest("baseline-authority")
    baseline_index_record_count = 25
    baseline_index_projection_digest = _digest("baseline-projection")
    baseline_control = _baseline_control(
        sequence=baseline_sequence,
        event_id=baseline_event_id,
        authority_manifest_digest=old_manifest,
        index_record_count=baseline_index_record_count,
        index_projection_digest=baseline_index_projection_digest,
    )
    baseline_control_bytes = canonical_bytes(baseline_control)
    baseline_journal_bytes = b"baseline journal bytes\n"
    old_authority = b"old authority\n"
    new_authority = b"new authority\n"
    (root / "state").mkdir()
    (root / "records").mkdir()
    (root / "state" / "control.json").write_bytes(baseline_control_bytes)
    (root / "records" / "journal.jsonl").write_bytes(baseline_journal_bytes)
    (root / "authority.txt").write_bytes(old_authority)
    (root / "runner.py").write_text("VALUE = 1\n", encoding="ascii")
    _git(root, "add", "--", "state/control.json", "records/journal.jsonl")
    _git(root, "add", "--", "authority.txt", "runner.py")
    _git(root, "commit", "-m", "baseline")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-u", "origin", "main")

    (root / "authority.txt").write_bytes(new_authority)
    (root / "runner.py").write_text("VALUE = 2\n", encoding="ascii")
    _git(root, "add", "--", "authority.txt", "runner.py")
    _git(root, "commit", "-m", "unpublished correction checkpoint")
    checkpoint = capture_local_correction_checkpoint(
        root,
        execution_paths=(root / "runner.py",),
    )
    baseline = CorrectionBaseline(
        control_revision=baseline_sequence,
        journal_sequence=baseline_sequence,
        journal_event_id=baseline_event_id,
        journal_path="records/journal.jsonl",
        control_sha256=sha256(baseline_control_bytes).hexdigest(),
        journal_sha256=sha256(baseline_journal_bytes).hexdigest(),
        journal_start_offset=0,
        journal_size_bytes=len(baseline_journal_bytes),
        authority_manifest_digest=old_manifest,
        index_record_count=baseline_index_record_count,
        index_projection_digest=baseline_index_projection_digest,
        mission_id="MIS-0006",
        initiative_id="INI-0025",
        next_action_kind="portfolio_decision",
        code_checkpoint_commit=checkpoint["code_checkpoint_commit"],
        code_checkpoint_tree=checkpoint["code_checkpoint_tree"],
        origin_main_commit=checkpoint["origin_main_commit"],
    )
    core = _core(
        baseline=baseline,
        authority_file=AuthorityFileBinding(
            path="authority.txt",
            predecessor_sha256=sha256(old_authority).hexdigest(),
            prospective_sha256=sha256(new_authority).hexdigest(),
        ),
        checkpoint_files=checkpoint["code_checkpoint_files"],
        execution_files=checkpoint["execution_files"],
    )
    events, envelope = _events_and_envelope(core)
    return _TempCorrectionRepository(
        root=root,
        core=core,
        events=events,
        envelope=envelope,
        baseline_control_bytes=baseline_control_bytes,
        baseline_journal_bytes=baseline_journal_bytes,
    )


def test_temp_repository_accepts_every_exact_prefix_zero_through_seven(
    tmp_path: Path,
) -> None:
    fixture = _temp_correction_repository(tmp_path)
    for prefix_count in range(0, fixture.core.event_count + 1):
        journal_events = fixture.write_prefix(prefix_count)
        suffix = correction_suffix_from_journal(fixture.core, journal_events)
        current_control = _control_for_prefix(fixture.core, suffix)
        result = require_local_main_correction_boundary(
            fixture.root,
            fixture.core,
            current_control=current_control,
            journal_events=journal_events,
        )
        assert len(suffix) == prefix_count
        assert result["structural_core_prefix_count"] == prefix_count
        assert result["projection_prefix_count"] == prefix_count
        unhashed_control = {
            key: value
            for key, value in current_control.items()
            if key != "control_hash"
        }
        assert current_control["control_hash"] == canonical_digest(
            domain="control",
            payload=unhashed_control,
        )
        if suffix:
            trailing = suffix[-1]
            control_body = trailing["control"]
            assert isinstance(control_body, Mapping)
            assert not {"control_hash", "heads", "revision"}.intersection(
                control_body
            )
            assembled_body = {
                key: value
                for key, value in current_control.items()
                if key not in {"control_hash", "heads", "revision"}
            }
            assert canonical_bytes(assembled_body) == canonical_bytes(
                dict(control_body)
            )
            assert current_control["revision"] == trailing["sequence"]
            assert current_control["heads"] == {
                "journal": {
                    "sequence": trailing["sequence"],
                    "event_id": trailing["event_id"],
                },
                "index": {
                    "required_sequence": trailing["sequence"],
                    "required_record_count": trailing[
                        "index_record_count"
                    ],
                    "required_projection_digest": trailing[
                        "index_projection_digest"
                    ],
                },
            }
        assert tuple(
            event.operation_id for event in fixture.core.events[prefix_count:]
        ) == tuple(
            event.operation_id
            for event in fixture.core.events
            if event.ordinal > prefix_count
        )

    full_journal = _journal_events(fixture.core, fixture.events)
    exact = correction_suffix_from_journal(fixture.envelope, full_journal)
    assert require_exact_correction_receipts(fixture.envelope, exact)
    final_boundary = require_local_main_correction_boundary(
        fixture.root,
        fixture.envelope,
        current_control=_control_for_prefix(fixture.core, fixture.events),
        journal_events=full_journal,
    )
    assert final_boundary["plan_artifact_hash"] == fixture.envelope.artifact_hash


def test_temp_repository_one_event_lag_requires_explicit_recovery_and_exact_head(
    tmp_path: Path,
) -> None:
    fixture = _temp_correction_repository(tmp_path)
    journal_events = fixture.write_prefix(1, control_count=0)
    baseline_control = _control_for_prefix(fixture.core, ())

    with pytest.raises(
        ContentAddressedCorrectionError,
        match="control is not an allowed plan prefix",
    ):
        require_local_main_correction_boundary(
            fixture.root,
            fixture.core,
            current_control=baseline_control,
            journal_events=journal_events,
        )
    lag = require_local_main_correction_boundary(
        fixture.root,
        fixture.core,
        current_control=baseline_control,
        journal_events=journal_events,
        allow_one_event_projection_lag=True,
    )
    assert lag["structural_core_prefix_count"] == 1
    assert lag["projection_prefix_count"] == 0

    recovered_control = _control_for_prefix(fixture.core, fixture.events[:1])
    (fixture.root / "state" / "control.json").write_bytes(
        canonical_bytes(recovered_control)
    )
    recovered = require_local_main_correction_boundary(
        fixture.root,
        fixture.core,
        current_control=recovered_control,
        journal_events=journal_events,
    )
    assert recovered["structural_core_prefix_count"] == 1
    assert recovered["projection_prefix_count"] == 1


def test_exact_suffix_replay_rejects_tampering_and_duplicate_events(
    tmp_path: Path,
) -> None:
    fixture = _temp_correction_repository(tmp_path)
    exact = _journal_events(fixture.core, fixture.events[:3])
    assert len(correction_suffix_from_journal(fixture.core, exact)) == 3

    tampered = [dict(event) for event in fixture.events[:3]]
    tampered[1]["payload"] = {"ordinal": 999}
    tampered[1]["event_id"] = canonical_digest(
        domain="journal-event",
        payload={
            key: value
            for key, value in tampered[1].items()
            if key != "event_id"
        },
    )
    with pytest.raises(ContentAddressedCorrectionError):
        correction_suffix_from_journal(
            fixture.core,
            _journal_events(fixture.core, tampered),
        )

    duplicate = (*fixture.events, fixture.events[-1])
    with pytest.raises(ContentAddressedCorrectionError):
        correction_suffix_from_journal(
            fixture.core,
            _journal_events(fixture.core, duplicate),
        )


_APPLY_MODULE: Any | None = None


def _load_apply_module():
    global _APPLY_MODULE
    if _APPLY_MODULE is not None:
        return _APPLY_MODULE
    name = "spread_time_prefix_recovery_apply_for_test"
    spec = importlib.util.spec_from_file_location(name, APPLY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _APPLY_MODULE = module
    return _APPLY_MODULE


@dataclass(frozen=True, slots=True)
class _CostManifest:
    payload: Mapping[str, object]

    @property
    def artifact_hash(self) -> str:
        return sha256(canonical_bytes(dict(self.payload))).hexdigest()

    def to_payload(self) -> dict[str, object]:
        return dict(self.payload)


class _StopAfterExactRecovery(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("explicit_recovery", "suffix_count"),
    ((False, 1), (True, 0), (True, 1)),
    ids=(
        "implicit-positive-suffix",
        "explicit-empty-suffix",
        "explicit-positive-suffix",
    ),
)
def test_apply_recovery_requires_positive_exact_suffix_and_ordered_reproof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_recovery: bool,
    suffix_count: int,
) -> None:
    fixture = _temp_correction_repository(tmp_path)
    module = _load_apply_module()
    suffix = fixture.events[:suffix_count]
    journal_events = _journal_events(fixture.core, suffix)
    baseline_document = canonical_bytes(_control_for_prefix(fixture.core, ()))
    order: list[str] = []
    state = {"lag": True}

    class TrackingEvidenceStore(EvidenceStore):
        def finalize(self, content: bytes):  # type: ignore[no-untyped-def]
            artifact = super().finalize(content)
            order.append(f"finalize:{artifact.sha256}")
            return artifact

        def read_verified(self, identity: str) -> bytes:
            document = super().read_verified(identity)
            order.append(f"read:{identity}")
            return document

    evidence_root = tmp_path / "apply-root" / "local" / "evidence"
    writer_evidence = TrackingEvidenceStore(evidence_root)

    class FakeJournal:
        def read_all(self):  # type: ignore[no-untyped-def]
            return journal_events

    class FakeWriter:
        journal = FakeJournal()
        evidence = writer_evidence

        def _assert_exact_trailing_arguments(
            self,
            *,
            expected_sequence,
            expected_event_id,
            expected_operation_id,
            expected_previous_event_id,
        ):  # type: ignore[no-untyped-def]
            assert suffix
            trailing = suffix[-1]
            assert (
                expected_sequence,
                expected_event_id,
                expected_operation_id,
                expected_previous_event_id,
            ) == (
                trailing["sequence"],
                trailing["event_id"],
                trailing["operation_id"],
                trailing["previous_event_id"],
            )
            return trailing

        def require_stable_head(self):  # type: ignore[no-untyped-def]
            if state["lag"]:
                order.append("stable:lag")
                raise module.RecoveryRequired("one-event projection lag")
            order.append("stable:exact")
            return {"journal_sequence": fixture.core.baseline.journal_sequence + 1}

        def require_exact_trailing_event_recovery_boundary(
            self,
            *,
            expected_sequence,
            expected_event_id,
            expected_operation_id,
            expected_previous_event_id,
        ):  # type: ignore[no-untyped-def]
            self._assert_exact_trailing_arguments(
                expected_sequence=expected_sequence,
                expected_event_id=expected_event_id,
                expected_operation_id=expected_operation_id,
                expected_previous_event_id=expected_previous_event_id,
            )
            order.append("trailing-boundary")
            return {
                "event_id": expected_event_id,
                "operation_id": expected_operation_id,
                "sequence": expected_sequence,
            }

        def recover_exact_trailing_event(
            self,
            *,
            expected_sequence,
            expected_event_id,
            expected_operation_id,
            expected_previous_event_id,
        ):  # type: ignore[no-untyped-def]
            assert any(
                item == f"read:{fixture.core.core_hash}" for item in order
            )
            self._assert_exact_trailing_arguments(
                expected_sequence=expected_sequence,
                expected_event_id=expected_event_id,
                expected_operation_id=expected_operation_id,
                expected_previous_event_id=expected_previous_event_id,
            )
            order.append("atomic-reproof")
            order.append("recover")
            state["lag"] = False
            return {
                "control_repaired": True,
                "recovery_boundary": {
                    "event_id": expected_event_id,
                    "operation_id": expected_operation_id,
                    "sequence": expected_sequence,
                },
            }

        def recover(self):  # type: ignore[no-untyped-def]
            raise AssertionError("generic recovery must remain unreachable")

    writer = FakeWriter()
    cost_manifest = _CostManifest({"schema": "test-cost-manifest.v1"})
    report_bytes = b"spread time recovery report\n"
    replay_document = b"exact replay evidence\n"
    replay_identity = sha256(replay_document).hexdigest()
    material = SimpleNamespace(
        core=fixture.core,
        report_bytes=report_bytes,
        cost_manifest=cost_manifest,
    )

    class ReplayEvidence:
        @staticmethod
        def exact_documents() -> dict[str, bytes]:
            return {replay_identity: replay_document}

    class Replay:
        def __init__(self) -> None:
            self.material = material
            self.replay_evidence = ReplayEvidence()
            self.verified_events: list[Mapping[str, object]] = []

        def verify_prefix(self, actual):  # type: ignore[no-untyped-def]
            assert canonical_bytes(list(actual)) == canonical_bytes(list(suffix))
            self.verified_events = [dict(event) for event in actual]

    replay = Replay()

    @contextmanager
    def replay_session(_core):  # type: ignore[no-untyped-def]
        yield replay

    @contextmanager
    def current_writer_for_plan(
        _core,
        *,
        require_apply_api: bool = False,
    ) -> Iterator[FakeWriter]:
        if require_apply_api:
            raise _StopAfterExactRecovery
        yield writer

    boundary_calls: list[bool] = []

    def boundary(
        _root,
        _core,
        *,
        allow_one_event_projection_lag: bool = False,
        **_kwargs,
    ) -> dict[str, object]:
        boundary_calls.append(allow_one_event_projection_lag)
        order.append(f"boundary:{len(boundary_calls)}")
        if state["lag"] and not allow_one_event_projection_lag:
            raise ContentAddressedCorrectionError(
                "control is not an allowed plan prefix"
            )
        return {
            "projection_prefix_count": (
                0 if state["lag"] else suffix_count
            )
        }

    def writer_factory(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return writer

    monkeypatch.setattr(module, "ROOT", tmp_path / "apply-root")
    monkeypatch.setattr(module, "EvidenceStore", TrackingEvidenceStore)
    monkeypatch.setattr(module, "_require_safe_apply_startup", lambda: None)
    monkeypatch.setattr(module, "_writer", writer_factory)
    monkeypatch.setattr(
        module,
        "_git_blob",
        lambda _ref, _path: baseline_document,
    )
    monkeypatch.setattr(
        module,
        "_durable_core_from_suffix",
        lambda *_args, **_kwargs: fixture.core,
    )
    monkeypatch.setattr(
        module,
        "_require_current_reviewed_execution_closure",
        lambda _core: None,
    )
    monkeypatch.setattr(module, "_open_correction_replay_session", replay_session)
    monkeypatch.setattr(module, "_current_writer_for_plan", current_writer_for_plan)
    monkeypatch.setattr(module, "require_local_main_correction_boundary", boundary)
    monkeypatch.setattr(
        module,
        "_current_control",
        lambda: _control_for_prefix(
            fixture.core,
            () if state["lag"] else suffix,
        ),
    )

    if explicit_recovery and suffix_count:
        with pytest.raises(_StopAfterExactRecovery):
            module.apply(explicit_recovery=True)
        assert boundary_calls == [True, True, False]
        assert order.count("recover") == 1
        first_admission = order.index("boundary:1")
        first_finalize = next(
            index
            for index, item in enumerate(order)
            if item.startswith("finalize:")
        )
        reproof = order.index("boundary:2")
        recovery = order.index("recover")
        assert first_admission < order.index("trailing-boundary")
        assert order.index("trailing-boundary") < first_finalize < reproof
        assert any(
            first_finalize < index < reproof
            and item == f"read:{fixture.core.core_hash}"
            for index, item in enumerate(order)
        )
        atomic_reproof = order.index("atomic-reproof")
        assert order.count("trailing-boundary") == 1
        assert reproof < atomic_reproof < recovery
    elif explicit_recovery:
        with pytest.raises(
            module.RecoveryRequired,
            match="one-event projection lag",
        ):
            module.apply(explicit_recovery=True)
        assert boundary_calls == [True]
        assert order == ["boundary:1", "stable:lag"]
        assert not any(
            item.startswith(("finalize:", "read:")) for item in order
        )
        assert "trailing-boundary" not in order
        assert "atomic-reproof" not in order
        assert "recover" not in order
    else:
        with pytest.raises(
            ContentAddressedCorrectionError,
            match="control is not an allowed plan prefix",
        ):
            module.apply(explicit_recovery=False)
        assert boundary_calls == [False]
        assert order == ["boundary:1"]
        assert "recover" not in order
        assert not any(
            item.startswith(("finalize:", "read:")) for item in order
        )


def test_replay_session_rejects_a_second_prefix_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _temp_correction_repository(tmp_path)
    module = _load_apply_module()
    session = module._CorrectionReplaySession(
        writer=object(),
        material=SimpleNamespace(core=fixture.core),
        replay_evidence=object(),
        baseline_sequence=fixture.core.baseline.journal_sequence,
        receipts=[],
        verified_events=[],
        independent_cursor=object(),
    )

    def accept_for_duplicate_guard(self, event):  # type: ignore[no-untyped-def]
        self.verified_events.append(dict(event))

    monkeypatch.setattr(
        module._CorrectionReplaySession,
        "verify_next",
        accept_for_duplicate_guard,
    )
    session.verify_prefix(fixture.events[:1])
    with pytest.raises(
        module.SpreadTimeCorrectionError,
        match="correction prefix was replayed twice",
    ):
        session.verify_prefix(fixture.events[:1])
