"""Static guards for shared helper boundaries."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MT5_DIR = PROJECT_ROOT / "src" / "axiom_rift" / "mt5"
PROXY_DIR = PROJECT_ROOT / "src" / "axiom_rift" / "proxies"


class SharedHelperBoundaryTests(unittest.TestCase):
    def test_mt5_probes_do_not_import_other_probe_helpers(self) -> None:
        offenders: list[str] = []
        for path in sorted(MT5_DIR.glob("*_probe.py")):
            tree = ast.parse(path.read_text(encoding="ascii"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.module.startswith("axiom_rift.mt5.") and node.module.endswith("_probe"):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {node.module}")
        self.assertEqual([], offenders)

    def test_proxy_runs_do_not_import_other_run_proxies_as_helpers(self) -> None:
        offenders: list[str] = []
        for path in sorted(PROXY_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="ascii"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "axiom_rift.proxies":
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports run proxy from package")
                    if node.module.startswith("axiom_rift.proxies.") and not node.module.startswith("axiom_rift.proxies.common"):
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("axiom_rift.proxies.") and not alias.name.startswith("axiom_rift.proxies.common"):
                            offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {alias.name}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
