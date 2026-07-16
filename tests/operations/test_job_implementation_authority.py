from __future__ import annotations

from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.job_implementation_authority import (
    HistoricalImplementationSourceAuthority,
    JobImplementationAuthorityError,
    hardcoded_control_ids,
    require_job_implementation_evidence,
)


class JobImplementationAuthorityTest(unittest.TestCase):
    def _implementation(
        self,
        source: bytes,
    ) -> tuple[dict[str, bytes], dict[str, object], str, str]:
        artifacts: dict[str, bytes] = {}

        def seal(value: bytes) -> str:
            identity = sha256(value).hexdigest()
            artifacts[identity] = value
            return identity

        source_hash = seal(source)
        source_path = "axiom_rift/research/historical_family_fixture.py"
        closure_hash = seal(
            canonical_bytes(
                {
                    "callable_identity": "fixture.replay.run.v1",
                    "dependencies": [
                        {"path": source_path, "sha256": source_hash}
                    ],
                    "schema": "job_implementation_source_closure.v1",
                }
            )
        )
        manifest_hash = seal(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        (closure_hash, source_hash)
                    ),
                    "callable_identity": "fixture.replay.run.v1",
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        return (
            artifacts,
            {
                "callable_identity": "fixture.replay.run.v1",
                "implementation_identity": manifest_hash,
            },
            source_hash,
            source_path,
        )

    def test_passive_prose_is_not_a_control_binding(self) -> None:
        source = b'''\
"""Historical note for STU-0001."""
component = ComponentSpec(display_name="STU-0002 display", spec={})
raise RuntimeError(f"STU-0003 failed for {component}")
'''
        self.assertEqual(hardcoded_control_ids(source), ())

    def test_control_bearing_static_identity_remains_rejected(self) -> None:
        source = b'STUDY_ID = "STU-0004"\n'
        self.assertEqual(hardcoded_control_ids(source), ("STU-0004",))
        artifacts, spec, _source_hash, _source_path = self._implementation(
            source
        )
        with self.assertRaisesRegex(
            JobImplementationAuthorityError,
            "outside declared historical replay lineage",
        ):
            require_job_implementation_evidence(
                spec,
                artifact_reader=artifacts.__getitem__,
            )

    def test_exact_writer_bound_reconstruction_source_is_admitted(self) -> None:
        source = (
            b'family = HistoricalFamilySpec(original_study_id="STU-0051")\n'
        )
        artifacts, spec, source_hash, source_path = self._implementation(
            source
        )
        manifest = require_job_implementation_evidence(
            spec,
            artifact_reader=artifacts.__getitem__,
            historical_source_authorities=(
                HistoricalImplementationSourceAuthority(
                    path=source_path,
                    source_sha256=source_hash,
                    original_study_id="STU-0051",
                ),
            ),
        )
        self.assertEqual(
            manifest["callable_identity"],
            "fixture.replay.run.v1",
        )

    def test_reconstruction_authority_cannot_cover_another_path_or_id(self) -> None:
        source = (
            b'family = HistoricalFamilySpec(original_study_id="STU-0051")\n'
        )
        artifacts, spec, source_hash, _source_path = self._implementation(
            source
        )
        for authority in (
            HistoricalImplementationSourceAuthority(
                path="axiom_rift/research/another_fixture.py",
                source_sha256=source_hash,
                original_study_id="STU-0051",
            ),
            HistoricalImplementationSourceAuthority(
                path=(
                    "axiom_rift/research/historical_family_fixture.py"
                ),
                source_sha256=source_hash,
                original_study_id="STU-0052",
            ),
        ):
            with self.subTest(authority=authority):
                with self.assertRaisesRegex(
                    JobImplementationAuthorityError,
                    "outside declared historical replay lineage",
                ):
                    require_job_implementation_evidence(
                        spec,
                        artifact_reader=artifacts.__getitem__,
                        historical_source_authorities=(authority,),
                    )


if __name__ == "__main__":
    unittest.main()
