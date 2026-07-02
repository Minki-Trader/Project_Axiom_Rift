import tempfile
import unittest
from pathlib import Path

from axiom_rift.mt5.terminal_hygiene import HEADLESS_PROFILE_NAME, enforce_headless_terminal_state


class Mt5TerminalHygieneTest(unittest.TestCase):
    def test_enforces_headless_profile_and_cleans_owned_charts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            config_dir = data_dir / "config"
            config_dir.mkdir(parents=True)
            common_ini = config_dir / "common.ini"
            common_ini.write_bytes(
                "\r\n".join(
                    [
                        "",
                        "[Common]",
                        "Login=123",
                        "[Charts]",
                        "ProfileLast=British Pound",
                        "SaveDeleted=1",
                        "PreloadCharts=1",
                        "[Experts]",
                        "Chart=1",
                        "",
                    ]
                ).encode("utf-16")
            )
            terminal_ini = config_dir / "terminal.ini"
            terminal_ini.write_bytes(
                "\r\n".join(
                    [
                        "",
                        "[CodeBasesList]",
                        "MQL5AddChart=1",
                        "[Tester]",
                        "Visualization=1",
                        "Expert=Experts\\AxiomRift\\AxiomR0001VolatilityExpansion.ex5",
                        "",
                    ]
                ).encode("utf-16")
            )
            profile_dir = data_dir / "MQL5" / "Profiles" / "Charts" / HEADLESS_PROFILE_NAME
            profile_dir.mkdir(parents=True)
            chart_file = profile_dir / "chart01.chr"
            chart_file.write_text("symbol=US100\n", encoding="ascii")

            result = enforce_headless_terminal_state(data_dir)

            self.assertEqual(result.profile_dir, profile_dir.resolve())
            self.assertIn(common_ini, result.changed_files)
            self.assertIn(terminal_ini, result.changed_files)
            self.assertIn(chart_file, result.removed_chart_files)
            self.assertFalse(chart_file.exists())

            common_text = common_ini.read_bytes().decode("utf-16")
            self.assertIn(f"ProfileLast={HEADLESS_PROFILE_NAME}", common_text)
            self.assertIn("SaveDeleted=0", common_text)
            self.assertIn("PreloadCharts=0", common_text)
            self.assertIn("Chart=0", common_text)

            terminal_text = terminal_ini.read_bytes().decode("utf-16")
            self.assertIn("MQL5AddChart=0", terminal_text)
            self.assertIn("Visualization=0", terminal_text)
            self.assertIn("Expert=Experts\\AxiomRift\\AxiomR0001VolatilityExpansion.ex5", terminal_text)

    def test_creates_missing_ini_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            result = enforce_headless_terminal_state(data_dir)

            self.assertEqual(result.removed_chart_files, ())
            common_text = (data_dir / "config" / "common.ini").read_bytes().decode("utf-16")
            terminal_text = (data_dir / "config" / "terminal.ini").read_bytes().decode("utf-16")
            self.assertIn("[Charts]", common_text)
            self.assertIn(f"ProfileLast={HEADLESS_PROFILE_NAME}", common_text)
            self.assertIn("[Tester]", terminal_text)
            self.assertIn("Visualization=0", terminal_text)


if __name__ == "__main__":
    unittest.main()
