from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from axiom_rift.pipelines.base_frame import build_us100_m5_base_frame
from axiom_rift.validation.price_quality import (
    PriceQualityError,
    build_price_quality_audit,
    require_no_price_quality_blockers,
)


def bar(index: int, price: float = 100.0, spread: float = 1.0, tick_volume: float = 10.0) -> dict[str, str]:
    return {
        "time": f"2026-01-01 00:{index % 60:02d}:00",
        "open": f"{price:.2f}",
        "high": f"{price + 5.0:.2f}",
        "low": f"{price - 5.0:.2f}",
        "close": f"{price + 1.0:.2f}",
        "tick_volume": f"{tick_volume:.0f}",
        "spread": f"{spread:.0f}",
        "real_volume": "0",
    }


class PriceQualityTest(unittest.TestCase):
    def test_valid_ohlc_has_no_blockers(self) -> None:
        audit = build_price_quality_audit(
            [bar(0), bar(1, price=101.0)],
            created_at_utc="2026-01-01T00:00:00Z",
            source_raw_csv="data/raw/mt5_bars/m5/US100_M5_max.csv",
            base_frame_csv="data/processed/datasets/us100_m5_base_frame.csv",
            base_frame_sha256="abc",
        )

        self.assertEqual(audit["blocker_count"], 0)
        require_no_price_quality_blockers(audit)

    def test_invalid_ohlc_and_negative_values_are_blocking(self) -> None:
        rows = [bar(0), bar(1)]
        rows[0]["high"] = "90.0"
        rows[0]["spread"] = "-1"
        rows[1]["tick_volume"] = "bad"

        audit = build_price_quality_audit(
            rows,
            created_at_utc="2026-01-01T00:00:00Z",
            source_raw_csv="raw.csv",
            base_frame_csv="base.csv",
        )

        codes = {issue["code"] for issue in audit["blocker_preview"]}
        self.assertGreaterEqual(audit["blocker_count"], 2)
        self.assertIn("numeric_parse_failed", codes)
        self.assertIn("high_below_open", codes)
        with self.assertRaises(PriceQualityError):
            require_no_price_quality_blockers(audit)

    def test_spikes_are_warnings_not_blockers(self) -> None:
        rows = [bar(index, price=100.0 + index * 0.1) for index in range(200)]
        rows[-1].update({"high": "1200.0", "low": "100.0", "close": "1100.0", "spread": "1000"})

        audit = build_price_quality_audit(
            rows,
            created_at_utc="2026-01-01T00:00:00Z",
            source_raw_csv="raw.csv",
            base_frame_csv="base.csv",
        )

        warning_codes = {warning["code"] for warning in audit["warnings"]}
        self.assertEqual(audit["blocker_count"], 0)
        self.assertIn("range_spike", warning_codes)
        self.assertIn("close_jump_spike", warning_codes)
        self.assertIn("spread_spike", warning_codes)

    def test_base_frame_build_fails_before_rewriting_outputs_on_price_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw = root / "raw.csv"
            output = root / "base.csv"
            coverage = root / "coverage.json"
            audit = root / "price_quality.json"
            raw.write_text(
                "time,open,high,low,close,tick_volume,spread,real_volume\n"
                "2026-01-01 00:00:00,100,90,95,98,10,1,0\n",
                encoding="ascii",
            )
            output.write_text("existing output\n", encoding="ascii")
            coverage.write_text("existing coverage\n", encoding="ascii")

            with self.assertRaises(PriceQualityError):
                build_us100_m5_base_frame(
                    raw_csv=raw,
                    output_csv=output,
                    coverage_json=coverage,
                    price_quality_json=audit,
                )

            self.assertEqual(output.read_text(encoding="ascii"), "existing output\n")
            self.assertEqual(coverage.read_text(encoding="ascii"), "existing coverage\n")
            self.assertFalse(audit.exists())


if __name__ == "__main__":
    unittest.main()
