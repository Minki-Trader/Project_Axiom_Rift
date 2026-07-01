import json
import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.validation.work_units import validate_templates, validate_work_unit


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="ascii") as handle:
        return yaml.safe_load(handle)


def write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="ascii")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="ascii") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")


class WorkUnitValidationTest(unittest.TestCase):
    def test_current_templates_validate(self) -> None:
        result = validate_templates(PROJECT_ROOT)
        self.assertTrue(result.ok, result.to_dict())

    def test_generated_campaign_validates_when_required_values_are_filled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaign = make_campaign(root, leave_placeholder=False)

            result = validate_work_unit(campaign, root=root)

            self.assertTrue(result.ok, result.to_dict())

    def test_generated_campaign_fails_when_placeholder_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaign = make_campaign(root, leave_placeholder=True)

            result = validate_work_unit(campaign, root=root)

            self.assertFalse(result.ok)
            codes = {issue.code for issue in result.issues}
            self.assertIn("template_sentinel_left", codes)

    def test_generated_run_requires_mt5_kpi_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaign = make_campaign(root, leave_placeholder=False)
            make_run(campaign)
            (campaign / "runs" / "R0001" / "kpi" / "mt5.json").unlink()

            result = validate_work_unit(campaign, root=root)

            self.assertFalse(result.ok)
            codes = {issue.code for issue in result.issues}
            self.assertIn("missing_required_file", codes)


def make_campaign(root: Path, leave_placeholder: bool) -> Path:
    target = root / "campaigns" / "C0001_smoke"
    target.mkdir(parents=True)
    template_root = PROJECT_ROOT / "campaigns" / "_templates"

    campaign = load_yaml(template_root / "campaign.yaml")
    campaign["template"] = False
    campaign["campaign_id"] = "C0001"
    campaign["campaign_slug"] = "smoke"
    campaign["opened_at_utc"] = "2026-07-01T00:00:00Z"
    campaign["hypothesis"]["summary"] = "smoke hypothesis"
    campaign["hypothesis"]["boundary"] = "smoke boundary"
    for surface, entry in campaign["required_surfaces"].items():
        entry["summary"] = f"smoke {surface} surface"
    if leave_placeholder:
        campaign["hypothesis"]["summary"] = "placeholder_major_hypothesis"
    write_yaml(target / "campaign.yaml", campaign)

    inputs = load_yaml(template_root / "inputs.yaml")
    inputs["template"] = False
    inputs["work_unit_id"] = "C0001"
    inputs["data_refs"]["dataset_identity"] = "data/processed/datasets/us100_m5_base_frame.csv"
    write_yaml(target / "inputs.yaml", inputs)

    selected = load_yaml(template_root / "selected.yaml")
    selected["template"] = False
    write_yaml(target / "selected.yaml", selected)
    return target


def make_run(campaign: Path) -> Path:
    run = campaign / "runs" / "R0001"
    (run / "kpi").mkdir(parents=True)
    template_root = PROJECT_ROOT / "campaigns" / "_templates"

    manifest = load_json(template_root / "run_manifest.json")
    manifest["template"] = False
    manifest["work_unit_id"] = "C0001"
    manifest["run_id"] = "R0001"
    manifest["hypothesis_variant"]["summary"] = "smoke run variant"
    manifest["hypothesis_variant"]["variant_boundary"] = "smoke variant boundary"
    for surface, entry in manifest["surfaces"].items():
        entry["summary"] = f"smoke {surface} run surface"
    write_json(run / "run_manifest.json", manifest)

    gate = load_json(template_root / "gate_report.json")
    gate["template"] = False
    gate["work_unit_id"] = "C0001"
    gate["run_id"] = "R0001"
    gate["gate_report_id"] = "G0001"
    write_json(run / "gate_report.json", gate)

    lineage = load_json(template_root / "artifact_lineage.json")
    lineage["template"] = False
    lineage["work_unit_id"] = "C0001"
    lineage["run_id"] = "R0001"
    lineage["lineage_id"] = "L0001"
    lineage["artifact_records"][0]["artifact_id"] = "A0001"
    lineage["artifact_records"][0]["repo_relative_path"] = "campaigns/C0001_smoke/runs/R0001/kpi/proxy.json"
    lineage["artifact_records"][0]["produced_by"] = "unit_test"
    write_json(run / "artifact_lineage.json", lineage)

    proxy = load_json(template_root / "kpi" / "proxy.json")
    proxy["template"] = False
    proxy["work_unit_id"] = "C0001"
    proxy["campaign_id"] = "C0001"
    proxy["run_id"] = "R0001"
    proxy["proxy_id"] = "PX0001"
    proxy["dataset_identity"] = "data/processed/datasets/us100_m5_base_frame.csv"
    proxy["proxy_engine"] = "unit_test_proxy"
    write_json(run / "kpi" / "proxy.json", proxy)

    mt5 = load_json(template_root / "kpi" / "mt5.json")
    mt5["template"] = False
    mt5["work_unit_id"] = "C0001"
    mt5["campaign_id"] = "C0001"
    mt5["run_id"] = "R0001"
    mt5["mt5_probe_id"] = "MT50001"
    write_json(run / "kpi" / "mt5.json", mt5)

    comparison = load_json(template_root / "kpi" / "proxy_vs_mt5.json")
    comparison["template"] = False
    comparison["work_unit_id"] = "C0001"
    comparison["campaign_id"] = "C0001"
    comparison["run_id"] = "R0001"
    comparison["parity_id"] = "P0001"
    comparison["proxy_id"] = "PX0001"
    comparison["mt5_probe_id"] = "MT50001"
    write_json(run / "kpi" / "proxy_vs_mt5.json", comparison)
    return run


if __name__ == "__main__":
    unittest.main()
