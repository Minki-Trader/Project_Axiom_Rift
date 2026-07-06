import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from axiom_rift import __version__
from axiom_rift.cli import COMMANDS, build_parser, resolve_target


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_ROOT / "src" / "axiom_rift" / "cli.py"


class ImportTest(unittest.TestCase):
    def test_version_is_defined(self) -> None:
        self.assertTrue(__version__)

    def test_cli_parser_choices_match_registry(self) -> None:
        parser = build_parser()
        command_actions = [action for action in parser._actions if action.dest == "command"]
        choices = set(command_actions[0].choices)
        self.assertEqual(choices, set(COMMANDS))
        self.assertEqual(len(COMMANDS), 776)
        self.assertIn("status", choices)
        self.assertIn("validate-templates", choices)
        self.assertIn("validate-repo-state", choices)
        self.assertIn("run-c0008-r0002-mt5-tick", choices)
        self.assertIn("run-c0008-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0008-r0004-proxy", choices)
        self.assertIn("run-c0008-r0004-mt5-tick-by-fold", choices)
        self.assertIn("run-c0009-r0001-proxy", choices)
        self.assertIn("run-c0009-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0009-r0002-proxy", choices)
        self.assertIn("run-c0009-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0009-r0003-proxy", choices)
        self.assertIn("run-c0009-r0003-mt5-tick-by-fold", choices)
        self.assertIn("run-c0010-r0001-proxy", choices)
        self.assertIn("run-c0010-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0010-r0002-proxy", choices)
        self.assertIn("run-c0010-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0011-r0001-proxy", choices)
        self.assertIn("run-c0011-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0011-r0002-proxy", choices)
        self.assertIn("run-c0011-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0012-r0001-proxy", choices)
        self.assertIn("run-c0012-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0012-r0002-proxy", choices)
        self.assertIn("run-c0012-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0012-r0003-proxy", choices)
        self.assertIn("run-c0012-r0003-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0003-sr0001-proxy", choices)
        self.assertIn("run-sc0003-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0004-sr0001-proxy", choices)
        self.assertIn("run-sc0004-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0005-sr0001-proxy", choices)
        self.assertIn("run-sc0005-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0006-sr0001-proxy", choices)
        self.assertIn("run-sc0006-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0008-sr0001-proxy", choices)
        self.assertIn("run-sc0008-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-sc0009-sr0001-proxy", choices)
        self.assertIn("run-sc0009-sr0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0013-r0001-proxy", choices)
        self.assertIn("run-c0013-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0014-r0001-proxy", choices)
        self.assertIn("run-c0014-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0015-r0001-proxy", choices)
        self.assertIn("run-c0015-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0016-r0001-proxy", choices)
        self.assertIn("run-c0016-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0017-r0001-proxy", choices)
        self.assertIn("run-c0017-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0018-r0001-proxy", choices)
        self.assertIn("run-c0018-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0019-r0001-proxy", choices)
        self.assertIn("run-c0019-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0020-r0001-proxy", choices)
        self.assertIn("run-c0020-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0021-r0001-proxy", choices)
        self.assertIn("run-c0021-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0022-r0001-proxy", choices)
        self.assertIn("run-c0022-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0023-r0001-proxy", choices)
        self.assertIn("run-c0023-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0024-r0001-proxy", choices)
        self.assertIn("run-c0024-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0025-r0001-proxy", choices)
        self.assertIn("run-c0025-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0026-r0001-proxy", choices)
        self.assertIn("run-c0026-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0027-r0001-proxy", choices)
        self.assertIn("run-c0027-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0028-r0001-proxy", choices)
        self.assertIn("run-c0028-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0029-r0001-proxy", choices)
        self.assertIn("run-c0029-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0030-r0001-proxy", choices)
        self.assertIn("run-c0030-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0031-r0001-proxy", choices)
        self.assertIn("run-c0031-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0032-r0001-proxy", choices)
        self.assertIn("run-c0032-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0033-r0001-proxy", choices)
        self.assertIn("run-c0033-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0034-r0001-proxy", choices)
        self.assertIn("run-c0034-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0035-r0001-proxy", choices)
        self.assertIn("run-c0035-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0036-r0001-proxy", choices)
        self.assertIn("run-c0036-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0037-r0001-proxy", choices)
        self.assertIn("run-c0037-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0037-r0002-proxy", choices)
        self.assertIn("run-c0037-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0037-r0003-proxy", choices)
        self.assertIn("run-c0037-r0003-mt5-tick-by-fold", choices)
        self.assertIn("run-c0037-r0004-proxy", choices)
        self.assertIn("run-c0037-r0004-mt5-tick-by-fold", choices)
        self.assertIn("run-c0040-r0001-proxy", choices)
        self.assertIn("run-c0040-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0041-r0001-proxy", choices)
        self.assertIn("run-c0041-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0042-r0001-proxy", choices)
        self.assertIn("run-c0042-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0043-r0001-proxy", choices)
        self.assertIn("run-c0043-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0044-r0001-proxy", choices)
        self.assertIn("run-c0044-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0045-r0001-proxy", choices)
        self.assertIn("run-c0045-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0045-r0002-proxy", choices)
        self.assertIn("run-c0045-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0045-r0003-proxy", choices)
        self.assertIn("run-c0045-r0003-mt5-tick-by-fold", choices)
        self.assertIn("run-c0046-r0001-proxy", choices)
        self.assertIn("run-c0046-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0046-r0002-proxy", choices)
        self.assertIn("run-c0046-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0047-r0001-proxy", choices)
        self.assertIn("run-c0047-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0047-r0002-proxy", choices)
        self.assertIn("run-c0047-r0002-mt5-tick-by-fold", choices)
        self.assertIn("run-c0048-r0001-proxy", choices)
        self.assertIn("run-c0048-r0001-mt5-tick-by-fold", choices)
        self.assertIn("run-c0048-r0002-proxy", choices)
        self.assertIn("run-c0048-r0002-mt5-tick-by-fold", choices)

    def test_cli_keeps_run_modules_out_of_top_level_imports(self) -> None:
        text = CLI_PATH.read_text(encoding="ascii")
        forbidden = (
            "from .mt5.",
            "from .proxies.",
            "from .collectors.mt5_fresh_export",
            "from .pipelines.",
        )
        offenders = [pattern for pattern in forbidden if pattern in text]
        self.assertEqual(offenders, [])

    def test_registry_targets_resolve(self) -> None:
        missing = []
        for command, spec in COMMANDS.items():
            if spec.target is None:
                continue
            try:
                target = resolve_target(spec.target)
            except Exception as exc:  # pragma: no cover - failure context is reported below.
                missing.append(f"{command}: {spec.target}: {exc}")
                continue
            if not callable(target):
                missing.append(f"{command}: {spec.target}: not callable")
        self.assertEqual(missing, [])

    def test_light_commands_do_not_import_mt5_or_proxy_modules(self) -> None:
        for command in ("status", "validate-templates", "validate-repo-state"):
            with self.subTest(command=command):
                loaded = self._loaded_run_modules_after_command(command)
                self.assertEqual(loaded, [])

    def _loaded_run_modules_after_command(self, command: str) -> list[str]:
        script = (
            "import json, sys\n"
            "from axiom_rift.cli import main\n"
            f"rc = main(['{command}'])\n"
            "loaded = sorted(\n"
            "    name for name in sys.modules\n"
            "    if name.startswith('axiom_rift.mt5.') or name.startswith('axiom_rift.proxies.')\n"
            ")\n"
            "print('__LOADED__' + json.dumps({'rc': rc, 'loaded': loaded}))\n"
            "raise SystemExit(0)\n"
        )
        env = os.environ.copy()
        src_path = str(PROJECT_ROOT / "src")
        env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        marker = next(line for line in result.stdout.splitlines() if line.startswith("__LOADED__"))
        payload = json.loads(marker.removeprefix("__LOADED__"))
        if command != "validate-repo-state":
            self.assertEqual(payload["rc"], 0)
        return payload["loaded"]


if __name__ == "__main__":
    unittest.main()
