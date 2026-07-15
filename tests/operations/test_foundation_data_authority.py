from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest

import yaml

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.foundation_data_authority import (
    FoundationDataAuthorityError,
    FoundationDataDerivationProof,
    build_foundation_data_derivation_proof,
    foundation_data_derivation_binding,
    validate_foundation_data_identity_transition,
    verify_foundation_data_derivation_proof,
)
from axiom_rift.operations.writer import (
    InjectedCrash,
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.storage.journal import JournalIntegrityError


FIELDS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
PARENT_RELATIVE = "data/processed/datasets/base.csv"
OBSERVED_RELATIVE = "data/processed/datasets/observed.csv"
SPLIT_RELATIVE = "data/processed/coverage_audits/split.json"
COVERAGE_RELATIVE = "data/processed/coverage_audits/coverage.json"
RAW_RELATIVE = "data/raw/mt5_bars/m5/source.csv"
FIXED_NOW = "2026-07-15T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)


def csv_row(timestamp: str, close: int) -> bytes:
    return f"{timestamp},1,1000,0.5,{close},10,3,0\n".encode("ascii")


class FoundationDataFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.header = (",".join(FIELDS) + "\n").encode("ascii")
        self.rows = (
            csv_row("2026-01-01 00:00:00", 1),
            csv_row("2026-01-01 00:05:00", 2),
            csv_row("2026-01-01 00:10:00", 3),
            csv_row("2026-01-01 00:15:00", 4),
        )
        self.parent = self.header + b"".join(self.rows)
        self.observed = self.header + b"".join(self.rows[:3])
        self.raw = b"opaque synthetic broker export\n"
        self._write(RAW_RELATIVE, self.raw)
        self._write(PARENT_RELATIVE, self.parent)
        self._write(OBSERVED_RELATIVE, self.observed)
        self.split = {
            "fold_count": 1,
            "folds": [
                {
                    "fold_id": "rw_001",
                    "train_is": {
                        "end": "2026-01-01 00:00:00",
                        "row_count": 1,
                        "start": "2026-01-01 00:00:00",
                    },
                    "validation_oos": {
                        "end": "2026-01-01 00:05:00",
                        "row_count": 1,
                        "start": "2026-01-01 00:05:00",
                    },
                    "test_oos": {
                        "end": "2026-01-01 00:10:00",
                        "row_count": 1,
                        "start": "2026-01-01 00:10:00",
                    },
                }
            ],
            "schema": "axiom_rift_rolling_windows_v1",
            "source_base_frame": PARENT_RELATIVE,
            "tail_holdout_partial": {
                "end": "2026-01-01 00:15:00",
                "row_count": 1,
                "start": "2026-01-01 00:15:00",
            },
        }
        self.split_bytes = json.dumps(
            self.split, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
        self._write(SPLIT_RELATIVE, self.split_bytes)
        self.coverage = {
            "blackout_gaps": [],
            "observed": {
                "blackout_gap_count": 0,
                "flag_for_review_gap_count": 0,
                "gap_event_count": 0,
                "suspicious_gap_count": 0,
            },
            "schema": "axiom_rift_clean_periods_v1",
            "source_base_frame": PARENT_RELATIVE,
            "suspicious_gaps": [],
        }
        self.coverage_bytes = json.dumps(
            self.coverage,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        self._write(COVERAGE_RELATIVE, self.coverage_bytes)
        self.data_document, self.exposure_document = self.documents()

    def _write(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def documents(
        self,
        *,
        observed_content: bytes | None = None,
        parent_content: bytes | None = None,
    ) -> tuple[bytes, bytes]:
        observed_content = self.observed if observed_content is None else observed_content
        parent_content = self.parent if parent_content is None else parent_content
        parent_sha256 = sha256(parent_content).hexdigest()
        observed_sha256 = sha256(observed_content).hexdigest()
        split_sha256 = sha256(self.split_bytes).hexdigest()
        identity_inputs = {
            "dataset_sha256": parent_sha256,
            "split_artifact_sha256": split_sha256,
            "observed_window_count": 1,
            "last_observed_development_time": "2026-01-01 00:10:00",
        }
        material_identity = canonical_digest(
            domain="development-material", payload=identity_inputs
        )
        data = {
            "schema": "data_foundation",
            "status": "preserved_intake_observation",
            "target": "FPMarkets_US100_M5",
            "raw": {
                "path": RAW_RELATIVE,
                "sha256": sha256(self.raw).hexdigest(),
            },
            "processed": {
                "path": PARENT_RELATIVE,
                "sha256": parent_sha256,
                "row_count": 4,
                "first_time": "2026-01-01 00:00:00",
                "last_time": "2026-01-01 00:15:00",
                "fields": list(FIELDS),
            },
            "observed_development": {
                "path": OBSERVED_RELATIVE,
                "sha256": observed_sha256,
                "byte_count": len(observed_content),
                "row_count": 3,
                "first_time": "2026-01-01 00:00:00",
                "last_time": "2026-01-01 00:10:00",
                "parent_dataset_sha256": parent_sha256,
                "split_artifact_sha256": split_sha256,
                "derivation": "exact_prefix_before_quarantined_tail",
            },
            "split_artifact": {
                "path": SPLIT_RELATIVE,
                "sha256": split_sha256,
            },
            "coverage": {
                "path": COVERAGE_RELATIVE,
                "sha256": sha256(self.coverage_bytes).hexdigest(),
                "blackout_boundaries": 0,
                "review_boundaries": 0,
                "timestamp_gaps": 0,
            },
            "quality_observations": {
                "duplicate_rows": 0,
                "non_monotonic_rows": 0,
                "off_grid_rows": 0,
                "nonfinite_rows": 0,
                "negative_spread_rows": 0,
                "invalid_ohlc_rows": 0,
                "raw_to_processed_row_mismatches": 0,
                "zero_spread_rows": 0,
            },
            "volume_semantics": {
                "tick_volume": "broker_tick_count_not_traded_volume",
                "real_volume": {"eligible": False, "nonzero_rows": 0},
            },
            "protection": {
                "ignored_by_git": True,
                "recoverable_from_git": False,
                "recursive_cleanup_allowed": False,
            },
        }
        exposure = {
            "schema": "data_exposure_foundation",
            "status": "binding_prior_exposure",
            "identity_profile": "axiom_cjson_v1",
            "observed_development_material": {
                "identity": material_identity,
                "identity_domain": "development-material",
                "identity_inputs": identity_inputs,
                "display_name_is_identity": False,
                "roles": {
                    "train": "observed_development",
                    "calibration": "observed_development",
                    "adaptive_development": "observed_development",
                },
                "may_be_relabelled_fresh": False,
                "prior_global_multiplicity_floor": 18,
            },
            "quarantined_tail": {
                "start": "2026-01-01 00:15:00",
                "end": "2026-01-01 00:15:00",
                "status": "quarantine_pending_access_audit",
                "scientific_raw_access_allowed": False,
                "claim_use_allowed": False,
            },
            "forward_holdout": {
                "starts_after": "2026-01-01 00:15:00",
                "status": "awaiting_future_data",
                "reveal_count": 0,
                "permitted_reveals_max": 1,
            },
            "restricted_confirmation": {
                "redesign_after_observation_reclassifies_surface_as_development": True,
                "reuse_as_untouched_confirmation_after_redesign": False,
            },
            "sealed_ingestion": {
                "engineering_hash_and_seal_allowed": True,
                "scientific_value_read_requires_one_time_permit": True,
                "ingestion_changes_reveal_count": False,
            },
        }
        return (
            yaml.safe_dump(data, sort_keys=False).encode("ascii"),
            yaml.safe_dump(exposure, sort_keys=False).encode("ascii"),
        )


class FoundationDataAuthorityProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.fixture = FoundationDataFixture(self.root)

    def test_exact_parent_prefix_derivation_builds_canonical_typed_proof(self) -> None:
        proof = build_foundation_data_derivation_proof(
            self.root,
            data_document=self.fixture.data_document,
            data_exposure_document=self.fixture.exposure_document,
        )

        parsed = FoundationDataDerivationProof.from_bytes(proof.to_bytes())
        self.assertEqual(parsed, proof)
        self.assertEqual(proof.parent_row_count, 4)
        self.assertEqual(proof.observed_row_count, 3)
        self.assertEqual(proof.quarantined_row_count, 1)
        self.assertEqual(proof.parent_byte_count, len(self.fixture.parent))
        binding = foundation_data_derivation_binding(proof)
        self.assertEqual(binding["material_identity"], proof.material_identity)
        self.assertEqual(binding["proof_id"], proof.identity)
        self.assertEqual(binding["proof_hash"], sha256(proof.to_bytes()).hexdigest())
        verify_foundation_data_derivation_proof(
            self.root,
            proof=proof,
            data_document=self.fixture.data_document,
            data_exposure_document=self.fixture.exposure_document,
        )

    def test_self_consistent_malicious_prefix_is_rejected_against_parent_bytes(self) -> None:
        malicious = (
            self.fixture.header
            + self.fixture.rows[0]
            + csv_row("2026-01-01 00:05:00", 999)
            + self.fixture.rows[2]
        )
        self.fixture._write(OBSERVED_RELATIVE, malicious)
        data_document, exposure_document = self.fixture.documents(
            observed_content=malicious
        )

        with self.assertRaisesRegex(
            FoundationDataAuthorityError,
            "not the exact parent prefix",
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_fake_prefix_digest_size_row_and_timestamp_metadata_fail_closed(self) -> None:
        mutations = {
            "digest": lambda observed: observed.__setitem__("sha256", "0" * 64),
            "byte_count": lambda observed: observed.__setitem__(
                "byte_count", observed["byte_count"] + 1
            ),
            "row_count": lambda observed: observed.__setitem__("row_count", 2),
            "first_time": lambda observed: observed.__setitem__(
                "first_time", "2026-01-01 00:05:00"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                data = yaml.safe_load(self.fixture.data_document.decode("ascii"))
                mutate(data["observed_development"])
                data_document = yaml.safe_dump(data, sort_keys=False).encode("ascii")
                with self.assertRaises(FoundationDataAuthorityError):
                    build_foundation_data_derivation_proof(
                        self.root,
                        data_document=data_document,
                        data_exposure_document=self.fixture.exposure_document,
                    )

    def test_exact_off_grid_prefix_is_rejected_even_when_all_hashes_match(self) -> None:
        off_grid_rows = (
            self.fixture.rows[0],
            csv_row("2026-01-01 00:06:00", 2),
            self.fixture.rows[2],
            self.fixture.rows[3],
        )
        parent = self.fixture.header + b"".join(off_grid_rows)
        observed = self.fixture.header + b"".join(off_grid_rows[:3])
        self.fixture._write(PARENT_RELATIVE, parent)
        self.fixture._write(OBSERVED_RELATIVE, observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=parent, observed_content=observed
        )

        with self.assertRaisesRegex(FoundationDataAuthorityError, "M5 grid"):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_self_consistent_fake_market_values_fail_observed_quality_validation(self) -> None:
        invalid_row = b"2026-01-01 00:05:00,10,5,1,8,10,3,0\n"
        rows = (
            self.fixture.rows[0],
            invalid_row,
            self.fixture.rows[2],
            self.fixture.rows[3],
        )
        parent = self.fixture.header + b"".join(rows)
        observed = self.fixture.header + b"".join(rows[:3])
        self.fixture._write(PARENT_RELATIVE, parent)
        self.fixture._write(OBSERVED_RELATIVE, observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=parent, observed_content=observed
        )

        with self.assertRaisesRegex(FoundationDataAuthorityError, "OHLC envelope"):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_self_consistent_nonpositive_ohlc_prices_are_rejected(self) -> None:
        negative_row = b"2026-01-01 00:05:00,-10,-5,-15,-8,10,3,0\n"
        rows = (
            self.fixture.rows[0],
            negative_row,
            self.fixture.rows[2],
            self.fixture.rows[3],
        )
        parent = self.fixture.header + b"".join(rows)
        observed = self.fixture.header + b"".join(rows[:3])
        self.fixture._write(PARENT_RELATIVE, parent)
        self.fixture._write(OBSERVED_RELATIVE, observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=parent, observed_content=observed
        )

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "strictly positive"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_actual_tail_timestamp_must_match_quarantine_boundary(self) -> None:
        rows = (*self.fixture.rows[:3], csv_row("2026-01-01 00:20:00", 4))
        parent = self.fixture.header + b"".join(rows)
        self.fixture._write(PARENT_RELATIVE, parent)
        data_document, exposure_document = self.fixture.documents(
            parent_content=parent
        )

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "parent dataset last time differs"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_malformed_rolling_window_order_is_rejected_under_new_split_hash(self) -> None:
        malformed = deepcopy(self.fixture.split)
        malformed["folds"][0]["validation_oos"]["start"] = (
            "2026-01-01 00:00:00"
        )
        malformed["folds"][0]["validation_oos"]["row_count"] = 2
        self.fixture.split_bytes = json.dumps(
            malformed, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
        self.fixture._write(SPLIT_RELATIVE, self.fixture.split_bytes)
        data_document, exposure_document = self.fixture.documents()

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "not ordered and disjoint"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=data_document,
                data_exposure_document=exposure_document,
            )

    def test_material_identity_domain_cannot_reset_identical_data_history(self) -> None:
        exposure = yaml.safe_load(self.fixture.exposure_document.decode("ascii"))
        material = exposure["observed_development_material"]
        material["identity_domain"] = "renamed-development-material"
        material["identity"] = canonical_digest(
            domain=material["identity_domain"], payload=material["identity_inputs"]
        )
        exposure_document = yaml.safe_dump(exposure, sort_keys=False).encode("ascii")

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "identity domain differs"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=self.fixture.data_document,
                data_exposure_document=exposure_document,
            )

    def test_minimal_data_exposure_document_is_not_authority(self) -> None:
        exposure = yaml.safe_load(self.fixture.exposure_document.decode("ascii"))
        material = exposure["observed_development_material"]
        for name in (
            "display_name_is_identity",
            "roles",
            "prior_global_multiplicity_floor",
        ):
            del material[name]
        quarantine = exposure["quarantined_tail"]
        del quarantine["status"]
        del quarantine["claim_use_allowed"]
        del exposure["forward_holdout"]
        del exposure["restricted_confirmation"]
        del exposure["sealed_ingestion"]

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "fields differ"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=self.fixture.data_document,
                data_exposure_document=yaml.safe_dump(
                    exposure, sort_keys=False
                ).encode("ascii"),
            )

    def test_access_claim_holdout_and_policy_weakening_is_rejected(self) -> None:
        data = yaml.safe_load(self.fixture.data_document.decode("ascii"))
        exposure = yaml.safe_load(self.fixture.exposure_document.decode("ascii"))
        cases: list[tuple[str, dict, dict]] = []

        changed_exposure = deepcopy(exposure)
        changed_exposure["quarantined_tail"]["claim_use_allowed"] = True
        cases.append(("claim_use", deepcopy(data), changed_exposure))

        changed_exposure = deepcopy(exposure)
        changed_exposure["quarantined_tail"][
            "scientific_raw_access_allowed"
        ] = True
        cases.append(("raw_access", deepcopy(data), changed_exposure))

        for field in (
            "forward_holdout",
            "restricted_confirmation",
            "sealed_ingestion",
        ):
            changed_exposure = deepcopy(exposure)
            del changed_exposure[field]
            cases.append((f"missing_{field}", deepcopy(data), changed_exposure))

        changed_exposure = deepcopy(exposure)
        changed_exposure["restricted_confirmation"][
            "reuse_as_untouched_confirmation_after_redesign"
        ] = True
        cases.append(("restricted_reuse", deepcopy(data), changed_exposure))

        changed_exposure = deepcopy(exposure)
        changed_exposure["sealed_ingestion"][
            "scientific_value_read_requires_one_time_permit"
        ] = False
        cases.append(("sealed_read", deepcopy(data), changed_exposure))

        changed_exposure = deepcopy(exposure)
        changed_exposure["observed_development_material"]["roles"][
            "train"
        ] = "quarantined_tail"
        cases.append(("material_role", deepcopy(data), changed_exposure))

        changed_exposure = deepcopy(exposure)
        changed_exposure["identity_profile"] = "caller_identity_v1"
        cases.append(("identity_profile", deepcopy(data), changed_exposure))

        changed_data = deepcopy(data)
        changed_data["target"] = "OTHER_MARKET"
        cases.append(("target", changed_data, deepcopy(exposure)))

        changed_data = deepcopy(data)
        changed_data["protection"]["recursive_cleanup_allowed"] = True
        cases.append(("protection", changed_data, deepcopy(exposure)))

        for label, proposed_data, proposed_exposure in cases:
            with self.subTest(label=label):
                with self.assertRaises(FoundationDataAuthorityError):
                    build_foundation_data_derivation_proof(
                        self.root,
                        data_document=yaml.safe_dump(
                            proposed_data, sort_keys=False
                        ).encode("ascii"),
                        data_exposure_document=yaml.safe_dump(
                            proposed_exposure, sort_keys=False
                        ).encode("ascii"),
                    )

    def test_raw_source_path_hash_and_actual_bytes_are_bound(self) -> None:
        data = yaml.safe_load(self.fixture.data_document.decode("ascii"))

        wrong_hash = deepcopy(data)
        wrong_hash["raw"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "raw source SHA-256 differs"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=yaml.safe_dump(wrong_hash, sort_keys=False).encode(
                    "ascii"
                ),
                data_exposure_document=self.fixture.exposure_document,
            )

        wrong_path = deepcopy(data)
        wrong_path["raw"]["path"] = PARENT_RELATIVE
        wrong_path["raw"]["sha256"] = sha256(self.fixture.parent).hexdigest()
        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "escapes its data lane"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=yaml.safe_dump(wrong_path, sort_keys=False).encode(
                    "ascii"
                ),
                data_exposure_document=self.fixture.exposure_document,
            )

        self.fixture._write(RAW_RELATIVE, self.fixture.raw + b"drift")
        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "raw source SHA-256 differs"
        ):
            build_foundation_data_derivation_proof(
                self.root,
                data_document=self.fixture.data_document,
                data_exposure_document=self.fixture.exposure_document,
            )

    def test_unchanged_identity_rejects_formatting_and_dynamic_metadata_edits(
        self,
    ) -> None:
        data = yaml.safe_load(self.fixture.data_document.decode("ascii"))
        cases: dict[str, bytes] = {
            "formatting": yaml.safe_dump(data, sort_keys=True).encode("ascii"),
        }
        metadata = deepcopy(data)
        metadata["quality_observations"]["zero_spread_rows"] = 1
        cases["quality_metadata"] = yaml.safe_dump(
            metadata, sort_keys=False
        ).encode("ascii")
        alternate_raw_relative = "data/raw/mt5_bars/m5/alternate.csv"
        self.fixture._write(alternate_raw_relative, self.fixture.raw)
        alternate_raw = deepcopy(data)
        alternate_raw["raw"]["path"] = alternate_raw_relative
        cases["raw_path_metadata"] = yaml.safe_dump(
            alternate_raw, sort_keys=False
        ).encode("ascii")

        for label, data_document in cases.items():
            with self.subTest(label=label):
                proof = build_foundation_data_derivation_proof(
                    self.root,
                    data_document=data_document,
                    data_exposure_document=self.fixture.exposure_document,
                )
                with self.assertRaisesRegex(
                    FoundationDataAuthorityError,
                    "requires changed material identity inputs",
                ):
                    validate_foundation_data_identity_transition(
                        predecessor_data_document=self.fixture.data_document,
                        predecessor_data_exposure_document=(
                            self.fixture.exposure_document
                        ),
                        successor_proof=proof,
                    )

    def test_new_material_cannot_mutate_non_derivation_policy_projection(
        self,
    ) -> None:
        changed_parent = (
            self.fixture.header
            + self.fixture.rows[0]
            + csv_row("2026-01-01 00:05:00", 22)
            + self.fixture.rows[2]
            + self.fixture.rows[3]
        )
        changed_observed = changed_parent[: -len(self.fixture.rows[3])]
        self.fixture._write(PARENT_RELATIVE, changed_parent)
        self.fixture._write(OBSERVED_RELATIVE, changed_observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=changed_parent,
            observed_content=changed_observed,
        )
        exposure = yaml.safe_load(exposure_document.decode("ascii"))
        exposure["observed_development_material"][
            "prior_global_multiplicity_floor"
        ] = 19
        exposure_document = yaml.safe_dump(exposure, sort_keys=False).encode(
            "ascii"
        )
        proof = build_foundation_data_derivation_proof(
            self.root,
            data_document=data_document,
            data_exposure_document=exposure_document,
        )

        with self.assertRaisesRegex(
            FoundationDataAuthorityError, "non-derivation policy changed"
        ):
            validate_foundation_data_identity_transition(
                predecessor_data_document=self.fixture.data_document,
                predecessor_data_exposure_document=self.fixture.exposure_document,
                successor_proof=proof,
            )

    def test_parent_change_requires_a_new_material_identity(self) -> None:
        changed_parent = (
            self.fixture.header
            + self.fixture.rows[0]
            + csv_row("2026-01-01 00:05:00", 22)
            + self.fixture.rows[2]
            + self.fixture.rows[3]
        )
        changed_observed = changed_parent[: -len(self.fixture.rows[3])]
        self.fixture._write(PARENT_RELATIVE, changed_parent)
        self.fixture._write(OBSERVED_RELATIVE, changed_observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=changed_parent,
            observed_content=changed_observed,
        )

        changed = build_foundation_data_derivation_proof(
            self.root,
            data_document=data_document,
            data_exposure_document=exposure_document,
        )
        original_identity = canonical_digest(
            domain="development-material",
            payload={
                "dataset_sha256": sha256(self.fixture.parent).hexdigest(),
                "split_artifact_sha256": sha256(self.fixture.split_bytes).hexdigest(),
                "observed_window_count": 1,
                "last_observed_development_time": "2026-01-01 00:10:00",
            },
        )
        self.assertNotEqual(changed.material_identity, original_identity)
        self.assertNotEqual(changed.parent_sha256, sha256(self.fixture.parent).hexdigest())
        validate_foundation_data_identity_transition(
            predecessor_data_document=self.fixture.data_document,
            predecessor_data_exposure_document=self.fixture.exposure_document,
            successor_proof=changed,
        )

    def test_each_material_identity_input_rekeys_the_prospective_material(self) -> None:
        original = {
            "dataset_sha256": "1" * 64,
            "split_artifact_sha256": "2" * 64,
            "observed_window_count": 1,
            "last_observed_development_time": "2026-01-01 00:10:00",
        }
        original_identity = canonical_digest(
            domain="development-material", payload=original
        )
        changed_values = {
            "dataset_sha256": "3" * 64,
            "split_artifact_sha256": "4" * 64,
            "observed_window_count": 2,
            "last_observed_development_time": "2026-01-01 00:15:00",
        }
        for name, changed_value in changed_values.items():
            with self.subTest(name=name):
                successor = dict(original)
                successor[name] = changed_value
                self.assertNotEqual(
                    canonical_digest(
                        domain="development-material", payload=successor
                    ),
                    original_identity,
                )

    def test_proof_revalidation_detects_post_plan_prefix_drift(self) -> None:
        proof = build_foundation_data_derivation_proof(
            self.root,
            data_document=self.fixture.data_document,
            data_exposure_document=self.fixture.exposure_document,
        )
        drifted = bytearray(self.fixture.observed)
        drifted[-3] = ord("9")
        self.fixture._write(OBSERVED_RELATIVE, bytes(drifted))

        with self.assertRaises(FoundationDataAuthorityError):
            verify_foundation_data_derivation_proof(
                self.root,
                proof=proof,
                data_document=self.fixture.data_document,
                data_exposure_document=self.fixture.exposure_document,
            )


class FoundationDataAuthorityMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for relative in AUTHORITY_PATHS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            copyfile(REPO_ROOT / relative, target)
        self.fixture = FoundationDataFixture(self.root)
        (self.root / "foundation/data.yaml").write_bytes(
            self.fixture.data_document
        )
        (self.root / "foundation/data_exposure.yaml").write_bytes(
            self.fixture.exposure_document
        )
        self.writer = StateWriter(
            self.root,
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=self.root,
        )
        initialized = self.writer.initialize_ready()
        self.assertEqual(initialized.revision, 1)

    def prospective(
        self, close: int
    ) -> tuple[dict[str, bytes], bytes, bytes]:
        rows = (
            self.fixture.rows[0],
            csv_row("2026-01-01 00:05:00", close),
            self.fixture.rows[2],
            self.fixture.rows[3],
        )
        parent = self.fixture.header + b"".join(rows)
        observed = self.fixture.header + b"".join(rows[:3])
        self.fixture._write(PARENT_RELATIVE, parent)
        self.fixture._write(OBSERVED_RELATIVE, observed)
        data_document, exposure_document = self.fixture.documents(
            parent_content=parent,
            observed_content=observed,
        )
        return (
            {
                "foundation/data.yaml": data_document,
                "foundation/data_exposure.yaml": exposure_document,
            },
            parent,
            observed,
        )

    def migrate(
        self,
        *,
        replacements: dict[str, bytes],
        operation_id: str,
        crash_after: str | None = None,
    ):
        return self.writer.migrate_foundation_data_authority(
            replacements=replacements,
            reason="activate exact prospective Foundation data derivation",
            operation_id=operation_id,
            crash_after=crash_after,
        )

    def test_generic_migration_rejects_each_protected_and_mixed_path_set(
        self,
    ) -> None:
        ordinary = (self.root / "contracts/runtime.yaml").read_bytes()
        cases = {
            "data": {
                "foundation/data.yaml": self.fixture.data_document + b"# no\n"
            },
            "exposure": {
                "foundation/data_exposure.yaml": (
                    self.fixture.exposure_document + b"# no\n"
                )
            },
            "mixed": {
                "foundation/data.yaml": self.fixture.data_document + b"# no\n",
                "contracts/runtime.yaml": ordinary + b"# no\n",
            },
        }
        for label, replacements in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    TransitionError, "typed derivation boundary"
                ):
                    self.writer.migrate_authority(
                        replacements=replacements,
                        reason="generic path must fail closed",
                        operation_id=f"generic-protected-{label}",
                    )
        self.assertEqual(len(self.writer.journal.read_all()), 1)

    def test_typed_migration_requires_exactly_both_protected_documents(self) -> None:
        replacements, _parent, _observed = self.prospective(22)
        cases = {
            "one": {"foundation/data.yaml": replacements["foundation/data.yaml"]},
            "extra": {
                **replacements,
                "contracts/runtime.yaml": (
                    (self.root / "contracts/runtime.yaml").read_bytes()
                    + b"# no\n"
                ),
            },
        }
        for label, proposed in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    TransitionError, "requires exactly both data documents"
                ):
                    self.migrate(
                        replacements=proposed,
                        operation_id=f"typed-path-set-{label}",
                    )
        self.assertEqual(len(self.writer.journal.read_all()), 1)

    def test_valid_typed_migration_binds_documents_proof_and_new_material(self) -> None:
        predecessor = build_foundation_data_derivation_proof(
            self.root,
            data_document=self.fixture.data_document,
            data_exposure_document=self.fixture.exposure_document,
        )
        replacements, _parent, _observed = self.prospective(22)

        result = self.migrate(
            replacements=replacements,
            operation_id="foundation-data-valid",
        )

        self.assertEqual(result.revision, 2)
        event = self.writer.journal.read_all()[-1]
        binding = event["payload"]["foundation_data_derivation"]
        self.assertNotEqual(binding["material_identity"], predecessor.material_identity)
        self.assertEqual(
            {row["path"] for row in event["payload"]["replacements"]},
            {"foundation/data.yaml", "foundation/data_exposure.yaml"},
        )
        evidence_hashes = {
            item["sha256"] for item in event["payload"]["evidence"]
        }
        self.assertTrue(
            {
                binding["data_document_sha256"],
                binding["data_exposure_document_sha256"],
                binding["proof_hash"],
            }.issubset(evidence_hashes)
        )
        self.assertEqual(
            (self.root / "foundation/data.yaml").read_bytes(),
            replacements["foundation/data.yaml"],
        )
        self.assertEqual(
            (self.root / "foundation/data_exposure.yaml").read_bytes(),
            replacements["foundation/data_exposure.yaml"],
        )
        self.assertEqual(self.writer.recover()["journal_sequence"], 2)

    def test_same_operation_reuses_exact_proof_and_rejects_new_derivation(self) -> None:
        replacements, _parent, _observed = self.prospective(22)
        first = self.migrate(
            replacements=replacements,
            operation_id="foundation-data-idempotency",
        )
        retry_replacements, _parent, _observed = self.prospective(22)

        retried = self.migrate(
            replacements=retry_replacements,
            operation_id="foundation-data-idempotency",
        )

        self.assertTrue(retried.reused)
        self.assertEqual(retried.event_id, first.event_id)
        journal = (self.root / "records/journal.jsonl").read_bytes()
        changed_replacements, _parent, _observed = self.prospective(33)
        with self.assertRaisesRegex(
            TransitionError, "idempotency key reused with different input"
        ):
            self.migrate(
                replacements=changed_replacements,
                operation_id="foundation-data-idempotency",
            )
        self.assertEqual((self.root / "records/journal.jsonl").read_bytes(), journal)

    def test_after_journal_crash_revalidates_raw_derivation_before_recovery(self) -> None:
        replacements, _parent, observed = self.prospective(22)
        with self.assertRaisesRegex(InjectedCrash, "after_journal"):
            self.migrate(
                replacements=replacements,
                operation_id="foundation-data-after-journal",
                crash_after="after_journal",
            )
        self.assertEqual(self.writer.read_control()["revision"], 1)
        drifted = bytearray(observed)
        drifted[-3] = ord("9")
        self.fixture._write(OBSERVED_RELATIVE, bytes(drifted))

        with self.assertRaises(RecoveryRequired):
            self.writer.recover()

        self.fixture._write(OBSERVED_RELATIVE, observed)
        report = self.writer.recover()
        self.assertEqual(report["journal_sequence"], 2)
        self.assertEqual(self.writer.read_control()["revision"], 2)

    def test_applied_migration_recovery_latches_observed_and_parent_drift(self) -> None:
        replacements, parent, observed = self.prospective(22)
        self.migrate(
            replacements=replacements,
            operation_id="foundation-data-recovery-latch",
        )

        drifted_observed = bytearray(observed)
        drifted_observed[-3] = ord("9")
        self.fixture._write(OBSERVED_RELATIVE, bytes(drifted_observed))
        with self.assertRaises(RecoveryRequired):
            self.writer.recover()
        self.fixture._write(OBSERVED_RELATIVE, observed)
        self.assertEqual(self.writer.recover()["journal_sequence"], 2)

        drifted_parent = bytearray(parent)
        drifted_parent[-3] = ord("9")
        self.fixture._write(PARENT_RELATIVE, bytes(drifted_parent))
        with self.assertRaises(RecoveryRequired):
            self.writer.recover()

    def test_recovery_rejects_typed_binding_with_an_extra_replacement_row(self) -> None:
        replacements, _parent, _observed = self.prospective(22)
        self.migrate(
            replacements=replacements,
            operation_id="foundation-data-recovery-scope",
        )
        events = deepcopy(self.writer.journal.read_all())
        events[-1]["payload"]["replacements"].append(
            {
                "artifact_sha256": "1" * 64,
                "new_sha256": "1" * 64,
                "old_sha256": "2" * 64,
                "path": "contracts/runtime.yaml",
            }
        )
        control = self.writer.read_control()
        assert control is not None

        with self.assertRaisesRegex(
            JournalIntegrityError, "typed Foundation data migration path set"
        ):
            self.writer._apply_pending_authority_migrations(
                events=events,
                applied_sequence=len(events),
                final_authority=control["authority"],
            )


if __name__ == "__main__":
    unittest.main()
