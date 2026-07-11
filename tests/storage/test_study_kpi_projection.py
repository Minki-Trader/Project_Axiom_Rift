from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
