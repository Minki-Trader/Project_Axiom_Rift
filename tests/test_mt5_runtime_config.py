from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.mt5.runtime_config import (
    RUNTIME_CONFIG_PATH,
    RuntimeConfigError,
    load_runtime_config,
    lot_input_line,
    runtime_payload_fields,
    tester_account_lines,
    tester_model_label_for_mode,
    tester_model_for_mode,
)


class Mt5RuntimeConfigTest(unittest.TestCase):
    def test_active_runtime_config_is_complete_without_authority_claims(self) -> None:
        config = load_runtime_config()
        self.assertEqual(config.symbol, "US100")
        self.assertEqual(config.timeframe, "M5")
        self.assertEqual(config.deposit, 500.0)
        self.assertEqual(config.leverage, 100)
        self.assertEqual(config.claim_boundary["active_runtime_config_complete"], True)
        self.assertEqual(config.claim_boundary["runtime_authority"], False)
        self.assertEqual(config.claim_boundary["live_ready"], False)

    def test_tester_lines_and_models_come_from_runtime_config(self) -> None:
        self.assertEqual(tester_account_lines(), ["Deposit=500", "Currency=USD", "Leverage=100", "ExecutionMode=0"])
        self.assertEqual(tester_model_for_mode("logic_parity"), 2)
        self.assertEqual(tester_model_for_mode("tick_execution"), 4)
        self.assertEqual(tester_model_label_for_mode("tick_execution"), "real_ticks_model_4")
        self.assertEqual(lot_input_line(), "InpLot=0.01")

    def test_runtime_payload_records_path_hash_and_snapshot(self) -> None:
        fields = runtime_payload_fields()
        self.assertEqual(fields["runtime_config_path"], "configs/runtime.yaml")
        self.assertEqual(len(fields["runtime_config_sha256"]), 64)
        self.assertEqual(fields["runtime_config_snapshot"]["claim_boundary"]["runtime_authority"], False)

    def test_null_required_field_fails_fast(self) -> None:
        data = yaml.safe_load(RUNTIME_CONFIG_PATH.read_text(encoding="ascii"))
        data["mt5"]["deposit"] = None
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.yaml"
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="ascii")
            with self.assertRaises(RuntimeConfigError):
                load_runtime_config(path)

    def test_probe_files_do_not_keep_legacy_runtime_defaults(self) -> None:
        forbidden = (
            "DEFAULT_TERMINAL_EXE",
            "DEFAULT_METAEDITOR_EXE",
            "STARTING_BALANCE_USD = 500.0",
            '"Deposit=500"',
            '"Leverage=100"',
            '"ExecutionMode=0"',
            '"InpLot=0.01"',
            '"mt5_symbol": "US100"',
            '"mt5_timeframe": "M5"',
            '"mt5_tester_model": "real_ticks_model_4"',
        )
        probe_dir = PROJECT_ROOT / "src" / "axiom_rift" / "mt5"
        offenders: list[str] = []
        for path in sorted(probe_dir.glob("*_probe.py")):
            text = path.read_text(encoding="ascii")
            for pattern in forbidden:
                if pattern in text:
                    offenders.append(f"{path.name}: {pattern}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
