"""Prove schema-v3 Component surfaces against the legacy formulas.

This maintenance oracle reads one Journal-authenticated stable index snapshot.
It neither materializes schema v3 nor writes any authority or projection state.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.core.component_surface import (  # noqa: E402
    component_manifest_surfaces,
)
from axiom_rift.core.identity import canonical_digest  # noqa: E402
from axiom_rift.operations.running_job import RunningJobAuthority  # noqa: E402


_DOMAIN_ALIASES = {"external_source": "data_source"}
_ROLE_BY_DOMAIN = {
    "calibration": "decision",
    "execution": "execution",
    "label": "label",
    "lifecycle": "lifecycle",
    "model": "decision",
    "portfolio": "portfolio",
    "risk": "portfolio",
    "selector": "decision",
    "synthesis": "portfolio",
    "trade": "entry",
}
_RESEARCH_DOMAINS = frozenset(
    {
        "calibration",
        "data_source",
        "execution",
        "feature",
        "label",
        "lifecycle",
        "model",
        "objective",
        "portfolio",
        "regime",
        "risk",
        "selector",
        "synthesis",
        "trade",
    }
)
_AUTHENTICATED_INDEX_SCHEMA_VERSION = 3


def _legacy_surfaces(manifest: Mapping[str, object]) -> dict[str, object]:
    """Reproduce the pre-v3 identities without calling the v3 calculator."""

    protocol = manifest.get("protocol")
    if not isinstance(protocol, str):
        raise RuntimeError("legacy Component protocol is malformed")
    raw_domain = protocol.split(".", 1)[0]
    domain = _DOMAIN_ALIASES.get(raw_domain, raw_domain)
    if domain not in _RESEARCH_DOMAINS:
        raise RuntimeError(f"unknown legacy Component domain: {raw_domain!r}")
    role = _ROLE_BY_DOMAIN.get(domain)
    common = {
        "implementation": manifest.get("implementation"),
        "semantic_dependencies": manifest.get("semantic_dependencies"),
        "spec": manifest.get("spec"),
    }
    domain_aware = "component-surface:" + canonical_digest(
        domain="component-semantic-surface",
        payload={
            "domain": domain,
            "schema": "component_semantic_surface.v1",
            **common,
        },
    )
    protocol_neutral = "component-protocol-neutral:" + canonical_digest(
        domain="component-protocol-neutral-surface",
        payload={
            "schema": "component_protocol_neutral_surface.v1",
            **common,
        },
    )
    architecture = (
        None
        if role is None
        else "architecture-component-surface:"
        + canonical_digest(
            domain="architecture-component-semantic-surface",
            payload={
                "role": role,
                "schema": "architecture_component_semantic_surface.v1",
                **common,
            },
        )
    )
    return {
        "architecture_role": role,
        "architecture_role_surface": architecture,
        "component_id": "component:"
        + canonical_digest(domain="component", payload=dict(manifest)),
        "domain": domain,
        "domain_aware": domain_aware,
        "protocol_neutral": protocol_neutral,
        "raw_protocol_domain": raw_domain,
    }


def audit(
    index_path: Path,
    *,
    expected_count: int | None,
    foundation_root: Path | None = None,
) -> dict[str, object]:
    resolved = index_path.resolve(strict=True)
    if resolved.name != "index.sqlite" or resolved.parent.name != "local":
        raise RuntimeError(
            "Component parity requires the repository local/index.sqlite projection"
        )
    repository_root = resolved.parent.parent
    authority = RunningJobAuthority(
        repository_root,
        foundation_root=(
            repository_root
            if foundation_root is None
            else foundation_root.resolve()
        ),
    )
    with authority.open_stable_index() as (_control, index):
        rows = index.records_by_kind("component-manifest")

    if expected_count is not None and len(rows) != expected_count:
        raise RuntimeError(
            f"Component manifest count differs: {len(rows)} != {expected_count}"
        )

    domains: Counter[str] = Counter()
    raw_domains: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    distinct = {
        "architecture_role_surface": set(),
        "component_id": set(),
        "domain_aware": set(),
        "protocol_neutral": set(),
    }
    for record in rows:
        record_id = record.record_id
        subject = record.subject
        status = record.status
        fingerprint = record.fingerprint
        payload = dict(record.payload)
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "component_id",
                "manifest",
                "protocol_domain",
                "schema",
                "semantic_surface_identity",
            }
            or payload.get("schema") != "component_manifest_projection.v1"
            or not isinstance(payload.get("manifest"), dict)
        ):
            raise RuntimeError(f"malformed Component projection: {record_id}")
        manifest = payload["manifest"]
        legacy = _legacy_surfaces(manifest)
        current = component_manifest_surfaces(manifest)
        projected = {
            "architecture_role": current.architecture_role,
            "architecture_role_surface": current.architecture_role_surface,
            "component_id": current.component_id,
            "domain": current.domain,
            "domain_aware": current.domain_aware,
            "protocol_neutral": current.protocol_neutral,
            "raw_protocol_domain": manifest["protocol"].split(".", 1)[0],
        }
        if canonical_bytes(legacy) != canonical_bytes(projected):
            raise RuntimeError(f"legacy/v3 surface mismatch: {record_id}")
        if (
            status != "registered"
            or record_id != legacy["component_id"]
            or subject != f"Component:{record_id}"
            or fingerprint != legacy["domain_aware"]
            or payload["component_id"] != record_id
            or payload["protocol_domain"] != legacy["raw_protocol_domain"]
            or payload["semantic_surface_identity"] != legacy["domain_aware"]
        ):
            raise RuntimeError(f"Component authority envelope mismatch: {record_id}")
        domains[str(legacy["domain"])] += 1
        raw_domains[str(legacy["raw_protocol_domain"])] += 1
        role = legacy["architecture_role"]
        roles["none" if role is None else str(role)] += 1
        for name in distinct:
            value = legacy[name]
            if value is not None:
                distinct[name].add(str(value))

    return {
        "architecture_bound_count": len(rows) - roles["none"],
        "domain_counts": dict(sorted(domains.items())),
        "distinct_surface_counts": {
            name: len(values) for name, values in sorted(distinct.items())
        },
        "index_path": str(resolved),
        "manifest_count": len(rows),
        "parity": "exact",
        "raw_protocol_domain_counts": dict(sorted(raw_domains.items())),
        "role_counts": dict(sorted(roles.items())),
        "schema": "component_surface_v3_parity_audit.v1",
        "source_schema_version": _AUTHENTICATED_INDEX_SCHEMA_VERSION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only legacy-to-v3 Component surface parity oracle"
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=ROOT / "local" / "index.sqlite",
        help="repository local index authenticated against control and Journal",
    )
    parser.add_argument("--expected-count", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = audit(arguments.index, expected_count=arguments.expected_count)
    print(
        json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
