from __future__ import annotations

from datetime import datetime, timezone
import unittest

import numpy as np

from axiom_rift.research.vix_source import VIX_COLUMNS
from axiom_rift.research.vix_source_audit import _history_bytes


class VIXSourceAuditTests(unittest.TestCase):
    def test_history_render_is_deterministic_ascii(self) -> None:
        dtype = [
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "i8"),
            ("spread", "i4"),
            ("real_volume", "i8"),
        ]
        rates = np.array(
            [
                (
                    int(datetime(2022, 1, 3, 1, 0, tzinfo=timezone.utc).timestamp()),
                    20.0,
                    21.0,
                    19.0,
                    20.5,
                    10,
                    2,
                    0,
                )
            ],
            dtype=dtype,
        )
        rendered = _history_bytes(rates)
        self.assertTrue(rendered.startswith((",".join(VIX_COLUMNS) + "\n").encode("ascii")))
        self.assertIn(b"2022.01.03 01:00:00,20.00,21.00,19.00,20.50", rendered)


if __name__ == "__main__":
    unittest.main()
