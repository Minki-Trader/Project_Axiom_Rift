from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.jobs import scout as scout_job
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research import CANONICAL_ENGINE
from axiom_rift.v2.research import __all__ as research_exports
from axiom_rift.v2.research.programs import ProgramRegistryError, load_program_registry
from axiom_rift.v2.research.scout import ScoutSpecError, load_scout_spec


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_sha256(path: Path) -> str:
    return sha256_payload(yaml.safe_load(path.read_text(encoding="ascii")))


class V21CanonicalResearchTests(unittest.TestCase):
    def test_registry_declares_one_canonical_engine_and_hashes_each_program(self) -> None:
        registry = load_program_registry(PROJECT_ROOT)

        self.assertEqual(CANONICAL_ENGINE["feature_path"], "src/axiom_rift/v2/features.py")
        self.assertEqual(CANONICAL_ENGINE["scout_path"], "src/axiom_rift/v2/research/scout.py")
        self.assertEqual(
            {definition.kind for definition in registry.programs.values()},
            {"feature", "label", "model", "calibration", "selector", "trade"},
        )
        for definition in registry.programs.values():
            self.assertEqual(
                contract_sha256(PROJECT_ROOT / definition.contract_path),
                definition.contract_sha256,
            )
            self.assertEqual(len(definition.program_sha256), 64)
        self.assertIn("run_causal_scout", research_exports)
        self.assertIn("run_fixture_research", research_exports)
        self.assertNotIn("run_research", research_exports)

    def test_registry_rejects_a_contract_changed_after_registration(self) -> None:
        copied_paths = (
            "configs/v2/program_registry.yaml",
            "configs/v2/feature_programs/causal_bar_v1.yaml",
            "contracts/v2/research_contract.yaml",
            "src/axiom_rift/v2/features.py",
            "src/axiom_rift/v2/research/scout.py",
            "src/axiom_rift/v2/research/evaluation.py",
            "src/axiom_rift/v2/research/sensitivity.py",
            "src/axiom_rift/v2/research/core.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in copied_paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((PROJECT_ROOT / relative).read_bytes())
            load_program_registry(root)
            contract = root / "contracts/v2/research_contract.yaml"
            payload = yaml.safe_load(contract.read_text(encoding="ascii"))
            payload["status"] = "tampered"
            contract.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="ascii")

            with self.assertRaisesRegex(ProgramRegistryError, "contract hash mismatch"):
                load_program_registry(root)

    def test_scout_spec_resolves_exact_registered_program_identities(self) -> None:
        hypothesis = (
            PROJECT_ROOT
            / "campaigns/v2/V2G0001_v2_activation/hypotheses/V2H0001.yaml"
        )
        spec = load_scout_spec(hypothesis, PROJECT_ROOT)

        self.assertEqual(spec.goal_id, "V2G0001")
        self.assertEqual(spec.hypothesis_id, "V2H0001")
        self.assertEqual(spec.program_registry_path, "configs/v2/program_registry.yaml")
        self.assertEqual(
            set(spec.program_identities),
            {"feature", "label", "model", "calibration", "selector", "trade"},
        )

        payload = yaml.safe_load(hypothesis.read_text(encoding="ascii"))
        payload["executable_programs"]["model_program"]["id"] = "V2MP9999"
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "V2H9999.yaml"
            changed.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
                encoding="ascii",
            )
            with self.assertRaisesRegex(ScoutSpecError, "not registered"):
                load_scout_spec(changed, PROJECT_ROOT)

    def test_generic_scout_job_uses_supplied_goal_hypothesis_and_stage_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data/base.csv"
            split_path = root / "data/splits.json"
            boundary_path = root / "data/boundaries.json"
            for path, content in (
                (data_path, "time,open,high,low,close,tick_volume,spread\n"),
                (split_path, "{}\n"),
                (boundary_path, "{}\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="ascii")
            data_config = {
                "processed": {"path": "data/base.csv", "sha256": sha256_file(data_path)},
                "boundary_source": {
                    "path": "data/boundaries.json",
                    "sha256": sha256_file(boundary_path),
                },
            }
            split_config = {
                "source": {"path": "data/splits.json", "sha256": sha256_file(split_path)}
            }
            config_dir = root / "configs/v2"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "data.yaml").write_text(
                yaml.safe_dump(data_config, sort_keys=False), encoding="ascii"
            )
            (config_dir / "splits.yaml").write_text(
                yaml.safe_dump(split_config, sort_keys=False), encoding="ascii"
            )
            spec_path = root / "campaigns/v2/V2G0042/hypotheses/V2H0042.yaml"
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text("schema: test_fixture\n", encoding="ascii")
            output_dir = root / "campaigns/v2/V2G0042/evidence/V2S0042"
            fake_spec = SimpleNamespace(
                goal_id="V2G0042",
                hypothesis_id="V2H0042",
                spec_sha256="1" * 64,
                program_registry_path="configs/v2/program_registry.yaml",
                program_registry_sha256="2" * 64,
                program_identities={"feature": {"id": "V2FP0042"}},
            )
            fake_result = SimpleNamespace(
                metrics={"fixture": True},
                models=(),
                trades=(),
                causal_checks={"all_pass": True},
                outcome="route_to_R",
                gate_passed=True,
                claim_ceiling="diagnostic_observation",
                result_sha256="3" * 64,
            )
            with (
                patch.object(scout_job, "PROJECT_ROOT", root),
                patch.object(scout_job, "load_scout_spec", return_value=fake_spec),
                patch.object(scout_job, "run_causal_scout", return_value=fake_result),
            ):
                receipt = scout_job.run_scout_job(
                    "V2G0042", "V2H0042", "V2S0042", spec_path, output_dir
                )

            self.assertEqual(receipt["goal_id"], "V2G0042")
            self.assertEqual(receipt["hypothesis_id"], "V2H0042")
            self.assertEqual(receipt["stage_id"], "V2S0042")
            self.assertEqual(receipt["program_registry_sha256"], "2" * 64)
            self.assertTrue((output_dir / "receipt.json").is_file())


if __name__ == "__main__":
    unittest.main()
