from __future__ import annotations

import ast
from contextlib import closing, ExitStack
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import PermitAuthority
from axiom_rift.operations.writer import InjectedCrash, RecoveryRequired, StateWriter
from axiom_rift.research import historical_study_registry
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    ReplaySatisfaction,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.journal import DurableJournal
from tests.operations import test_replay_projection as replay_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "apply_exhaustive_audit_replay_correction.py"
SPEC = importlib.util.spec_from_file_location(
    "apply_exhaustive_audit_replay_correction_for_test",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUBJECT)

AUTHORITY_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)
CHANGED_PATH = "contracts/evidence.yaml"
MISSION_ID = replay_fixture.MISSION_ID
RECORD_KINDS = (
    "batch-close",
    "batch-open",
    "historical-replay-obligation",
    "historical-replay-obligation-resolution",
    "historical-scientific-adjudication",
    "job-completed",
    "job-declared",
    "portfolio-decision",
    "study-close",
    "study-diagnosis",
    "study-open",
    "trial",
)


def _downgrade_projection_to_v1(path: Path) -> None:
    """Create a real legacy query surface from an isolated current index."""

    with closing(sqlite3.connect(path)) as connection, connection:
        triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND ("
            "name LIKE 'component_surface_%' OR "
            "name LIKE '%controlled_chassis_study%')"
        ).fetchall()
        for (name,) in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE component_surface_bindings")
        connection.execute("DROP TABLE component_surface_stats")
        connection.execute("DROP TABLE controlled_chassis_study_stats")
        indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name LIKE 'ix_records_kind_payload_%'"
        ).fetchall()
        for (name,) in indexes:
            connection.execute(f'DROP INDEX "{name}"')
        connection.execute("PRAGMA user_version = 1")


def _projection_snapshot(path: Path) -> tuple[bytes, int, int, tuple[str, ...]]:
    payload = path.read_bytes()
    metadata = path.stat()
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    return (
        payload,
        metadata.st_size,
        version,
        tuple(sorted(item.name for item in path.parent.iterdir())),
    )


class CorrectionSourceBoundaryTests(unittest.TestCase):
    def test_correction_source_has_no_mutable_index_open(self) -> None:
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="ascii"))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        direct_constructors = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("_open_authoritative_index", called_attributes)
        self.assertNotIn(
            "_open_mutable_authoritative_index",
            called_attributes,
        )
        self.assertNotIn("_open_mutable_recovery_index", called_attributes)
        self.assertNotIn("LocalIndex", direct_constructors)


class CorrectionFixture:
    def __init__(self, temporary: str) -> None:
        base = Path(temporary)
        self.root = base / "root"
        self.predecessor_root = base / "predecessor"
        self.materialized_predecessor_root = base / "materialized-predecessor"
        self.git_requires_recovered_head = False
        self.git_observations = 0
        self.git_head = "b" * 40
        self.git_origin = "a" * 40
        self.git_origin_is_ancestor = True
        self.git_index_clean = True
        for relative in AUTHORITY_PATHS:
            content = (REPO_ROOT / relative).read_bytes()
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            predecessor = self.predecessor_root / relative
            predecessor.parent.mkdir(parents=True, exist_ok=True)
            predecessor.write_bytes(content)
        historical_family_source = self.root / SUBJECT.HISTORICAL_FAMILY_SOURCE
        historical_family_source.parent.mkdir(parents=True, exist_ok=True)
        historical_family_source.write_bytes(
            b"# isolated reviewed historical family source fixture\n"
        )
        self.reviewed_historical_family_source_sha256 = sha256(
            historical_family_source.read_bytes()
        ).hexdigest()
        predecessor_contract = self.predecessor_root / CHANGED_PATH
        predecessor_contract.write_bytes(
            predecessor_contract.read_bytes()
            + b"\n# correction recovery fixture predecessor\n"
        )
        for relative in AUTHORITY_PATHS:
            materialized = self.materialized_predecessor_root / relative
            materialized.parent.mkdir(parents=True, exist_ok=True)
            materialized.write_bytes((self.predecessor_root / relative).read_bytes())
        self.predecessor_writer = self.writer(
            foundation_root=self.materialized_predecessor_root
        )
        self.predecessor_writer.initialize_ready(
            operation_id="fixture-ready-boundary"
        )
        self.predecessor_writer.open_mission(
            mission_id=MISSION_ID,
            goal={
                "objective": "exercise correction recovery",
                "scope": ["isolated", "engineering_fixture"],
                "terminal_contract": "no_scientific_terminal",
            },
            operation_id="fixture-open-mission",
        )
        self.obligation_id = self._seed_invalid_satisfaction()
        control = self.predecessor_writer.read_control()
        assert control is not None
        self.paths = SUBJECT._authority_paths(control)
        self.predecessor_digest = SUBJECT._manifest_digest(
            self.paths,
            root=self.predecessor_root,
        )
        self.prospective_digest = SUBJECT._manifest_digest(
            self.paths,
            root=self.root,
        )
        self.reviewed_authority_replacement_sha256 = {
            CHANGED_PATH: sha256(
                (self.root / CHANGED_PATH).read_bytes()
            ).hexdigest()
        }
        plan = self.predecessor_writer.plan_historical_replay_satisfaction_invalidation(
            obligation_id=self.obligation_id
        )
        self.reviewed_manifest_sha256 = plan["audit_manifest_sha256"]
        self.git_blobs = self._capture_git_blobs()
        self.git_blob_overrides: dict[str, bytes] = {}
        self.origin_blob_overrides: dict[str, bytes] = {}
        self.extra_changed_paths: set[str] = set()
        self.untracked_correction_paths: set[str] = set()

    def writer(self, root: Path | None = None, **kwargs) -> StateWriter:
        return StateWriter(
            self.root if root is None else root,
            permit_authority=PermitAuthority(b"p" * 32),
            clock=lambda: "2026-07-15T00:00:00Z",
            engineering_fixture=True,
            **kwargs,
        )

    def _seed_invalid_satisfaction(self) -> str:
        scratch_path = self.root.parent / "scratch" / "index.sqlite"
        scratch_path.parent.mkdir(parents=True, exist_ok=True)
        with LocalIndex(scratch_path) as scratch:
            helper = replay_fixture.MultiplicityReplaySatisfactionTests(
                "test_exact_e01_membership_defect_round_trips_and_requeues"
            )
            helper.index = scratch
            original_obligation, original_satisfaction = helper._seed_satisfied(
                wrong_registration_member=4
            )
            original_obligation_payload = (
                original_obligation.to_identity_payload()
            )
            member_parameters = tuple(
                {"fixture_ordinal": ordinal}
                for ordinal in range(1, 5)
            )
            member_executables = tuple(
                {
                    "parameters": parameters,
                    "schema": "historical_fixture.v1",
                }
                for parameters in member_parameters
            )
            member_ids = tuple(
                "executable:"
                + canonical_digest(
                    domain="executable",
                    payload=executable,
                )
                for executable in member_executables
            )
            obligation = HistoricalReplayObligation(
                governing_mission_id=original_obligation_payload[
                    "governing_mission_id"
                ],
                historical_adjudication_id=original_obligation_payload[
                    "historical_adjudication_id"
                ],
                replay_priority=original_obligation.replay_priority,
                original_study_id="STU-0061",
                original_study_close_record_id=original_obligation_payload[
                    "original_study_close_record_id"
                ],
                original_completion_record_id=original_obligation_payload[
                    "original_completion_record_id"
                ],
                original_executable_id=member_ids[0],
                audit_artifact_hash=original_obligation_payload[
                    "audit_artifact_hash"
                ],
                validation_plan_hash=original_obligation_payload[
                    "validation_plan_hash"
                ],
                measurement_artifact_hash=original_obligation_payload[
                    "measurement_artifact_hash"
                ],
                claim_ids=tuple(original_obligation_payload["claim_ids"]),
                criterion_ids=tuple(
                    original_obligation_payload["criterion_ids"]
                ),
                reason_codes=tuple(original_obligation_payload["reason_codes"]),
            )
            original_satisfaction_payload = (
                original_satisfaction.to_identity_payload()
            )
            satisfaction = ReplaySatisfaction(
                obligation_id=obligation.identity,
                resolution_scope=original_satisfaction.resolution_scope,
                portfolio_decision_id=original_satisfaction_payload[
                    "portfolio_decision_id"
                ],
                replay_study_id=original_satisfaction_payload["replay_study_id"],
                replay_executable_id=original_satisfaction_payload[
                    "replay_executable_id"
                ],
                replay_study_close_record_id=original_satisfaction_payload[
                    "replay_study_close_record_id"
                ],
                study_diagnosis_id=original_satisfaction_payload[
                    "study_diagnosis_id"
                ],
                satisfied_criterion_ids=tuple(
                    original_satisfaction_payload["satisfied_criterion_ids"]
                ),
                evidence_record_ids=tuple(
                    original_satisfaction_payload["evidence_record_ids"]
                ),
                remaining_scientific_condition=(
                    original_satisfaction_payload[
                        "remaining_scientific_condition"
                    ]
                ),
            )
            study_hash = "6" * 64
            batch_spec = {
                "acceptance_profile": {
                    "concurrent_family": {
                        "evaluation_mode": "sequential",
                        "executable_ids": list(member_ids),
                        "family_size": len(member_ids),
                        "schema": "concurrent_family_manifest.v1",
                    }
                },
                "max_trials": len(member_ids),
                "study_hash": study_hash,
            }
            batch_digest = canonical_digest(
                domain="batch-spec",
                payload=batch_spec,
            )
            batch_id = f"batch:{batch_digest}"
            members = tuple(
                HistoricalMemberSpec(
                    ordinal=ordinal,
                    configuration_id=f"fixture-family-member-{ordinal}",
                    historical_reference_executable_id=executable_id,
                    parameters=member_parameters[ordinal - 1],
                )
                for ordinal, executable_id in enumerate(member_ids, start=1)
            )
            controls = (
                ControlBinding(
                    subject_historical_executable_id=member_ids[0],
                    opposite_historical_executable_id=member_ids[1],
                    feature_historical_executable_ids=(member_ids[2],),
                ),
                ControlBinding(
                    subject_historical_executable_id=member_ids[1],
                    opposite_historical_executable_id=member_ids[0],
                    feature_historical_executable_ids=(member_ids[3],),
                ),
                ControlBinding(
                    subject_historical_executable_id=member_ids[2],
                    opposite_historical_executable_id=member_ids[3],
                    feature_historical_executable_ids=(member_ids[0],),
                ),
                ControlBinding(
                    subject_historical_executable_id=member_ids[3],
                    opposite_historical_executable_id=member_ids[2],
                    feature_historical_executable_ids=(member_ids[1],),
                ),
            )
            family = HistoricalFamilySpec(
                original_study_id="STU-0061",
                original_batch_id=batch_id,
                target_historical_executable_id=obligation.original_executable_id,
                members=members,
                controls=controls,
            )
            self.historical_family_authority = HistoricalFamilyAuthority(
                replay_obligation_id=obligation.identity,
                family=family,
                reconstruction_source_path=SUBJECT.HISTORICAL_FAMILY_SOURCE,
                reconstruction_source_sha256=(
                    self.reviewed_historical_family_source_sha256
                ),
            )
            scratch.put_many(
                (
                    IndexRecord(
                        kind="study-open",
                        record_id="STU-0061",
                        subject="Study:STU-0061",
                        status="closed",
                        fingerprint=study_hash,
                        payload={
                            "mission_id": "MIS-HIST-MULTIPLICITY",
                            "portfolio_axis_id": "axis-original-multiplicity",
                            "portfolio_axis_identity": "axis:" + "4" * 64,
                        },
                    ),
                    IndexRecord(
                        kind="batch-open",
                        record_id=batch_id,
                        subject="Study:STU-0061",
                        status="open",
                        fingerprint=batch_digest,
                        payload={
                            "batch_hash": batch_digest,
                            "spec": batch_spec,
                        },
                    ),
                    *tuple(
                        IndexRecord(
                            kind="trial",
                            record_id=executable_id,
                            subject=f"Batch:{batch_id}",
                            status="evaluated",
                            fingerprint=executable_id.removeprefix("executable:"),
                            payload={
                                "executable": member_executables[ordinal - 1],
                                "mission_id": "MIS-HIST-MULTIPLICITY",
                                "portfolio_axis_id": "axis-original-multiplicity",
                                "portfolio_axis_identity": "axis:" + "4" * 64,
                                "study_id": "STU-0061",
                            },
                            event_stream=f"batch-trials:{batch_id}",
                            event_sequence=ordinal,
                        )
                        for ordinal, executable_id in enumerate(
                            member_ids,
                            start=1,
                        )
                    ),
                    IndexRecord(
                        kind="job-declared",
                        record_id="job:" + "5" * 64,
                        subject="Job:job:" + "5" * 64,
                        status="declared",
                        fingerprint="5" * 64,
                        payload={
                            "mission_id": "MIS-HIST-MULTIPLICITY",
                            "study_id": "STU-0061",
                            "spec": {
                                "evidence_subject": {
                                    "id": obligation.original_executable_id,
                                    "kind": "Executable",
                                }
                            },
                        },
                    ),
                    IndexRecord(
                        kind="job-completed",
                        record_id=obligation.original_completion_record_id,
                        subject="Job:job:" + "5" * 64,
                        status="success",
                        fingerprint="2" * 64,
                        payload={
                            "job_id": "job:" + "5" * 64,
                            "scientific": {
                                "executable_id": obligation.original_executable_id
                            },
                        },
                    ),
                    IndexRecord(
                        kind="study-close",
                        record_id=obligation.original_study_close_record_id,
                        subject="Study:STU-0061",
                        status="failed",
                        fingerprint="5" * 64,
                        payload={"study_id": "STU-0061"},
                    ),
                    IndexRecord(
                        kind="historical-replay-obligation",
                        record_id=obligation.identity,
                        subject=f"Mission:{obligation.governing_mission_id}",
                        status="pending",
                        fingerprint=obligation.identity.removeprefix(
                            "historical-replay-obligation:"
                        ),
                        payload={
                            "obligation": obligation.to_identity_payload()
                        },
                        event_stream=(
                            f"historical-replay-obligation:{obligation.identity}"
                        ),
                        event_sequence=1,
                    ),
                    IndexRecord(
                        kind="historical-replay-obligation-resolution",
                        record_id=satisfaction.identity,
                        subject=f"Mission:{obligation.governing_mission_id}",
                        status="satisfied",
                        fingerprint=satisfaction.identity.removeprefix(
                            "historical-replay-satisfaction:"
                        ),
                        payload={
                            "obligation_id": obligation.identity,
                            "prior_status": "pending",
                            "resolution": satisfaction.to_identity_payload(),
                        },
                        event_stream=(
                            f"historical-replay-obligation:{obligation.identity}"
                        ),
                        event_sequence=2,
                    ),
                )
            )
            old_obligation_id = original_obligation.identity
            old_satisfaction_id = original_satisfaction.identity

            def replace_fixture_identity(value):
                if isinstance(value, str):
                    return value.replace(
                        old_obligation_id,
                        obligation.identity,
                    ).replace(
                        original_obligation.original_study_id,
                        "STU-0061",
                    ).replace(
                        original_obligation.original_executable_id,
                        obligation.original_executable_id,
                    )
                if isinstance(value, list):
                    return [replace_fixture_identity(item) for item in value]
                if isinstance(value, dict):
                    return {
                        key: replace_fixture_identity(item)
                        for key, item in value.items()
                    }
                return value

            records_list: list[IndexRecord] = []
            for kind in RECORD_KINDS:
                for record in scratch.records_by_kind(kind):
                    if record.record_id in {
                        old_obligation_id,
                        old_satisfaction_id,
                    }:
                        continue
                    records_list.append(
                        IndexRecord(
                            kind=record.kind,
                            record_id=record.record_id,
                            subject=replace_fixture_identity(record.subject),
                            status=record.status,
                            fingerprint=record.fingerprint,
                            payload=replace_fixture_identity(
                                deepcopy(record.payload)
                            ),
                            event_stream=replace_fixture_identity(
                                record.event_stream
                            ),
                            event_sequence=record.event_sequence,
                        )
                    )
            records = tuple(records_list)

        def seed(current, _index):
            body = self.predecessor_writer._body(current)
            body["next_action"] = {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": MISSION_ID,
            }
            return body, records, {"obligation_id": obligation.identity}

        self.predecessor_writer._commit(
            event_kind="correction_recovery_fixture_seeded",
            operation_id="fixture-seed-correction-recovery",
            subject=f"Mission:{MISSION_ID}",
            payload={"obligation_id": obligation.identity},
            prepare=seed,
        )
        return obligation.identity

    def replacements(self) -> dict[str, bytes]:
        return {CHANGED_PATH: (self.root / CHANGED_PATH).read_bytes()}

    def _capture_git_blobs(self) -> dict[str, bytes]:
        paths = [self.root / "state" / "control.json"]
        legacy = self.root / "records" / "journal.jsonl"
        if legacy.is_file():
            paths.append(legacy)
        segment_root = self.root / "records" / "journal"
        if segment_root.is_dir():
            paths.extend(
                sorted(path for path in segment_root.iterdir() if path.is_file())
            )
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in paths
        }

    def activate_segmented_journal(self) -> None:
        self.predecessor_writer.migrate_journal_storage(
            reason="exercise segmented correction delivery headroom",
            operation_id="fixture-segment-correction-journal",
            allow_active_stable_boundary=True,
        )
        plan = self.predecessor_writer.plan_historical_replay_satisfaction_invalidation(
            obligation_id=self.obligation_id
        )
        self.reviewed_manifest_sha256 = plan["audit_manifest_sha256"]
        self.git_blobs = self._capture_git_blobs()

    def fake_git(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        if arguments == ("branch", "--show-current"):
            if self.git_requires_recovered_head:
                control = json.loads(
                    (self.root / "state" / "control.json").read_text("ascii")
                )
                events = self.writer().journal.read_all()
                if control["revision"] != events[-1]["sequence"]:
                    raise AssertionError("Git preflight ran before projection recovery")
                self.git_observations += 1
            output = b"main\n"
            returncode = 0
        elif arguments == ("rev-parse", "HEAD"):
            output = (self.git_head + "\n").encode("ascii")
            returncode = 0
        elif arguments == ("rev-parse", "origin/main"):
            output = (self.git_origin + "\n").encode("ascii")
            returncode = 0
        elif arguments == (
            "merge-base",
            "--is-ancestor",
            "origin/main",
            "HEAD",
        ):
            output = b""
            returncode = 0 if self.git_origin_is_ancestor else 1
        elif (
            len(arguments) == 2
            and arguments[0] == "show"
            and ":" in arguments[1]
        ):
            ref, relative = arguments[1].split(":", 1)
            if ref == "HEAD":
                known = (
                    relative in self.git_blob_overrides
                    or relative in self.git_blobs
                    or relative in AUTHORITY_PATHS
                )
                output = self.git_blob_overrides.get(
                    relative,
                    self.git_blobs.get(
                        relative,
                        (
                            (self.root / relative).read_bytes()
                            if relative in AUTHORITY_PATHS
                            else b""
                        ),
                    ),
                )
            elif ref == "origin/main":
                known = (
                    relative in self.origin_blob_overrides
                    or relative in self.git_blobs
                    or relative in AUTHORITY_PATHS
                )
                output = self.origin_blob_overrides.get(
                    relative,
                    self.git_blobs.get(
                        relative,
                        (
                            (self.predecessor_root / relative).read_bytes()
                            if relative in AUTHORITY_PATHS
                            else b""
                        ),
                    ),
                )
            else:
                raise AssertionError(f"unexpected Git ref: {ref}")
            if not known:
                raise AssertionError(f"unexpected Git blob: {relative}")
            returncode = 0
        elif arguments == ("diff", "--cached", "--quiet"):
            output = b""
            returncode = 0 if self.git_index_clean else 1
        elif arguments == ("diff", "--name-only"):
            changed = set(self.extra_changed_paths)
            for relative, baseline in self.git_blobs.items():
                delivered = self.git_blob_overrides.get(relative, baseline)
                target = self.root / relative
                if not target.is_file() or target.read_bytes() != delivered:
                    changed.add(relative)
            output = (
                "" if not changed else "\n".join(sorted(changed)) + "\n"
            ).encode("ascii")
            returncode = 0
        elif arguments == (
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "state/control.json",
            "records/journal",
            "records/journal.jsonl",
        ):
            output = (
                ""
                if not self.untracked_correction_paths
                else "\n".join(sorted(self.untracked_correction_paths)) + "\n"
            ).encode("ascii")
            returncode = 0
        else:
            raise AssertionError(f"unexpected Git command: {arguments}")
        return subprocess.CompletedProcess(arguments, returncode, output, b"")

    def patch_subject(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(SUBJECT, "ROOT", self.root))
        stack.enter_context(
            patch.object(
                SUBJECT,
                "PREDECESSOR_AUTHORITY_DIGEST",
                self.predecessor_digest,
            )
        )
        stack.enter_context(
            patch.object(SUBJECT, "AUTHORITY_PATHS_CHANGED", (CHANGED_PATH,))
        )
        stack.enter_context(
            patch.object(
                SUBJECT,
                "REVIEWED_AUTHORITY_REPLACEMENT_SHA256",
                self.reviewed_authority_replacement_sha256,
            )
        )
        stack.enter_context(
            patch.object(SUBJECT, "REPLAY_OBLIGATION_ID", self.obligation_id)
        )
        stack.enter_context(
            patch.object(
                SUBJECT,
                "REVIEWED_INVALIDATION_MANIFEST_SHA256",
                self.reviewed_manifest_sha256,
            )
        )
        stack.enter_context(
            patch.object(
                SUBJECT,
                "REVIEWED_HISTORICAL_FAMILY_SOURCE_SHA256",
                self.reviewed_historical_family_source_sha256,
            )
        )
        stack.enter_context(
            patch.object(
                SUBJECT,
                "_historical_family_authority",
                lambda: self.historical_family_authority,
            )
        )
        stack.enter_context(
            patch.dict(
                historical_study_registry.HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
                {
                    Path(SUBJECT.HISTORICAL_FAMILY_SOURCE).name: (
                        self.reviewed_historical_family_source_sha256
                    )
                },
            )
        )
        stack.enter_context(
            patch.dict(
                historical_study_registry.HISTORICAL_FAMILY_IDENTITY_BY_MODULE,
                {
                    Path(SUBJECT.HISTORICAL_FAMILY_SOURCE).name: (
                        self.historical_family_authority.family.identity
                    )
                },
            )
        )
        stack.enter_context(patch.object(SUBJECT, "StateWriter", self.writer))
        stack.enter_context(
            patch.object(
                SUBJECT,
                "_predecessor_bytes",
                lambda relative: (self.predecessor_root / relative).read_bytes(),
            )
        )
        stack.enter_context(patch.object(SUBJECT, "_git", self.fake_git))
        return stack


class ExhaustiveAuditReplayCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = CorrectionFixture(self.temporary.name)

    def test_read_only_plan_does_not_mutate_control_journal_or_index(self) -> None:
        paths = (
            self.fixture.root / "state" / "control.json",
            self.fixture.root / "records" / "journal.jsonl",
            self.fixture.root / "local" / "index.sqlite",
        )
        before = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
        with self.fixture.patch_subject():
            plan = SUBJECT._read_only_plan()
        after = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
        self.assertEqual(after, before)
        self.assertEqual(plan["replay_obligation_id"], self.fixture.obligation_id)
        self.assertIsNotNone(plan["replay_invalidation_plan"])

    def test_every_correction_reader_rejects_v1_without_materialization(self) -> None:
        index_path = self.fixture.root / "local" / "index.sqlite"
        _downgrade_projection_to_v1(index_path)
        before = _projection_snapshot(index_path)
        self.assertEqual(before[2], 1)
        self.assertFalse(
            any(
                name.startswith(index_path.name + "-")
                for name in before[3]
            )
        )
        writer = self.fixture.predecessor_writer

        def read_only_correction_plan() -> object:
            with self.fixture.patch_subject():
                return SUBJECT._read_only_plan()

        readers = {
            "correction_read_only_plan": read_only_correction_plan,
            "historical_replay_correction_plan": lambda: (
                writer.plan_historical_replay_correction(
                    adjudication_record_ids=("historical-adjudication-fixture",),
                    replay_study_id="STU-0061",
                )
            ),
            "historical_replay_invalidation_plan": lambda: (
                writer.plan_historical_replay_satisfaction_invalidation(
                    obligation_id=self.fixture.obligation_id,
                )
            ),
            "operation_lookup": lambda: SUBJECT._operation(
                writer,
                "fixture-seed-correction-recovery",
                expected_event_kind="correction_recovery_fixture_seeded",
            ),
            "stable_head": writer.require_stable_head,
        }
        for name, reader in readers.items():
            with self.subTest(reader=name):
                with self.assertRaisesRegex(
                    RecoveryRequired,
                    "explicit local-index materialization: 1",
                ):
                    reader()
                self.assertEqual(_projection_snapshot(index_path), before)

    def test_normal_apply_commits_authority_and_invalidation(self) -> None:
        with self.fixture.patch_subject():
            result = SUBJECT.apply()
            stable = self.fixture.writer().require_stable_head()
        self.assertEqual(result["recovery"]["mode"], "stable_head_no_recovery")
        self.assertEqual(
            result["invalidation_transition"]["result"]["replay_obligation_id"],
            self.fixture.obligation_id,
        )
        self.assertEqual(
            stable["control"]["authority"]["manifest_digest"],
            self.fixture.prospective_digest,
        )
        self.assertEqual(
            result["local_main_delivery_boundary"]["delivery_mode"],
            "single_non_force_fast_forward_push_after_correction_commit",
        )
        self.assertFalse(
            result["local_main_delivery_boundary"]["force_push_allowed"]
        )
        self.assertEqual(
            result["local_main_delivery_boundary"]["correction_commit_paths"],
            ["state/control.json", "records/journal.jsonl"],
        )

    def test_canonical_operation_rejects_duplicate_accepted_family_authority(
        self,
    ) -> None:
        with self.fixture.patch_subject():
            SUBJECT.apply()
            writer = self.fixture.writer()
            authority = SUBJECT._historical_family_authority()
            duplicate = IndexRecord(
                kind="historical-family-authority",
                record_id="historical-family-authority:" + "e" * 64,
                subject=f"ReplayObligation:{self.fixture.obligation_id}",
                status="accepted",
                fingerprint="e" * 64,
                payload=authority.to_identity_payload(),
            )

            def add_duplicate(current, _index):
                return (
                    writer._body(current),
                    (duplicate,),
                    {"duplicate_authority_id": duplicate.record_id},
                )

            writer._commit(
                event_kind="fixture_duplicate_family_authority",
                operation_id="fixture-duplicate-family-authority",
                subject=f"ReplayObligation:{self.fixture.obligation_id}",
                payload={"duplicate_authority_id": duplicate.record_id},
                prepare=add_duplicate,
            )
            with self.assertRaisesRegex(RuntimeError, "not atomic or unique"):
                SUBJECT._operation(
                    writer,
                    SUBJECT.INVALIDATION_OPERATION_ID,
                    expected_event_kind=(
                        "historical_replay_satisfaction_invalidated"
                    ),
                    expected_obligation_id=self.fixture.obligation_id,
                )

    def test_canonical_operation_requires_family_authority_in_same_event(
        self,
    ) -> None:
        with self.fixture.patch_subject():
            SUBJECT.apply()
            writer = self.fixture.writer()
            with writer._open_authoritative_index() as index:
                operation = index.get(
                    "operation",
                    SUBJECT.INVALIDATION_OPERATION_ID,
                )
            assert operation is not None
            event = writer.journal.read_event_at(
                offset=operation.authority_offset,
                expected_sequence=operation.authority_sequence,
                expected_event_id=operation.authority_event_id,
            )
            candidate = deepcopy(event)
            candidate["index_records"] = [
                record
                for record in candidate["index_records"]
                if record.get("kind") != "historical-family-authority"
            ]
            with patch.object(
                writer.journal,
                "read_event_at",
                return_value=candidate,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "not atomic or unique|not a unique Journal member",
                ):
                    SUBJECT._operation(
                        writer,
                        SUBJECT.INVALIDATION_OPERATION_ID,
                        expected_event_kind=(
                            "historical_replay_satisfaction_invalidated"
                        ),
                        expected_obligation_id=self.fixture.obligation_id,
                    )

    def test_apply_rejects_divergent_origin_without_mutation(self) -> None:
        observed_paths = (
            self.fixture.root / "state" / "control.json",
            self.fixture.root / "records" / "journal.jsonl",
            self.fixture.root / "local" / "index.sqlite",
        )
        before = {
            path: sha256(path.read_bytes()).hexdigest() for path in observed_paths
        }
        self.fixture.git_origin_is_ancestor = False
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "divergent|non-ancestor"):
                SUBJECT.apply()
        after = {
            path: sha256(path.read_bytes()).hexdigest() for path in observed_paths
        }
        self.assertEqual(after, before)

    def test_apply_rejects_code_checkpoint_already_published(self) -> None:
        self.fixture.git_origin = self.fixture.git_head
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "unpublished local"):
                SUBJECT.apply()

    def test_apply_accepts_segmented_journal_with_exact_two_event_headroom(
        self,
    ) -> None:
        self.fixture.activate_segmented_journal()
        manifest_path = self.fixture.root / "records" / "journal" / "manifest.json"
        manifest_before = manifest_path.read_bytes()
        manifest = json.loads(manifest_before)
        active_path = manifest["active_segment"]["path"]

        with self.fixture.patch_subject():
            result = SUBJECT.apply()

        boundary = result["local_main_delivery_boundary"]
        self.assertEqual(
            boundary["correction_commit_paths"],
            ["state/control.json", active_path],
        )
        self.assertEqual(boundary["journal_headroom"]["layout"], "segmented")
        self.assertEqual(
            boundary["journal_headroom"]["correction_event_upper_bound"],
            2,
        )
        self.assertEqual(boundary["journal_headroom"]["active_event_count"], 0)
        self.assertEqual(boundary["journal_headroom"]["already_present"], 0)
        self.assertEqual(boundary["journal_headroom"]["remaining"], 2)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(
            [
                event["event_kind"]
                for event in self.fixture.writer().journal.read_all()[-2:]
            ],
            ["authority_migrated", "historical_replay_satisfaction_invalidated"],
        )

    def test_segmented_near_limit_first_event_interruption_resumes(
        self,
    ) -> None:
        self.fixture.activate_segmented_journal()
        with patch.object(DurableJournal, "MAX_SEGMENT_EVENTS", 2):
            with self.assertRaises(InjectedCrash):
                self.fixture.predecessor_writer.migrate_authority(
                    replacements=self.fixture.replacements(),
                    reason=SUBJECT.AUTHORITY_REASON,
                    operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
                    allow_active_stable_boundary=True,
                    crash_after="after_journal",
                )
            self.fixture.git_requires_recovered_head = True
            with self.fixture.patch_subject():
                result = SUBJECT.apply(explicit_recovery=True)
                stable = self.fixture.writer().require_stable_head()

        headroom = result["local_main_delivery_boundary"]["journal_headroom"]
        self.assertEqual(result["recovery"]["recoverable_suffix"], "authority_migrated")
        self.assertEqual(headroom["active_event_count"], 1)
        self.assertEqual(headroom["already_present"], 1)
        self.assertEqual(headroom["remaining"], 1)
        self.assertEqual(headroom["remaining_event_byte_upper_bound"], 1_048_576)
        self.assertEqual(stable["control_revision"], len(self.fixture.writer().journal.read_all()))

    def test_segmented_completed_suffix_reentry_has_zero_remaining_headroom(
        self,
    ) -> None:
        self.fixture.activate_segmented_journal()
        with patch.object(DurableJournal, "MAX_SEGMENT_EVENTS", 2):
            with self.fixture.patch_subject():
                first = SUBJECT.apply()
                revision = self.fixture.writer().require_stable_head()[
                    "control_revision"
                ]
                second = SUBJECT.apply()
                stable = self.fixture.writer().require_stable_head()

        first_headroom = first["local_main_delivery_boundary"]["journal_headroom"]
        second_headroom = second["local_main_delivery_boundary"]["journal_headroom"]
        self.assertEqual(first_headroom["already_present"], 0)
        self.assertEqual(first_headroom["remaining"], 2)
        self.assertEqual(second_headroom["active_event_count"], 2)
        self.assertEqual(second_headroom["already_present"], 2)
        self.assertEqual(second_headroom["remaining"], 0)
        self.assertEqual(second_headroom["remaining_event_byte_upper_bound"], 0)
        self.assertEqual(stable["control_revision"], revision)

    def test_apply_rejects_segmented_journal_without_two_event_count_headroom(
        self,
    ) -> None:
        self.fixture.activate_segmented_journal()
        observed = tuple(
            path
            for path in (
                self.fixture.root / "state" / "control.json",
                self.fixture.root / "records" / "journal" / "manifest.json",
                self.fixture.root / "records" / "journal" / "journal-000002.jsonl",
            )
        )
        before = {path: sha256(path.read_bytes()).hexdigest() for path in observed}
        with self.fixture.patch_subject(), patch.object(
            DurableJournal,
            "MAX_SEGMENT_EVENTS",
            1,
        ):
            with self.assertRaisesRegex(RuntimeError, "two-event Journal segment"):
                SUBJECT.apply()
        after = {path: sha256(path.read_bytes()).hexdigest() for path in observed}
        self.assertEqual(after, before)

    def test_apply_rejects_segmented_journal_without_max_size_headroom(
        self,
    ) -> None:
        self.fixture.activate_segmented_journal()
        manifest_path = self.fixture.root / "records" / "journal" / "manifest.json"
        manifest_before = sha256(manifest_path.read_bytes()).hexdigest()
        with self.fixture.patch_subject(), patch.object(
            DurableJournal,
            "MAX_SEGMENT_BYTES",
            2 * DurableJournal.MAX_EVENT_BYTES - 1,
        ):
            with self.assertRaisesRegex(RuntimeError, "two-event Journal segment"):
                SUBJECT.apply()
        self.assertEqual(
            sha256(manifest_path.read_bytes()).hexdigest(),
            manifest_before,
        )

    def test_apply_rejects_nonempty_git_index(self) -> None:
        self.fixture.git_index_clean = False
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "empty Git index"):
                SUBJECT.apply()

    def test_apply_rejects_uncommitted_authority_worktree_bytes(self) -> None:
        self.fixture.git_blob_overrides[CHANGED_PATH] = (
            self.fixture.predecessor_root / CHANGED_PATH
        ).read_bytes()
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "fully committed"):
                SUBJECT.apply()

    def test_apply_rejects_code_commit_that_changed_control_baseline(self) -> None:
        self.fixture.origin_blob_overrides["state/control.json"] = b"{}\n"
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "control or Journal baseline"):
                SUBJECT.apply()

    def test_apply_rejects_origin_with_prospective_authority_bytes(self) -> None:
        self.fixture.origin_blob_overrides[CHANGED_PATH] = (
            self.fixture.root / CHANGED_PATH
        ).read_bytes()
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "reviewed predecessor"):
                SUBJECT.apply()

    def test_plan_rejects_unreviewed_bytes_at_a_reviewed_authority_path(self) -> None:
        path = self.fixture.root / CHANGED_PATH
        path.write_bytes(path.read_bytes() + b"# unreviewed\n")
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "exact reviewed checkpoint"):
                SUBJECT._read_only_plan()

    def test_recovery_refuses_a_foreign_single_journal_suffix(self) -> None:
        control = self.fixture.predecessor_writer.read_control()
        assert control is not None
        revision = control["revision"]

        def prepare(current, _index):
            return (
                self.fixture.predecessor_writer._body(current),
                (),
                {"foreign": True},
            )

        with self.assertRaises(InjectedCrash):
            self.fixture.predecessor_writer._commit(
                event_kind="foreign_correction_suffix",
                operation_id="foreign-correction-suffix",
                subject=f"Mission:{MISSION_ID}",
                payload={"foreign": True},
                prepare=prepare,
                crash_after="after_journal",
            )
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "foreign authority"):
                SUBJECT.apply(explicit_recovery=True)
        after = self.fixture.predecessor_writer.read_control()
        assert after is not None
        self.assertEqual(after["revision"], revision)
        self.assertEqual(self.fixture.git_observations, 0)

    def test_authority_recovery_requires_exact_payload_control_records_and_id(
        self,
    ) -> None:
        control = self.fixture.predecessor_writer.read_control()
        assert control is not None
        with self.assertRaises(InjectedCrash):
            self.fixture.predecessor_writer.migrate_authority(
                replacements=self.fixture.replacements(),
                reason=SUBJECT.AUTHORITY_REASON,
                operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
                allow_active_stable_boundary=True,
                crash_after="after_journal",
            )
        events = self.fixture.predecessor_writer.journal.read_all()
        original = events[-1]

        def trial_delta(event):
            event["payload"]["trial_delta"] = 1

        def migration_id(event):
            event["index_records"][0]["payload"]["result"][
                "migration_id"
            ] = "f" * 64

        def extra_record(event):
            event["index_records"].append(deepcopy(event["index_records"][0]))

        def changed_control(event):
            event["control"]["next_action"] = {"kind": "foreign_action"}

        for mutate in (trial_delta, migration_id, extra_record, changed_control):
            with self.subTest(mutation=mutate.__name__):
                candidate = deepcopy(original)
                mutate(candidate)
                with self.fixture.patch_subject(), patch.object(
                    self.fixture.predecessor_writer.journal,
                    "read_all",
                    return_value=[*events[:-1], candidate],
                ):
                    with self.assertRaisesRegex(RuntimeError, "foreign"):
                        SUBJECT._require_recoverable_suffix(
                            self.fixture.predecessor_writer,
                            control=control,
                            paths=self.fixture.paths,
                        )

    def test_invalidation_recovery_cross_checks_reviewed_manifest_and_result(
        self,
    ) -> None:
        self.fixture.predecessor_writer.migrate_authority(
            replacements=self.fixture.replacements(),
            reason=SUBJECT.AUTHORITY_REASON,
            operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        writer = self.fixture.writer()
        control = writer.read_control()
        assert control is not None
        plan = writer.plan_historical_replay_satisfaction_invalidation(
            obligation_id=self.fixture.obligation_id
        )
        artifact = writer.evidence.finalize(canonical_bytes(plan["audit_manifest"]))
        original_commit = writer._commit
        with self.fixture.patch_subject():
            family_authority = SUBJECT._historical_family_authority()

        def crash_after_journal(**kwargs):
            return original_commit(**kwargs, crash_after="after_journal")

        with self.fixture.patch_subject(), patch.object(
            writer,
            "_commit",
            side_effect=crash_after_journal,
        ):
            with self.assertRaises(InjectedCrash):
                writer.invalidate_historical_replay_satisfaction(
                    obligation_id=self.fixture.obligation_id,
                    audit_manifest_hash=artifact.sha256,
                    operation_id=SUBJECT.INVALIDATION_OPERATION_ID,
                    historical_family_authority=family_authority,
                )
        events = writer.journal.read_all()
        original = events[-1]

        def payload_manifest(event):
            event["payload"]["audit_manifest_hash"] = "f" * 64

        def payload_satisfaction(event):
            event["payload"]["satisfaction_record_id"] = (
                "historical-replay-satisfaction:" + "f" * 64
            )

        def result_manifest(event):
            event["index_records"][0]["payload"]["result"][
                "audit_manifest_hash"
            ] = "f" * 64

        def result_satisfaction(event):
            event["index_records"][0]["payload"]["result"][
                "invalidated_satisfaction_record_id"
            ] = "historical-replay-satisfaction:" + "f" * 64

        def result_family_authority(event):
            event["index_records"][0]["payload"]["result"][
                "historical_family_authority_id"
            ] = "historical-family-authority:" + "f" * 64

        def payload_family_authority(event):
            event["payload"]["historical_family_authority"] = {
                "schema": "foreign_historical_family_authority.v1"
            }

        def missing_family_authority_record(event):
            event["index_records"] = [
                record
                for record in event["index_records"]
                if record.get("kind") != "historical-family-authority"
            ]

        def nonzero_delta(event):
            event["index_records"][0]["payload"]["result"][
                "scientific_trial_delta"
            ] = 1

        def extra_record(event):
            event["index_records"].append(deepcopy(event["index_records"][0]))

        for mutate in (
            payload_manifest,
            payload_satisfaction,
            result_manifest,
            result_satisfaction,
            result_family_authority,
            payload_family_authority,
            missing_family_authority_record,
            nonzero_delta,
            extra_record,
        ):
            with self.subTest(mutation=mutate.__name__):
                candidate = deepcopy(original)
                mutate(candidate)
                with self.fixture.patch_subject(), patch.object(
                    writer.journal,
                    "read_all",
                    return_value=[*events[:-1], candidate],
                ):
                    with self.assertRaisesRegex(RuntimeError, "foreign"):
                        SUBJECT._require_recoverable_suffix(
                            writer,
                            control=control,
                            paths=self.fixture.paths,
                        )

    def test_recovery_refuses_prior_accepted_family_authority(self) -> None:
        self.fixture.predecessor_writer.migrate_authority(
            replacements=self.fixture.replacements(),
            reason=SUBJECT.AUTHORITY_REASON,
            operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        writer = self.fixture.writer()
        with self.fixture.patch_subject():
            authority = SUBJECT._historical_family_authority()
            duplicate = IndexRecord(
                kind="historical-family-authority",
                record_id="historical-family-authority:" + "e" * 64,
                subject=f"ReplayObligation:{self.fixture.obligation_id}",
                status="accepted",
                fingerprint="e" * 64,
                payload=authority.to_identity_payload(),
            )

            def add_prior_authority(current, _index):
                return (
                    writer._body(current),
                    (duplicate,),
                    {"authority_id": duplicate.record_id},
                )

            writer._commit(
                event_kind="fixture_prior_family_authority",
                operation_id="fixture-prior-family-authority",
                subject=f"ReplayObligation:{self.fixture.obligation_id}",
                payload={"authority_id": duplicate.record_id},
                prepare=add_prior_authority,
            )
            control = writer.read_control()
            assert control is not None
            plan = writer.plan_historical_replay_satisfaction_invalidation(
                obligation_id=self.fixture.obligation_id
            )
            artifact = writer.evidence.finalize(
                canonical_bytes(plan["audit_manifest"])
            )
            original_commit = writer._commit

            def crash_after_journal(**kwargs):
                return original_commit(**kwargs, crash_after="after_journal")

            with patch.object(writer, "_commit", side_effect=crash_after_journal):
                with self.assertRaises(InjectedCrash):
                    writer.invalidate_historical_replay_satisfaction(
                        obligation_id=self.fixture.obligation_id,
                        audit_manifest_hash=artifact.sha256,
                        operation_id=SUBJECT.INVALIDATION_OPERATION_ID,
                    )
            with self.assertRaisesRegex(RuntimeError, "duplicate accepted"):
                SUBJECT._require_recoverable_suffix(
                    writer,
                    control=control,
                    paths=self.fixture.paths,
                )

    def test_recovers_authority_after_journal_from_predecessor_view(self) -> None:
        with self.assertRaises(InjectedCrash):
            self.fixture.predecessor_writer.migrate_authority(
                replacements=self.fixture.replacements(),
                reason=SUBJECT.AUTHORITY_REASON,
                operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
                allow_active_stable_boundary=True,
                crash_after="after_journal",
            )
        self.fixture.git_requires_recovered_head = True
        with self.fixture.patch_subject():
            result = SUBJECT.apply(explicit_recovery=True)
            stable = self.fixture.writer().require_stable_head()
        self.assertEqual(
            result["recovery"]["recoverable_suffix"],
            "authority_migrated",
        )
        self.assertEqual(self.fixture.git_observations, 1)
        self.assertEqual(
            stable["control"]["authority"]["manifest_digest"],
            self.fixture.prospective_digest,
        )
        self.assertEqual(
            result["invalidation_transition"]["result"]["replay_obligation_id"],
            self.fixture.obligation_id,
        )

    def test_recovers_invalidation_after_journal_from_prospective_view(self) -> None:
        self.fixture.predecessor_writer.migrate_authority(
            replacements=self.fixture.replacements(),
            reason=SUBJECT.AUTHORITY_REASON,
            operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        writer = self.fixture.writer()
        plan = writer.plan_historical_replay_satisfaction_invalidation(
            obligation_id=self.fixture.obligation_id
        )
        artifact = writer.evidence.finalize(canonical_bytes(plan["audit_manifest"]))
        original_commit = writer._commit
        with self.fixture.patch_subject():
            family_authority = SUBJECT._historical_family_authority()

        def crash_after_journal(**kwargs):
            return original_commit(**kwargs, crash_after="after_journal")

        with self.fixture.patch_subject(), patch.object(
            writer,
            "_commit",
            side_effect=crash_after_journal,
        ):
            with self.assertRaises(InjectedCrash):
                writer.invalidate_historical_replay_satisfaction(
                    obligation_id=self.fixture.obligation_id,
                    audit_manifest_hash=artifact.sha256,
                    operation_id=SUBJECT.INVALIDATION_OPERATION_ID,
                    historical_family_authority=family_authority,
                )
        self.fixture.git_requires_recovered_head = True
        with self.fixture.patch_subject():
            first = SUBJECT.apply(explicit_recovery=True)
            revision = self.fixture.writer().require_stable_head()["control_revision"]
            second = SUBJECT.apply(explicit_recovery=True)
            stable = self.fixture.writer().require_stable_head()
        self.assertEqual(
            first["recovery"]["recoverable_suffix"],
            "historical_replay_satisfaction_invalidated",
        )
        self.assertEqual(first["invalidation_operation"], second["invalidation_operation"])
        self.assertEqual(stable["control_revision"], revision)
        self.assertEqual(self.fixture.git_observations, 2)

    def test_delivery_guard_rejects_foreign_tracked_journal_path(self) -> None:
        self.fixture.predecessor_writer.migrate_authority(
            replacements=self.fixture.replacements(),
            reason=SUBJECT.AUTHORITY_REASON,
            operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        revision = self.fixture.writer().require_stable_head()["control_revision"]
        self.fixture.extra_changed_paths.add(
            "records/journal/journal-foreign.jsonl"
        )
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "unrelated or undelivered"):
                SUBJECT.apply()
        self.assertEqual(
            self.fixture.writer().require_stable_head()["control_revision"],
            revision,
        )

    def test_delivery_guard_rejects_rewritten_journal_prefix_bytes(self) -> None:
        self.fixture.predecessor_writer.migrate_authority(
            replacements=self.fixture.replacements(),
            reason=SUBJECT.AUTHORITY_REASON,
            operation_id=SUBJECT.AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        self.fixture.git_blob_overrides["records/journal.jsonl"] = (
            self.fixture.git_blobs["records/journal.jsonl"] + b"foreign\n"
        )
        self.fixture.origin_blob_overrides["records/journal.jsonl"] = (
            self.fixture.git_blob_overrides["records/journal.jsonl"]
        )
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "append-only Git suffix"):
                SUBJECT.apply()

    def test_delivery_guard_rejects_foreign_untracked_journal_path(self) -> None:
        observed_paths = (
            self.fixture.root / "state" / "control.json",
            self.fixture.root / "records" / "journal.jsonl",
            self.fixture.root / "local" / "index.sqlite",
        )
        before = {
            path: sha256(path.read_bytes()).hexdigest() for path in observed_paths
        }
        self.fixture.untracked_correction_paths.add(
            "records/journal/foreign.jsonl"
        )
        with self.fixture.patch_subject():
            with self.assertRaisesRegex(RuntimeError, "foreign untracked"):
                SUBJECT.apply()
        after = {
            path: sha256(path.read_bytes()).hexdigest() for path in observed_paths
        }
        self.assertEqual(after, before)

    def test_recover_without_apply_is_rejected(self) -> None:
        with patch.object(sys, "argv", [str(SCRIPT_PATH), "--recover"]):
            with self.assertRaisesRegex(SystemExit, "requires --apply"):
                SUBJECT.main()


class LiveRootCorrectionPlanTests(unittest.TestCase):
    @unittest.skipUnless(
        (REPO_ROOT / "local" / "index.sqlite").is_file(),
        "requires the live read-only Axiom projection",
    )
    def test_live_root_plan_is_read_only_and_still_binds_four_contracts(
        self,
    ) -> None:
        def snapshot() -> tuple[tuple[str, int, str], ...]:
            paths = [
                REPO_ROOT / "state" / "control.json",
                REPO_ROOT / "local" / "index.sqlite",
                *(sorted((REPO_ROOT / "records" / "journal").glob("*"))),
            ]
            return tuple(
                (
                    path.relative_to(REPO_ROOT).as_posix(),
                    path.stat().st_size,
                    sha256(path.read_bytes()).hexdigest(),
                )
                for path in paths
                if path.is_file()
            )

        before = snapshot()
        status_before = subprocess.run(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        plan = SUBJECT._read_only_plan()
        status_after = subprocess.run(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(snapshot(), before)
        self.assertEqual(status_after, status_before)
        self.assertEqual(
            set(plan["authority_replacement_sha256"]),
            set(SUBJECT.AUTHORITY_PATHS_CHANGED),
        )
        self.assertEqual(len(plan["authority_replacement_sha256"]), 4)
        if plan["replay_invalidation_plan"] is not None:
            self.assertEqual(
                plan["replay_invalidation_plan"]["audit_manifest_sha256"],
                SUBJECT.REVIEWED_INVALIDATION_MANIFEST_SHA256,
            )


if __name__ == "__main__":
    unittest.main()
