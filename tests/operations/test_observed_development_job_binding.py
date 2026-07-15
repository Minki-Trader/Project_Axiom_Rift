from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.observed_development_binding import (
    ObservedDevelopmentBindingError,
    observed_development_job_binding,
    scientific_observed_development_job_binding,
    verify_observed_development_prefix_artifact,
)
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.storage.index import LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    _AUTHORITY_AND_FOUNDATION_PATHS,
    digest,
    initiative_objective,
    job_spec,
    mission_goal,
)


CURRENT_PREFIX_SHA256 = (
    "a7f097242f46ab45e8f58387c35a76a8c7d8ea1b04519f0878b66747442acbbe"
)


def _job_identity(
    *, mission_id: str, spec: dict[str, object], binding: dict[str, str] | None
) -> str:
    payload: dict[str, object] = {"mission_id": mission_id, "spec": spec}
    if binding is not None:
        payload["observed_development_binding"] = binding
    return canonical_digest(domain="job", payload=payload)


def _work_and_success_fingerprints(
    *, mission_id: str, spec: dict[str, object], binding: dict[str, str] | None
) -> tuple[str, str]:
    work: dict[str, object] = {
        "callable_identity": spec["callable_identity"],
        "component_parity_binding": spec.get("component_parity_binding"),
        "evidence_subject": spec["evidence_subject"],
        "external_dependency_binding": spec.get("external_dependency_binding"),
        "input_hashes": spec["input_hashes"],
        "holdout_binding": spec.get("holdout_binding"),
        "runtime_binding": spec.get("runtime_binding"),
        "scientific_binding": spec.get("scientific_binding"),
        "source_binding": spec.get("source_binding"),
    }
    if binding is not None:
        work["observed_development_binding"] = binding
    work_fingerprint = canonical_digest(
        domain="job-work", payload={"mission_id": mission_id, "work": work}
    )
    success: dict[str, object] = {
        "candidate_execution_context": None,
        "external_observed_development_binding": None,
        "expected_outputs": spec["expected_outputs"],
        "implementation_identity": spec["implementation_identity"],
        "implementation_source_authority": None,
        "mission_id": mission_id,
        "output_classes": spec["output_classes"],
        "work_fingerprint": work_fingerprint,
    }
    if binding is not None:
        success["observed_development_binding"] = binding
    return work_fingerprint, canonical_digest(
        domain="job-success-cache", payload=success
    )


class ObservedDevelopmentBindingModelTests(unittest.TestCase):
    def test_cache_reuse_guard_hashes_only_the_registered_prefix_bytes(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = root / "foundation"
            foundation.mkdir()
            exposure = REPO_ROOT / "foundation" / "data_exposure.yaml"
            (foundation / "data_exposure.yaml").write_bytes(
                exposure.read_bytes()
            )
            content = b"registered observed development prefix\n"
            content_hash = sha256(content).hexdigest()
            data = (REPO_ROOT / "foundation" / "data.yaml").read_bytes()
            data = data.replace(
                CURRENT_PREFIX_SHA256.encode("ascii"),
                content_hash.encode("ascii"),
            ).replace(
                b"byte_count: 37029769",
                f"byte_count: {len(content)}".encode("ascii"),
            )
            (foundation / "data.yaml").write_bytes(data)
            prefix = (
                root
                / "data"
                / "processed"
                / "datasets"
                / "us100_m5_observed_development.csv"
            )
            prefix.parent.mkdir(parents=True)
            prefix.write_bytes(content)
            binding = observed_development_job_binding(
                foundation_root=root,
                input_hashes=(OBSERVED_MATERIAL_ID,),
            )
            self.assertIsNotNone(binding)
            assert binding is not None
            verify_observed_development_prefix_artifact(
                foundation_root=root,
                binding=binding,
            )

            prefix.write_bytes(b"X" + content[1:])
            with self.assertRaisesRegex(
                ObservedDevelopmentBindingError,
                "prefix bytes differ",
            ):
                verify_observed_development_prefix_artifact(
                    foundation_root=root,
                    binding=binding,
                )

    def test_cache_reuse_guard_rejects_a_link_like_prefix_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = root / "foundation"
            foundation.mkdir()
            (foundation / "data_exposure.yaml").write_bytes(
                (REPO_ROOT / "foundation" / "data_exposure.yaml").read_bytes()
            )
            content = b"registered observed development prefix\n"
            content_hash = sha256(content).hexdigest()
            data = (REPO_ROOT / "foundation" / "data.yaml").read_bytes()
            data = data.replace(
                CURRENT_PREFIX_SHA256.encode("ascii"),
                content_hash.encode("ascii"),
            ).replace(
                b"byte_count: 37029769",
                f"byte_count: {len(content)}".encode("ascii"),
            )
            (foundation / "data.yaml").write_bytes(data)
            real_prefix = root / "data" / "real-prefix.csv"
            real_prefix.parent.mkdir(parents=True)
            real_prefix.write_bytes(content)
            linked_prefix = (
                root
                / "data"
                / "processed"
                / "datasets"
                / "us100_m5_observed_development.csv"
            )
            linked_prefix.parent.mkdir(parents=True)
            try:
                linked_prefix.symlink_to(real_prefix)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"link fixture unavailable: {exc}")
            binding = observed_development_job_binding(
                foundation_root=root,
                input_hashes=(OBSERVED_MATERIAL_ID,),
            )
            self.assertIsNotNone(binding)
            assert binding is not None
            with self.assertRaisesRegex(
                ObservedDevelopmentBindingError, "link-like path"
            ):
                verify_observed_development_prefix_artifact(
                    foundation_root=root,
                    binding=binding,
                )

    def test_scientific_lineage_cannot_omit_registered_material_input(self) -> None:
        with self.assertRaisesRegex(
            ObservedDevelopmentBindingError, "omits its lineage material input"
        ):
            scientific_observed_development_job_binding(
                foundation_root=REPO_ROOT,
                input_hashes=("0" * 64,),
                lineage_material_identity=OBSERVED_MATERIAL_ID,
            )
        binding = scientific_observed_development_job_binding(
            foundation_root=REPO_ROOT,
            input_hashes=(OBSERVED_MATERIAL_ID,),
            lineage_material_identity=OBSERVED_MATERIAL_ID,
        )
        self.assertIsNotNone(binding)
        self.assertIsNone(
            scientific_observed_development_job_binding(
                foundation_root=REPO_ROOT,
                input_hashes=("f" * 64,),
                lineage_material_identity="f" * 64,
            )
        )
        with self.assertRaisesRegex(
            ObservedDevelopmentBindingError, "omits its lineage material input"
        ):
            scientific_observed_development_job_binding(
                foundation_root=REPO_ROOT,
                input_hashes=("0" * 64,),
                lineage_material_identity="f" * 64,
            )

    def test_same_material_prefix_change_changes_only_bound_job_key(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = root / "foundation"
            foundation.mkdir()
            for name in ("data.yaml", "data_exposure.yaml"):
                (foundation / name).write_bytes(
                    (REPO_ROOT / "foundation" / name).read_bytes()
                )

            current = observed_development_job_binding(
                foundation_root=root,
                input_hashes=(OBSERVED_MATERIAL_ID,),
            )
            self.assertIsNotNone(current)
            assert current is not None
            current_payload = current.to_payload()
            unrelated_before = observed_development_job_binding(
                foundation_root=root,
                input_hashes=("0" * 64,),
            )
            self.assertIsNone(unrelated_before)

            data_path = foundation / "data.yaml"
            replacement = data_path.read_bytes().replace(
                CURRENT_PREFIX_SHA256.encode("ascii"),
                b"b" * 64,
            )
            self.assertNotEqual(replacement, data_path.read_bytes())
            data_path.write_bytes(replacement)
            changed = observed_development_job_binding(
                foundation_root=root,
                input_hashes=(OBSERVED_MATERIAL_ID,),
            )
            self.assertIsNotNone(changed)
            assert changed is not None
            changed_payload = changed.to_payload()
            self.assertEqual(
                {
                    key: value
                    for key, value in current_payload.items()
                    if key != "observed_development_sha256"
                },
                {
                    key: value
                    for key, value in changed_payload.items()
                    if key != "observed_development_sha256"
                },
            )
            self.assertEqual(
                changed_payload["observed_development_sha256"], "b" * 64
            )
            self.assertIsNone(
                observed_development_job_binding(
                    foundation_root=root,
                    input_hashes=("0" * 64,),
                )
            )
            normalized_spec = {
                "input_hashes": [OBSERVED_MATERIAL_ID],
                "tag": "same-material-prefix-change",
            }
            self.assertNotEqual(
                _job_identity(
                    mission_id="MIS-PREFIX-BINDING",
                    spec=normalized_spec,
                    binding=current_payload,
                ),
                _job_identity(
                    mission_id="MIS-PREFIX-BINDING",
                    spec=normalized_spec,
                    binding=changed_payload,
                ),
            )


class ObservedDevelopmentWriterBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mission_id = "MIS-PREFIX-BINDING"
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"b" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id=self.mission_id,
            goal=mission_goal("observed development cache binding"),
            operation_id="prefix-binding-open-mission",
        )
        self.writer.open_initiative(
            initiative_id="INI-PREFIX-BINDING",
            objective=initiative_objective(
                "establish the exact Mission-stable cache boundary"
            ),
            operation_id="prefix-binding-open-initiative",
        )
        self.writer.close_initiative(
            outcome="completed",
            operation_id="prefix-binding-close-initiative",
        )

    def _spec(self, *, tag: str, observed: bool) -> dict[str, object]:
        spec = job_spec(
            self.writer,
            {"kind": "Mission", "id": self.mission_id},
        )
        spec["input_hashes"] = [
            *spec["input_hashes"],
            digest("prefix-binding-input", {"tag": tag}),
            *([OBSERVED_MATERIAL_ID] if observed else []),
        ]
        output_name = f"local/cache/prefix-binding/{tag}.bin"
        spec["expected_outputs"] = [output_name]
        spec["output_classes"] = {output_name: "reproducible_cache"}
        return spec

    def _complete_cache(
        self, *, spec: dict[str, object], operation_prefix: str
    ) -> tuple[str, str]:
        declared = self.writer.declare_job(
            spec=spec,
            operation_id=f"{operation_prefix}-declare",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{operation_prefix}-permit",
        )
        self.writer.start_job(
            permit=permit,
            operation_id=f"{operation_prefix}-start",
        )
        output_name = spec["expected_outputs"][0]
        assert isinstance(output_name, str)
        content = f"{operation_prefix} reproducible output".encode("ascii")
        target = self.root / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={output_name: sha256(content).hexdigest()},
            operation_id=f"{operation_prefix}-complete",
        )
        return declared.result["job_id"], completed.result["completion_record_id"]

    def test_writer_binds_observed_prefix_without_rekeying_unrelated_jobs(self) -> None:
        unrelated_spec = self._spec(tag="unrelated", observed=False)
        normalized_unrelated = self.writer._normalize_job_spec(unrelated_spec)
        unrelated_job_id, unrelated_completion_id = self._complete_cache(
            spec=unrelated_spec,
            operation_prefix="unrelated-prefix-cache",
        )
        self.assertEqual(
            unrelated_job_id,
            "job:"
            + _job_identity(
                mission_id=self.mission_id,
                spec=normalized_unrelated,
                binding=None,
            ),
        )

        observed = observed_development_job_binding(
            foundation_root=REPO_ROOT,
            input_hashes=(OBSERVED_MATERIAL_ID,),
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        binding = observed.to_payload()
        observed_spec = self._spec(tag="observed", observed=True)
        normalized_observed = self.writer._normalize_job_spec(observed_spec)
        observed_job_id, observed_completion_id = self._complete_cache(
            spec=observed_spec,
            operation_prefix="observed-prefix-cache",
        )
        expected_job_hash = _job_identity(
            mission_id=self.mission_id,
            spec=normalized_observed,
            binding=binding,
        )
        self.assertEqual(observed_job_id, "job:" + expected_job_hash)

        unrelated_work, unrelated_success = _work_and_success_fingerprints(
            mission_id=self.mission_id,
            spec=normalized_unrelated,
            binding=None,
        )
        observed_work, observed_success = _work_and_success_fingerprints(
            mission_id=self.mission_id,
            spec=normalized_observed,
            binding=binding,
        )
        with LocalIndex(self.writer.index_path) as index:
            unrelated_declaration = index.get("job-declared", unrelated_job_id)
            observed_declaration = index.get("job-declared", observed_job_id)
            self.assertIsNotNone(unrelated_declaration)
            self.assertIsNotNone(observed_declaration)
            assert unrelated_declaration is not None
            assert observed_declaration is not None
            self.assertNotIn(
                "observed_development_binding", unrelated_declaration.payload
            )
            self.assertEqual(
                unrelated_declaration.payload["work_fingerprint"],
                unrelated_work,
            )
            self.assertEqual(
                unrelated_declaration.payload["success_fingerprint"],
                unrelated_success,
            )
            self.assertEqual(
                observed_declaration.payload["observed_development_binding"],
                binding,
            )
            self.assertEqual(
                observed_declaration.payload["work_fingerprint"], observed_work
            )
            self.assertEqual(
                observed_declaration.payload["success_fingerprint"],
                observed_success,
            )
            unrelated_cache = index.get("job-success-cache", unrelated_success)
            observed_cache = index.get("job-success-cache", observed_success)
            self.assertIsNotNone(unrelated_cache)
            self.assertIsNotNone(observed_cache)
            assert unrelated_cache is not None
            assert observed_cache is not None
            self.assertNotIn(
                "observed_development_binding", unrelated_cache.payload
            )
            self.assertEqual(
                unrelated_cache.payload["completion_record_id"],
                unrelated_completion_id,
            )
            self.assertEqual(
                observed_cache.payload["observed_development_binding"], binding
            )
            self.assertEqual(
                observed_cache.payload["completion_record_id"],
                observed_completion_id,
            )

        unrelated_reuse = self.writer.declare_job(
            spec=unrelated_spec,
            operation_id="unrelated-prefix-cache-reuse",
        )
        observed_reuse = self.writer.declare_job(
            spec=observed_spec,
            operation_id="observed-prefix-cache-reuse",
        )
        self.assertTrue(unrelated_reuse.reused)
        self.assertTrue(observed_reuse.reused)
        self.assertEqual(
            unrelated_reuse.result["completion_record_id"],
            unrelated_completion_id,
        )
        self.assertEqual(
            observed_reuse.result["completion_record_id"],
            observed_completion_id,
        )
        with patch(
            "axiom_rift.operations.writer."
            "verify_observed_development_prefix_artifact",
            side_effect=ObservedDevelopmentBindingError(
                "injected physical prefix mismatch"
            ),
        ), self.assertRaisesRegex(
            RecoveryRequired, "cache source bytes"
        ):
            self.writer.declare_job(
                spec=observed_spec,
                operation_id="reject-observed-prefix-cache-after-byte-drift",
            )


class AuthorityPrepareRaceTests(unittest.TestCase):
    def test_prepare_time_authority_drift_cannot_append_an_event(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            authority_root = root / "authority"
            for relative in _AUTHORITY_AND_FOUNDATION_PATHS:
                target = authority_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((REPO_ROOT / relative).read_bytes())
            writer = StateWriter(
                root / "writer",
                permit_authority=PermitAuthority(b"r" * 32),
                clock=lambda: FIXED_NOW,
                engineering_fixture=True,
                foundation_root=authority_root,
            )
            writer.initialize_ready()
            control_before = writer.read_control()
            journal_before = writer.journal.tail()[0]
            with LocalIndex(writer.index_path) as index:
                index_count_before = index.record_count()
            data_path = authority_root / "foundation" / "data.yaml"

            def prepare(current, _index):
                assert current is not None
                data_path.write_bytes(
                    data_path.read_bytes()
                    + b"\n# prepare-time authority drift fixture\n"
                )
                return writer._body(current), [], {"prepared": True}

            with self.assertRaisesRegex(
                RecoveryRequired, "changed during transition preparation"
            ):
                writer._commit(
                    event_kind="authority_prepare_race_fixture",
                    operation_id="reject-authority-prepare-race",
                    subject="Authority:fixture",
                    payload={"schema": "authority_prepare_race_fixture.v1"},
                    prepare=prepare,
                )
            self.assertEqual(writer.read_control(), control_before)
            self.assertEqual(writer.journal.tail()[0], journal_before)
            with LocalIndex(writer.index_path) as index:
                self.assertEqual(index.record_count(), index_count_before)
                self.assertIsNone(
                    index.get("operation", "reject-authority-prepare-race")
                )


if __name__ == "__main__":
    unittest.main()
