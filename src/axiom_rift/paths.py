"""Project path helpers."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"
CONTRACT_DIR = PROJECT_ROOT / "contracts"
CAMPAIGN_DIR = PROJECT_ROOT / "campaigns"
REGISTRY_DIR = PROJECT_ROOT / "registries"
DATA_DIR = PROJECT_ROOT / "data"
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"
