from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import axiom_rift.storage.atomic_file as atomic_file_module
from axiom_rift.storage.study_kpi import (
    StudyKpiProjectionRow,
    materialize_study_kpi,
    render_study_kpi,
)


def row(
    sequence: int,
    study_id: str,
    *,
    executable_id: str | None = None,
    executable_display_id: str | None = None,
) -> StudyKpiProjectionRow:
    display_id = executable_display_id
    if executable_id is not None and display_id is None:
        display_id = "EXE-" + executable_id.removeprefix("executable:")[:12]
    return StudyKpiProjectionRow(
        sequence=sequence,
        closed_at_utc=f"2026-07-12T0{sequence + 4}:30:00Z",
        study_id=study_id,
        executable_id=executable_id,
        executable_display_id=display_id,
        net_profit_micropoints=(1_248_300 if executable_id else None),
        median_fold_profit_factor_milli=(1_780 if executable_id else None),
        trade_count=(124 if executable_id else None),
        monthly_realized_exit_drawdown_share_of_gross_profit_ppm=(
            72_000 if executable_id else None
        ),
        outcome="preserved" if executable_id else "evidence_gap",
    )


class StudyKpiProjectionTests(unittest.TestCase):
    def test_render_is_deterministic_ascii_and_uses_fixed_units(self) -> None:
        first = row(1, "STU-0022", executable_id="executable:" + "a" * 64)
        second = row(2, "STU-0023")
        rendered = render_study_kpi((second, first))
        rendered.decode("ascii")
        text = rendered.decode("ascii")
        self.assertIn(
            "| 000001 | 2026-07-12 14:30 | STU-0022 | EXE-aaaaaaaaaaaa | "
            "1,248,300 | 1.78 | 124 | 7.2% | preserved |",
            text,
        )
        self.assertIn(
            "| 000002 | 2026-07-12 15:30 | STU-0023 | - | - | - | - | - | "
            "evidence_gap |",
            text,
        )
        self.assertEqual(rendered, render_study_kpi((first, second)))

    def test_existing_row_is_stable_when_a_future_prefix_collides(self) -> None:
        prefix = "123456789abc"
        first = row(
            1,
            "STU-0022",
            executable_id="executable:" + prefix + "0" * 52,
        )
        second = row(
            2,
            "STU-0023",
            executable_id="executable:" + prefix + "1" * 52,
            executable_display_id="EXE-" + prefix + "1111",
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "STUDY_KPI.md"
            self.assertTrue(materialize_study_kpi(target, (first,)))
            original = target.read_bytes()
            self.assertTrue(materialize_study_kpi(target, (first, second)))
            updated = target.read_bytes()
            self.assertIn(original.splitlines()[-1], updated.splitlines())
            self.assertIn(("EXE-" + prefix + "1111").encode("ascii"), updated)

    def test_sequence_and_study_are_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "contiguous"):
            render_study_kpi((row(2, "STU-0022"),))
        with self.assertRaisesRegex(ValueError, "duplicate Study"):
            render_study_kpi((row(1, "STU-0022"), row(2, "STU-0022")))

    def test_atomic_materialization_is_idempotent_and_repairs_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "records" / "STUDY_KPI.md"
            rows = (row(1, "STU-0022"),)
            self.assertTrue(materialize_study_kpi(target, rows))
            expected = target.read_bytes()
            self.assertFalse(materialize_study_kpi(target, rows))
            target.write_bytes(b"corrupt\n")
            self.assertTrue(materialize_study_kpi(target, rows))
            self.assertEqual(target.read_bytes(), expected)

    def test_linked_projection_and_linked_parent_fail_closed(self) -> None:
        rows = (row(1, "STU-0022"),)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            outside_projection = outside / "STUDY_KPI.md"
            outside_projection.write_bytes(b"outside\n")
            linked_projection = root / "linked-projection.md"
            linked_parent = root / "linked-records"
            try:
                linked_projection.symlink_to(outside_projection)
                linked_parent.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(OSError, "single-link regular"):
                materialize_study_kpi(linked_projection, rows)
            with self.assertRaisesRegex(OSError, "directory is unsafe"):
                materialize_study_kpi(linked_parent / "missing" / "STUDY_KPI.md", rows)

            self.assertEqual(outside_projection.read_bytes(), b"outside\n")
            self.assertFalse((outside / "missing").exists())

    def test_existing_change_before_publication_check_is_preserved(self) -> None:
        rows = (row(1, "STU-0022"),)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "STUDY_KPI.md"
            target.write_bytes(b"initial projection\n")
            manual = b"manual concurrent projection\n"
            original_snapshot = atomic_file_module._stable_snapshot
            target_snapshots = 0

            def snapshot_with_change(
                path: Path,
                *,
                max_bytes: int,
                missing_ok: bool,
            ) -> tuple[bytes, tuple[int, int, int, int, int, int]] | None:
                nonlocal target_snapshots
                if Path(path) == target:
                    target_snapshots += 1
                    if target_snapshots == 2:
                        target.write_bytes(manual)
                return original_snapshot(
                    path,
                    max_bytes=max_bytes,
                    missing_ok=missing_ok,
                )

            with (
                patch.object(
                    atomic_file_module,
                    "_stable_snapshot",
                    side_effect=snapshot_with_change,
                ),
                self.assertRaisesRegex(OSError, "target changed"),
            ):
                materialize_study_kpi(target, rows)

            self.assertEqual(target.read_bytes(), manual)

    def test_missing_projection_race_preserves_the_concurrent_creator(self) -> None:
        rows = (row(1, "STU-0022"),)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "STUDY_KPI.md"
            manual = b"concurrent creator\n"
            original_publish = atomic_file_module._publish_missing_target

            def publish_after_concurrent_create(
                temporary_path: Path,
                target_path: Path,
                *,
                temporary_identity: tuple[int, int],
                parent_identity: tuple[int, int],
            ) -> None:
                target_path.write_bytes(manual)
                original_publish(
                    temporary_path,
                    target_path,
                    temporary_identity=temporary_identity,
                    parent_identity=parent_identity,
                )

            with (
                patch.object(
                    atomic_file_module,
                    "_publish_missing_target",
                    side_effect=publish_after_concurrent_create,
                ),
                self.assertRaisesRegex(OSError, "was created"),
            ):
                materialize_study_kpi(target, rows)

            self.assertEqual(target.read_bytes(), manual)


if __name__ == "__main__":
    unittest.main()
