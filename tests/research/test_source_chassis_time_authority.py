from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.research import us500_source_chassis
from axiom_rift.research import usdjpy_source_chassis
from axiom_rift.research import vix_source_chassis
from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
)


_CASES = (
    (
        "US500",
        us500_source_chassis,
        "us500_source_baseline",
        "us500_source_chassis_implementation_sha256",
        "us500_source_implementation_sha256",
        "validator_module",
        "us500_source_validator_implementation_sha256",
    ),
    (
        "USDJPY",
        usdjpy_source_chassis,
        "usdjpy_source_baseline",
        "usdjpy_source_chassis_implementation_sha256",
        "usdjpy_source_implementation_sha256",
        "validator_module",
        "usdjpy_source_validator_implementation_sha256",
    ),
    (
        "VIX",
        vix_source_chassis,
        "vix_source_baseline",
        "vix_source_chassis_implementation_sha256",
        "vix_source_implementation_sha256",
        "audit_module",
        "vix_source_audit_implementation_sha256",
    ),
)


class SourceChassisTimeAuthorityTests(unittest.TestCase):
    def test_chassis_bind_coordinate_without_absolute_or_session_claim(self) -> None:
        for symbol, module, baseline_name, *_ in _CASES:
            with self.subTest(symbol=symbol):
                baseline = getattr(module, baseline_name)()
                self.assertIn(MT5_EPOCH_COORDINATE, baseline.clock_contract)
                self.assertIn("absolute_time_authority_unknown", baseline.clock_contract)
                self.assertIn(
                    "broker_session_timezone_DST_authority_unknown",
                    baseline.clock_contract,
                )
                self.assertIn("no_offset_or_shift_inference", baseline.clock_contract)
                self.assertNotIn("epoch_utc", baseline.clock_contract.lower())
                self.assertEqual(
                    baseline.parameter_values()["source_state"],
                    "context_only",
                )
                source = baseline.to_identity_payload()["component_manifests"][0]
                self.assertEqual(
                    source["spec"]["time_coordinate"],
                    MT5_EPOCH_COORDINATE,
                )
                self.assertEqual(
                    source["spec"]["absolute_time_authority"],
                    MT5_ABSOLUTE_TIME_AUTHORITY,
                )
                self.assertEqual(
                    source["spec"]["broker_session_timezone_dst_authority"],
                    MT5_SESSION_TIME_AUTHORITY,
                )
                self.assertEqual(source["spec"]["offset_policy"], MT5_OFFSET_POLICY)
                self.assertFalse(source["spec"]["performance_allowed"])

    def test_identity_tracks_chassis_source_and_validator_or_audit_bytes(self) -> None:
        for (
            symbol,
            module,
            baseline_name,
            chassis_hash_name,
            source_hash_name,
            dependency_module_name,
            dependency_hash_name,
        ) in _CASES:
            with self.subTest(symbol=symbol):
                source_module = module.source_module
                dependency_module = getattr(module, dependency_module_name)
                self.assertEqual(
                    getattr(module, chassis_hash_name)(),
                    sha256(Path(module.__file__).resolve().read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    getattr(module, source_hash_name)(),
                    sha256(
                        Path(source_module.__file__).resolve().read_bytes()
                    ).hexdigest(),
                )
                self.assertEqual(
                    getattr(module, dependency_hash_name)(),
                    sha256(
                        Path(dependency_module.__file__).resolve().read_bytes()
                    ).hexdigest(),
                )
                with TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    chassis_path = root / "chassis.py"
                    source_path = root / "source.py"
                    dependency_path = root / "dependency.py"
                    chassis_path.write_bytes(b"chassis-a")
                    source_path.write_bytes(b"source-a")
                    dependency_path.write_bytes(b"dependency-a")
                    with (
                        patch.object(module, "_THIS_FILE", chassis_path),
                        patch.object(source_module, "__file__", str(source_path)),
                        patch.object(
                            dependency_module,
                            "__file__",
                            str(dependency_path),
                        ),
                    ):
                        baseline = getattr(module, baseline_name)
                        identities = [baseline().identity]
                        chassis_path.write_bytes(b"chassis-b")
                        identities.append(baseline().identity)
                        source_path.write_bytes(b"source-b")
                        identities.append(baseline().identity)
                        dependency_path.write_bytes(b"dependency-b")
                        identities.append(baseline().identity)
                self.assertEqual(len(set(identities)), len(identities))


if __name__ == "__main__":
    unittest.main()
