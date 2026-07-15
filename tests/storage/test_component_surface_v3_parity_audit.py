from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.running_job import RunningJobAuthorityIntegrityError
from axiom_rift.operations.writer import StateWriter, ready_control_body
from axiom_rift.storage.index import LocalIndex


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_component_surface_v3_parity.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "audit_component_surface_v3_parity",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComponentSurfaceV3ParityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        workspace = Path(self.temporary.name).resolve()
        self.root = workspace / "repository"
        self.foundation_root = workspace / "foundation"
        authority = ready_control_body()["authority"]
        relative_paths = [
            authority["operating_direction"],
            *authority["contracts"],
            *authority["foundation_inputs"],
        ]
        for relative in relative_paths:
            destination = self.foundation_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, destination)
        self.writer = StateWriter(
            self.root,
            engineering_fixture=True,
            foundation_root=self.foundation_root,
        )
        self.writer.initialize_ready()
        self.module = load_script()

    def _audit(self):
        return self.module.audit(
            self.writer.index_path,
            expected_count=0,
            foundation_root=self.foundation_root,
        )

    def test_empty_authenticated_component_surface_has_exact_parity(self) -> None:
        result = self._audit()

        self.assertEqual(result["manifest_count"], 0)
        self.assertEqual(result["parity"], "exact")
        self.assertEqual(result["source_schema_version"], 3)

    def test_projection_mismatch_fails_before_component_claim(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index._connection.execute(  # noqa: SLF001 - adversarial fixture
                "UPDATE projection_stats SET projection_valid = 0 "
                "WHERE singleton = 1"
            )

        with self.assertRaisesRegex(
            RunningJobAuthorityIntegrityError,
            "read-only local index",
        ):
            self._audit()

    def test_files_are_ascii_and_script_has_no_raw_index_reader(self) -> None:
        source = SCRIPT.read_text(encoding="ascii")
        Path(__file__).read_text(encoding="ascii")
        self.assertNotIn("sqlite3.connect", source)
        self.assertNotIn("LocalIndex.open_read_only", source)
        self.assertIn("RunningJobAuthority", source)
        self.assertIn("open_stable_index", source)


if __name__ == "__main__":
    unittest.main()
