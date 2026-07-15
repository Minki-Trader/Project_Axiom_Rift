from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.storage.atomic_file as atomic_file_module
from axiom_rift.storage.state import (
    ControlStateError,
    ControlStore,
    WriterLock,
    control_hash,
    validate_control,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ControlStrictTypeTests(unittest.TestCase):
    @staticmethod
    def _control() -> dict[str, object]:
        return json.loads(
            (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
        )

    def _assert_control_rejected(
        self,
        mutate,
        message: str,
    ) -> None:
        control = self._control()
        mutate(control)
        control["control_hash"] = control_hash(control)
        with self.assertRaisesRegex(ControlStateError, message):
            validate_control(control)

    def test_control_surface_and_scientific_authority_are_exact(self) -> None:
        cases = (
            (
                "extra top level",
                lambda control: control.__setitem__("forged_history", []),
                "top-level surface",
            ),
            (
                "extra engineering",
                lambda control: control["engineering"].__setitem__("forged", True),
                "engineering control surface",
            ),
            (
                "boolean authority count",
                lambda control: control["authority"].__setitem__("graph_count", True),
                "authority graph",
            ),
            (
                "boolean engineering count",
                lambda control: control["engineering"].__setitem__(
                    "mutable_control_state_count", True
                ),
                "mutable state",
            ),
            (
                "negative holdout count",
                lambda control: control["scientific"].__setitem__(
                    "holdout_reveals", -1
                ),
                "holdout reveal count",
            ),
            (
                "boolean holdout count",
                lambda control: control["scientific"].__setitem__(
                    "holdout_reveals", True
                ),
                "holdout reveal count",
            ),
            (
                "scientific claim",
                lambda control: control["scientific"].__setitem__(
                    "claim", {"forged": "candidate"}
                ),
                "scientific claim authority",
            ),
            (
                "Foundation initiative",
                lambda control: control["initiative"].__setitem__(
                    "status", "active"
                ),
                "Foundation initiative",
            ),
            (
                "active lineage",
                lambda control: control["scientific"].__setitem__(
                    "active_lineage", "LIN-FORGED"
                ),
                "active_lineage",
            ),
            (
                "future holdout",
                lambda control: control["scientific"].__setitem__(
                    "required_future_holdout_id", "future"
                ),
                "future holdout identity",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label):
                self._assert_control_rejected(mutate, message)

    def test_active_nested_projections_and_authorizations_fail_closed(self) -> None:
        authorization_key = next(iter(self._control()["authorizations"]))
        cases = (
            (
                "authorization epoch bool",
                lambda control: control["authorizations"][
                    authorization_key
                ].__setitem__("authorization_epoch", True),
                "authorization payload",
            ),
            (
                "authorization subject mismatch",
                lambda control: control["authorizations"][
                    authorization_key
                ].__setitem__("subject_id", "MIS-FORGED"),
                "authorization payload",
            ),
            (
                "authorization extra field",
                lambda control: control["authorizations"][
                    authorization_key
                ].__setitem__("forged", True),
                "authorization payload",
            ),
            (
                "active Batch extra field",
                lambda control: control["scientific"].__setitem__(
                    "active_batch",
                    {
                        "forged": True,
                        "hash": "0" * 64,
                        "id": "batch:" + "0" * 64,
                        "status": "open",
                    },
                ),
                "active Batch projection",
            ),
            (
                "active Job extra field",
                lambda control: control["scientific"].__setitem__(
                    "active_job",
                    {
                        "forged": True,
                        "hash": "0" * 64,
                        "id": "job:" + "0" * 64,
                        "resume_action": "resume",
                        "status": "declared",
                    },
                ),
                "active Job projection",
            ),
            (
                "active Release extra field",
                lambda control: control["scientific"].__setitem__(
                    "active_release",
                    {
                        "candidate_id": "candidate:" + "0" * 64,
                        "executable_id": "executable:" + "0" * 64,
                        "forged": True,
                        "id": "REL-FORGED",
                        "status": "declared",
                    },
                ),
                "active Release projection",
            ),
            (
                "active holdout",
                lambda control: control["scientific"].__setitem__(
                    "active_holdout_evaluation",
                    {
                        "candidate_id": "candidate:" + "0" * 64,
                        "executable_id": "executable:" + "0" * 64,
                        "holdout_id": "future",
                        "job_id": "job:" + "0" * 64,
                        "status": "revealed_pending_evaluation",
                    },
                ),
                "active holdout",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label):
                self._assert_control_rejected(mutate, message)

    def test_boolean_index_sequence_cannot_equal_integer_revision(self) -> None:
        original = json.loads(
            (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
        )
        for path in (
            ("heads", "journal", "sequence"),
            ("heads", "index", "required_sequence"),
            ("heads", "index", "required_record_count"),
        ):
            with self.subTest(path=path):
                control = json.loads(json.dumps(original))
                control["revision"] = 1
                control["heads"]["journal"]["sequence"] = 1
                control["heads"]["index"]["required_sequence"] = 1
                control["heads"]["index"]["required_record_count"] = 1
                target = control
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = True
                control["control_hash"] = control_hash(control)

                with self.assertRaisesRegex(
                    ControlStateError, "heads do not match"
                ):
                    validate_control(control)

    def test_writer_lock_timeout_rejects_boolean_and_nonpositive_values(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "writer.lock"
            for value in (False, True, 0, -1):
                with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "positive integer"
                ):
                    WriterLock(path, timeout_seconds=value)
            for value in (0, 1, "false"):
                with self.subTest(create_if_missing=value), self.assertRaisesRegex(
                    ValueError, "must be boolean"
                ):
                    WriterLock(path, create_if_missing=value)  # type: ignore[arg-type]

    def test_read_side_state_capabilities_create_nothing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent-repository"
            control_path = root / "state" / "control.json"
            lock_path = root / "local" / "state.writer.lock"

            store = ControlStore(control_path)
            self.assertFalse(root.exists())
            self.assertIsNone(store.read())
            self.assertFalse(root.exists())
            with self.assertRaisesRegex(ControlStateError, "unavailable"):
                with WriterLock(lock_path, create_if_missing=False):
                    self.fail("missing read-side lock must not be created")
            self.assertFalse(root.exists())

    def test_existing_only_writer_lock_never_initializes_or_repairs_file(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "writer.lock"
            for payload in (b"", b"\0extra", b"x"):
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    with self.assertRaises(ControlStateError):
                        with WriterLock(path, create_if_missing=False):
                            self.fail("malformed existing lock must fail closed")
                    self.assertEqual(path.read_bytes(), payload)

            path.write_bytes(b"\0")
            with WriterLock(path, create_if_missing=False):
                pass
            self.assertEqual(path.read_bytes(), b"\0")

    def test_writer_lock_rejects_a_hard_link_alias(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "writer.lock"
            path.write_bytes(b"\0")
            alias = path.with_suffix(".alias")
            os.link(path, alias)

            with self.assertRaisesRegex(ControlStateError, "link-like"):
                with WriterLock(path):
                    self.fail("hard-linked writer lock must not be acquired")

    def test_writer_lock_rejects_a_symbolic_link(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.lock"
            target.write_bytes(b"\0")
            path = root / "writer.lock"
            try:
                path.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(ControlStateError, "link-like"):
                with WriterLock(path):
                    self.fail("symbolic-link writer lock must not be acquired")

    def test_writer_lock_does_not_materialize_a_broken_symbolic_link_target(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "absent-target.lock"
            path = root / "writer.lock"
            try:
                path.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaises(ControlStateError):
                with WriterLock(path):
                    self.fail("broken symbolic-link lock must fail closed")
            self.assertFalse(target.exists())

    def test_control_reader_rejects_link_aliases(self) -> None:
        control_payload = (
            REPOSITORY_ROOT / "state" / "control.json"
        ).read_bytes()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_bytes(control_payload)

            hard_link = root / "hard-link.json"
            os.link(target, hard_link)
            with self.assertRaisesRegex(ControlStateError, "single-link"):
                ControlStore(hard_link).read()

            symbolic_link = root / "symbolic-link.json"
            try:
                symbolic_link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaisesRegex(ControlStateError, "single-link"):
                ControlStore(symbolic_link).read()

    def test_control_reader_rejects_oversized_documents_before_parsing(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "control.json"
            path.write_bytes(b" " * (1_048_576 + 1))
            with self.assertRaisesRegex(ControlStateError, "byte limit"):
                ControlStore(path).read()

    def test_state_writers_do_not_traverse_a_linked_parent(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symbolic links unavailable: {exc}")

            lock_path = linked / "created" / "writer.lock"
            with self.assertRaisesRegex(ControlStateError, "directory"):
                with WriterLock(lock_path):
                    self.fail("linked parent must not receive a writer lock")
            self.assertFalse((outside / "created").exists())

            control = json.loads(
                (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
            )
            outside_control = outside / "control.json"
            outside_control.write_text(json.dumps(control), encoding="ascii")
            with self.assertRaisesRegex(ControlStateError, "became unavailable"):
                ControlStore(linked / "control.json").read()
            with self.assertRaisesRegex(ControlStateError, "atomic replacement"):
                ControlStore(linked / "state" / "control.json").replace(control)
            self.assertFalse((outside / "state").exists())

    def test_control_atomic_replace_ignores_predictable_link_residue(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "control.json"
            outside = root / "outside.json"
            outside.write_bytes(b"outside-must-not-change")
            residue = root / ".control.json.tmp"
            try:
                residue.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            control = json.loads(
                (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
            )

            observed = ControlStore(path).replace(control)
            self.assertEqual(ControlStore(path).read(), observed)
            self.assertEqual(outside.read_bytes(), b"outside-must-not-change")
            self.assertTrue(residue.is_symlink())

    def test_control_atomic_replace_leaves_a_foreign_temporary_untouched(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "control.json"
            foreign = root / "foreign.json"
            foreign.write_bytes(b"foreign-must-not-change")
            control = json.loads(
                (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
            )
            original_directory_identity = atomic_file_module._directory_identity
            captured: dict[str, Path] = {}
            calls = 0

            def replace_before_publish(parent: Path) -> tuple[int, int]:
                nonlocal calls
                identity = original_directory_identity(parent)
                calls += 1
                if calls == 2:
                    candidates = tuple(parent.glob(".control.json.*.tmp"))
                    self.assertEqual(len(candidates), 1)
                    temporary_path = candidates[0]
                    temporary_path.unlink()
                    os.link(foreign, temporary_path)
                    captured["temporary"] = temporary_path
                return identity

            with (
                patch.object(
                    atomic_file_module,
                    "_directory_identity",
                    side_effect=replace_before_publish,
                ),
                self.assertRaisesRegex(ControlStateError, "single-link"),
            ):
                ControlStore(path).replace(control)
            replacement = captured["temporary"]
            self.assertFalse(path.exists())
            self.assertEqual(foreign.read_bytes(), b"foreign-must-not-change")
            self.assertEqual(replacement.read_bytes(), b"foreign-must-not-change")

    def test_control_atomic_replace_cleanup_does_not_mask_primary_error(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "control.json"
            control = json.loads(
                (REPOSITORY_ROOT / "state" / "control.json").read_text("ascii")
            )

            with (
                patch.object(
                    atomic_file_module.os,
                    "replace",
                    side_effect=OSError("primary replace failure"),
                ),
                patch.object(
                    Path,
                    "unlink",
                    side_effect=PermissionError("secondary cleanup failure"),
                ),
                self.assertRaises(ControlStateError) as caught,
            ):
                ControlStore(path).replace(control)
            cause = caught.exception.__cause__
            self.assertIsNotNone(cause)
            assert cause is not None
            self.assertIn("atomic replacement", str(cause))
            self.assertIsInstance(cause.__cause__, OSError)
            self.assertIn("primary replace failure", str(cause.__cause__))


if __name__ == "__main__":
    unittest.main()
