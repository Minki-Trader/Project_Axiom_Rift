from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import yaml

from axiom_rift.v2.validation import validate_v2_bootstrap


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class V2BootstrapValidationTests(unittest.TestCase):
    def test_repository_bootstrap_is_valid_and_fast(self) -> None:
        start = time.perf_counter()
        result = validate_v2_bootstrap(PROJECT_ROOT)
        elapsed = time.perf_counter() - start
        self.assertTrue(result.ok, result.to_dict())
        self.assertLess(elapsed, 2.0)

    def test_invalid_claim_level_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in ("contracts/v2", "configs/v2", "registries/v2"):
                source = PROJECT_ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target)
            state_path = root / "registries/v2/control_state.yaml"
            payload = yaml.safe_load(state_path.read_text(encoding="ascii"))
            payload["claim"]["current_level"] = "selected"
            state_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="ascii")
            result = validate_v2_bootstrap(root)
            self.assertFalse(result.ok)
            self.assertIn("invalid_control_state", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
