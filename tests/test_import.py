import unittest

from axiom_rift import __version__
from axiom_rift.cli import build_parser


class ImportTest(unittest.TestCase):
    def test_version_is_defined(self) -> None:
        self.assertTrue(__version__)

    def test_cli_has_expected_commands(self) -> None:
        parser = build_parser()
        command_actions = [action for action in parser._actions if action.dest == "command"]
        choices = command_actions[0].choices
        self.assertIn("export-mt5-max-bars", choices)
        self.assertIn("build-us100-base-frame", choices)
        self.assertIn("derive-us100-clean-periods", choices)
        self.assertIn("build-us100-rolling-windows", choices)


if __name__ == "__main__":
    unittest.main()
