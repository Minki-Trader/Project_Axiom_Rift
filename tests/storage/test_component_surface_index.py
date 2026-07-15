from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from axiom_rift.core.component_surface import (
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
    COMPONENT_SURFACE_DOMAIN_AWARE,
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    component_manifest_surfaces,
)
from axiom_rift.core.identity import ComponentSpec
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    LocalIndexError,
)


def _component_record(
    token: int,
    *,
    protocol: str = "model",
    implementation: str | None = None,
    specification: object | None = None,
) -> tuple[IndexRecord, ComponentSpec]:
    component = ComponentSpec(
        display_name=f"component {token}",
        protocol=protocol + ".v1",
        implementation=implementation or f"implementation-{token:04d}",
        spec={"token": token} if specification is None else specification,
    )
    manifest = component.to_identity_payload()
    surfaces = component_manifest_surfaces(manifest)
    return (
        IndexRecord(
            kind="component-manifest",
            record_id=component.identity,
            subject=f"Component:{component.identity}",
            status="registered",
            fingerprint=surfaces.domain_aware,
            payload={
                "component_id": component.identity,
                "manifest": manifest,
                "protocol_domain": protocol,
                "schema": "component_manifest_projection.v1",
                "semantic_surface_identity": surfaces.domain_aware,
            },
        ),
        component,
    )


def _drop_v3_component_projection(path: Path, *, version: int) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        trigger_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE 'component_surface_%'"
        ).fetchall()
        for (name,) in trigger_rows:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE component_surface_bindings")
        connection.execute("DROP TABLE component_surface_stats")
        controlled_triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE '%controlled_chassis_study%'"
        ).fetchall()
        for (name,) in controlled_triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE controlled_chassis_study_stats")
        if version == 1:
            index_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name LIKE 'ix_records_kind_payload_%'"
            ).fetchall()
            for (name,) in index_rows:
                connection.execute(f'DROP INDEX "{name}"')
        connection.execute(f"PRAGMA user_version = {version}")


class ComponentSurfaceIndexTests(unittest.TestCase):
    def test_exact_and_union_surface_queries_are_keyed_and_post_verified(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            shared = "shared-decision-implementation"
            spec = {"shared": True}
            model_record, model = _component_record(
                1,
                protocol="model",
                implementation=shared,
                specification=spec,
            )
            calibration_record, calibration = _component_record(
                2,
                protocol="calibration",
                implementation=shared,
                specification=spec,
            )
            feature_record, feature = _component_record(3, protocol="feature")
            model_surfaces = component_manifest_surfaces(model)
            calibration_surfaces = component_manifest_surfaces(calibration)
            feature_surfaces = component_manifest_surfaces(feature)
            self.assertEqual(
                model_surfaces.architecture_role_surface,
                calibration_surfaces.architecture_role_surface,
            )
            with LocalIndex(path) as index:
                index.put_many(
                    (model_record, calibration_record, feature_record)
                )
                architecture = index.component_manifests_by_surface(
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    model_surfaces.architecture_role_surface,
                )
                self.assertEqual(
                    tuple(record.record_id for record in architecture),
                    tuple(sorted((model.identity, calibration.identity))),
                )
                union = index.component_manifests_by_surfaces(
                    COMPONENT_SURFACE_DOMAIN_AWARE,
                    (
                        feature_surfaces.domain_aware,
                        model_surfaces.domain_aware,
                        model_surfaces.domain_aware,
                    ),
                )
                self.assertEqual(
                    {record.record_id for record in union},
                    {feature.identity, model.identity},
                )
                protocol_variants = index.component_manifests_by_surface(
                    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
                    model_surfaces.protocol_neutral,
                )
                self.assertEqual(len(protocol_variants), 2)
                self.assertEqual(
                    index.component_surface_bindings_for_component(
                        model.identity
                    ),
                    model_surfaces.bindings(),
                )
                forward_shape = index.component_manifests_by_surfaces_access_shape(
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    (model_surfaces.architecture_role_surface,),
                )
                reverse_shape = (
                    index.component_surface_bindings_for_component_access_shape(
                        model.identity
                    )
                )
                self.assertFalse(
                    any(detail.startswith("SCAN") for detail in forward_shape)
                )
                self.assertTrue(
                    any("USING PRIMARY KEY" in detail for detail in forward_shape)
                )
                self.assertTrue(
                    any(
                        "ix_component_surface_bindings_component" in detail
                        for detail in reverse_shape
                    )
                )
                absent = (
                    "architecture-component-surface:" + "f" * 64
                )
                self.assertEqual(
                    index.component_manifests_by_surface(
                        COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                        absent,
                    ),
                    (),
                )
                index.check_integrity()

    def test_current_surface_lookup_decodes_one_not_487_manifests(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            records_and_components = tuple(
                _component_record(token, protocol="model")
                for token in range(487)
            )
            with LocalIndex(path) as index:
                index.rebuild(record for record, _component in records_and_components)
            target = records_and_components[321][1]
            target_surface = component_manifest_surfaces(
                target
            ).architecture_role_surface
            decoded: list[str] = []
            with LocalIndex.open_read_only(
                path,
                authority_validator=lambda record: decoded.append(record.record_id),
            ) as index:
                result = index.component_manifests_by_surface(
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    target_surface,
                )
                self.assertEqual(
                    tuple(record.record_id for record in result),
                    (target.identity,),
                )
                self.assertEqual(decoded, [target.identity])
                self.assertEqual(index.component_surface_guard()[0], 487)

    def test_component_put_many_refreshes_the_set_guard_once(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            records = tuple(_component_record(token)[0] for token in range(64))
            with LocalIndex(path) as index, patch.object(
                index,
                "_refresh_component_surface_guard",
                wraps=index._refresh_component_surface_guard,
            ) as refresh:
                self.assertEqual(index.put_many(records), (True,) * len(records))
                self.assertEqual(refresh.call_count, 1)
                self.assertEqual(index.component_surface_guard()[:2], (64, 192))

    def test_binding_and_source_mutations_fail_before_negative_omission(self) -> None:
        mutations = {
            "binding-delete": (
                "DELETE FROM component_surface_bindings "
                "WHERE surface_kind = ? AND surface_identity = ?",
                lambda surfaces: (
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    surfaces.architecture_role_surface,
                ),
            ),
            "binding-update": (
                "UPDATE component_surface_bindings SET surface_identity = ? "
                "WHERE surface_kind = ? AND surface_identity = ?",
                lambda surfaces: (
                    "architecture-component-surface:" + "e" * 64,
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    surfaces.architecture_role_surface,
                ),
            ),
            "record-update": (
                "UPDATE records SET status = 'tampered' "
                "WHERE kind = 'component-manifest' AND record_id = ?",
                lambda surfaces: (surfaces.component_id,),
            ),
            "record-delete": (
                "DELETE FROM records "
                "WHERE kind = 'component-manifest' AND record_id = ?",
                lambda surfaces: (surfaces.component_id,),
            ),
        }
        for name, (statement, parameters) in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                path = Path(temporary) / "index.sqlite"
                record, component = _component_record(1)
                surfaces = component_manifest_surfaces(component)
                with LocalIndex(path) as index:
                    index.put(record)
                    index._connection.execute(  # noqa: SLF001
                        statement,
                        parameters(surfaces),
                    )
                    with self.assertRaisesRegex(
                        IndexIntegrityError,
                        "invalid",
                    ):
                        index.component_manifests_by_surface(
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            surfaces.architecture_role_surface,
                        )

    def test_added_binding_and_guard_mutation_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            record, component = _component_record(1)
            surfaces = component_manifest_surfaces(component)
            with LocalIndex(path) as index:
                index.put(record)
                index._connection.execute(  # noqa: SLF001
                    "INSERT INTO component_surface_bindings("
                    "surface_kind, surface_identity, component_id"
                    ") VALUES (?, ?, ?)",
                    (
                        COMPONENT_SURFACE_DOMAIN_AWARE,
                        "component-surface:" + "d" * 64,
                        "component:" + "d" * 64,
                    ),
                )
                with self.assertRaises(IndexIntegrityError):
                    index.component_manifests_by_surface(
                        COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                        surfaces.architecture_role_surface,
                    )

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            record, component = _component_record(1)
            surfaces = component_manifest_surfaces(component)
            with LocalIndex(path) as index:
                index.put(record)
                index._connection.execute(  # noqa: SLF001
                    "UPDATE component_surface_stats SET binding_valid = 0 "
                    "WHERE singleton = 1"
                )
                with self.assertRaises(IndexIntegrityError):
                    index.component_manifests_by_surface(
                        COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                        surfaces.architecture_role_surface,
                    )

    def test_component_put_many_failure_rolls_back_records_bindings_and_guard(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            base_record, _base = _component_record(1)
            valid_record, valid = _component_record(2)
            malformed_record, malformed = _component_record(3)
            malformed_record = replace(
                malformed_record,
                payload={
                    **malformed_record.payload,
                    "semantic_surface_identity": "component-surface:"
                    + "0" * 64,
                },
            )
            with LocalIndex(path) as index:
                index.put(base_record)
                guard_before = index.component_surface_guard()
                count_before = index.record_count()
                with self.assertRaises(IndexIntegrityError):
                    index.put_many((valid_record, malformed_record))
                self.assertEqual(index.component_surface_guard(), guard_before)
                self.assertEqual(index.record_count(), count_before)
                self.assertIsNone(
                    index.get("component-manifest", valid.identity)
                )
                self.assertIsNone(
                    index.get("component-manifest", malformed.identity)
                )
                index.check_integrity()

    def test_rebuild_replaces_surface_projection_atomically(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            old_record, old = _component_record(1)
            new_record, new = _component_record(2)
            old_surface = component_manifest_surfaces(
                old
            ).architecture_role_surface
            new_surface = component_manifest_surfaces(
                new
            ).architecture_role_surface
            with LocalIndex(path) as index:
                index.put(old_record)
                self.assertEqual(index.rebuild((new_record,)), 1)
                self.assertEqual(
                    index.component_manifests_by_surface(
                        COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                        old_surface,
                    ),
                    (),
                )
                self.assertEqual(
                    tuple(
                        record.record_id
                        for record in index.component_manifests_by_surface(
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            new_surface,
                        )
                    ),
                    (new.identity,),
                )
                self.assertEqual(index.component_surface_guard()[:2], (1, 3))
                index.check_integrity()

    def test_v1_and_v2_migration_preserve_authority_and_build_all_bindings(
        self,
    ) -> None:
        for version in (1, 2):
            with self.subTest(version=version), TemporaryDirectory() as temporary:
                path = Path(temporary) / "index.sqlite"
                records = tuple(_component_record(token)[0] for token in range(4))
                with LocalIndex(path) as index:
                    index.rebuild(records)
                    authority_guard = index.projection_guard()
                    record_count = index.record_count()
                _drop_v3_component_projection(path, version=version)

                result = LocalIndex.materialize_payload_lookup_indexes(path)

                self.assertEqual(result["from_schema_version"], version)
                self.assertEqual(result["to_schema_version"], 3)
                self.assertEqual(result["component_count"], 4)
                self.assertEqual(result["component_binding_count"], 12)
                with LocalIndex.open_read_only(path) as index:
                    self.assertEqual(index.projection_guard(), authority_guard)
                    self.assertEqual(index.record_count(), record_count)
                    self.assertEqual(index.component_surface_guard()[:2], (4, 12))

    def test_missing_invalidation_trigger_blocks_read_only_open(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            with LocalIndex(path):
                pass
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "DROP TRIGGER component_surface_bindings_delete_invalid"
                )
            with self.assertRaisesRegex(
                LocalIndexError,
                "invalidation triggers",
            ):
                LocalIndex.open_read_only(path)

    def test_writable_recovery_open_accepts_corrupt_guard_then_rebuilds(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            original = IndexRecord(
                kind="negative-memory",
                record_id="recovery-fixture",
                subject="Executable:recovery-fixture",
                status="durable",
                fingerprint="a" * 64,
                payload={"schema": "recovery_fixture.v1"},
            )
            with LocalIndex(path) as index:
                index.put(original)
                index._connection.execute(  # noqa: SLF001 - adversarial fixture
                    "UPDATE records SET fingerprint = ? "
                    "WHERE kind = ? AND record_id = ?",
                    ("b" * 64, original.kind, original.record_id),
                )

            with self.assertRaises(IndexIntegrityError):
                LocalIndex.open_read_only(path)
            with LocalIndex(path) as recovery:
                with self.assertRaises(IndexIntegrityError):
                    recovery.check_integrity()
                recovery.rebuild((original,))
                recovery.check_integrity()
                self.assertEqual(
                    recovery.get(original.kind, original.record_id),
                    original,
                )

    def test_owned_snapshot_excludes_concurrent_component_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite"
            base_record, _base = _component_record(1)
            added_record, added = _component_record(2)
            added_surface = component_manifest_surfaces(
                added
            ).architecture_role_surface
            with LocalIndex(path) as index:
                index.put(base_record)

            writer_ready = Event()
            start_write = Event()
            commit_attempted = Event()
            writer_finished = Event()
            errors: list[BaseException] = []

            def write_component() -> None:
                try:
                    with LocalIndex(path) as writer:
                        writer._connection.set_trace_callback(  # noqa: SLF001
                            lambda statement: (
                                commit_attempted.set()
                                if statement.strip().upper() == "COMMIT"
                                else None
                            )
                        )
                        writer_ready.set()
                        if not start_write.wait(5):
                            raise AssertionError("component writer was not released")
                        writer.put(added_record)
                except BaseException as exc:  # pragma: no cover - asserted below
                    errors.append(exc)
                finally:
                    writer_finished.set()

            thread = Thread(target=write_component, daemon=True)
            thread.start()
            self.assertTrue(writer_ready.wait(5))
            try:
                with LocalIndex.open_read_only(path) as index:
                    self.assertEqual(
                        index.component_manifests_by_surface(
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            added_surface,
                        ),
                        (),
                    )
                    start_write.set()
                    self.assertTrue(commit_attempted.wait(5))
                    self.assertFalse(writer_finished.wait(0.1))
                    self.assertEqual(
                        index.component_manifests_by_surface(
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            added_surface,
                        ),
                        (),
                    )
            finally:
                start_write.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            with LocalIndex.open_read_only(path) as index:
                self.assertEqual(
                    tuple(
                        record.record_id
                        for record in index.component_manifests_by_surface(
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            added_surface,
                        )
                    ),
                    (added.identity,),
                )


if __name__ == "__main__":
    unittest.main()
