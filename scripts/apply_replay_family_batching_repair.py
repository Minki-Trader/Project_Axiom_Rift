"""Plan or apply the audited replay-family batching authority repair.

The code checkpoint must precede this mutation.  The script first replays the
exact three-event transition in an isolated canonical shadow, then ``--apply``
commits only:

1. the authority migration;
2. the prospective scientific-protocol rebind; and
3. six Writer-derived sibling satisfactions with no new trials.

It never stages, commits, pushes, or accepts caller-built scientific verdicts.
"""

from __future__ import annotations

import argparse
import ctypes
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterator, Mapping, Sequence
from contextlib import contextmanager


ROOT = Path(__file__).resolve().parents[1]
_SAFE_STARTUP = bool(
    sys.flags.isolated
    and sys.flags.no_site
    and sys.flags.no_user_site
    and sys.flags.ignore_environment
    and sys.flags.safe_path
)
if "--apply" in sys.argv and not _SAFE_STARTUP:
    raise SystemExit(
        "apply requires `python -I -S scripts/"
        "apply_replay_family_batching_repair.py --apply`"
    )
_SAFE_BYTECODE_CACHE: TemporaryDirectory[str] | None = None


def _require_safe_repository_import_surface(
    import_roots: Sequence[Path],
) -> None:
    forbidden: list[str] = []
    for import_root in import_roots:
        for candidate in import_root.resolve(strict=True).rglob("*"):
            suffix = candidate.suffix.casefold()
            if suffix in {".dll", ".pyd", ".so"} or (
                suffix == ".pyc"
                and candidate.parent.name.casefold() != "__pycache__"
            ):
                forbidden.append(candidate.resolve(strict=True).as_posix())
    if forbidden:
        raise SystemExit(
            "safe repository import surface contains executable artifacts: "
            + ", ".join(sorted(forbidden))
        )


if _SAFE_STARTUP:
    roaming_buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(
        None,
        0x001A,
        None,
        0,
        roaming_buffer,
    ):
        raise SystemExit("canonical Windows RoamingAppData is unavailable")
    package_roots = (
        (Path(sys.base_prefix) / "Lib" / "site-packages").resolve(),
        (
            Path(roaming_buffer.value)
            / "Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "site-packages"
        ).resolve(),
    )
    for package_root in package_roots:
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.append(str(package_root))
    _SAFE_BYTECODE_CACHE = TemporaryDirectory(
        prefix="axiom-family-batching-bytecode-"
    )
    sys.pycache_prefix = str(
        Path(_SAFE_BYTECODE_CACHE.name).resolve(strict=True)
    )
    sys.dont_write_bytecode = True
    _require_safe_repository_import_surface((ROOT / "src", ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src"))
else:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.historical_family_authority_admission import (
    require_recorded_historical_family_authority,
)
from axiom_rift.operations.replay_projection import obligation_heads
from axiom_rift.operations.research_protocol_projection import (
    require_current_research_protocol_activation,
)
from axiom_rift.operations.study_close_git import (
    capture_study_close_delivery_observation,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_stu0048 import (
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0051 import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


class ReplayFamilyBatchingRepairError(RuntimeError):
    """The exact audited repair boundary is absent or has drifted."""


EXPECTED_ORIGIN_MAIN_COMMIT = (
    "7b57d3679fdd0f7f0038281e43438b5e726073ae"
)
EXPECTED_BASELINE_REVISION = 5488
EXPECTED_BASELINE_EVENT_ID = (
    "19e8059f92ef502451c2768abfe1bce00b9e5c01da0dd008c603f6f81b18e8c3"
)
EXPECTED_BASELINE_RECORD_COUNT = 21675
EXPECTED_BASELINE_AUTHORITY_DIGEST = (
    "cc556acff292f71d35a16fd528f174b4f6bc3758b8aaf033a53e8a2df44b39ab"
)
EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST = (
    "5403723bbf9dfbd8124568b6acab91be7a85c8d1cb2fba060288f79216df5757"
)
EXPECTED_FINAL_REVISION = EXPECTED_BASELINE_REVISION + 3
EXPECTED_FINAL_RECORD_COUNT = EXPECTED_BASELINE_RECORD_COUNT + 20
MISSION_ID = "MIS-0006"
AUDIT_REPORT_PATH = (
    "records/audits/2026-07-18_replay_family_batching_and_sibling_recertification.md"
)
AUTHORITY_REASON = (
    "bind audited family batching, exact member lineage, and sibling evidence "
    "recertification"
)
OPERATION_IDS = (
    "axiom-family-batching:authority",
    "axiom-family-batching:protocol",
    "axiom-family-batching:sibling-recertification",
)
EVENT_KINDS = (
    "authority_migrated",
    "research_protocol_activated",
    "historical_replay_sibling_evidence_recertified",
)
SOURCE_SATISFACTION_IDS = (
    "historical-replay-satisfaction:"
    "3242ab3cd550fc71cff233f764b4e3071a741c8dd88636244835aaf88717e4c8",
    "historical-replay-satisfaction:"
    "c1cdf96e6ac286e6825af9619f8cb893f5293ff5669969d0425735f038109f38",
)
EXPECTED_AUTHORITY_IDS = {
    "historical-replay-obligation:"
    "1361c2fdf817c97666de8fbe8cb13c6e93f8ef9e203222c0df789ecdd8acc751": (
        "historical-family-authority:"
        "db50c30825a3052ea18a03c8e02801697df2983f4a379258b0f6a2415338aaf6"
    ),
    "historical-replay-obligation:"
    "8276c4e62ceb3d45afbf72794843178c3d0dd69d30e0a1e1f4266c63fbc37bd8": (
        "historical-family-authority:"
        "89c9570c49e43e8febfcb994f4308bfb8caa447ea58ba12703e847f89faf3957"
    ),
    "historical-replay-obligation:"
    "a33963139b4259b688cfe2655d717300d6f461d80a6a71ffa634b0e26fd4d861": (
        "historical-family-authority:"
        "8e0b3f9bc53e5b9aa3420feea9ad794ddcec52c01745932029715cc5c303da8f"
    ),
    "historical-replay-obligation:"
    "a65b172e0ab2c0f335bc2b62ff308622f1d2a6e50dde6746dfdbc647f34a82f5": (
        "historical-family-authority:"
        "667a6633cd36cbc950e8f25ac587f64df820785ee54c74d440cf52022a336b13"
    ),
    "historical-replay-obligation:"
    "b888e29d83d91e2dac6ee0ed377027007067f29dc35a94f4710de60fa2be181c": (
        "historical-family-authority:"
        "0f93d75cbb14da2301734dc2485a6728909bacfa5f30329799159721b82e31c0"
    ),
    "historical-replay-obligation:"
    "f2b5b1b87506c1adb29623c08a7a1be52b1d512f0f653347408958de0b554447": (
        "historical-family-authority:"
        "22ca6894af4bedfc4b4bb0ae3fae9399bfcdbdd4579464b84fe49509eb0a5180"
    ),
}
EXPECTED_SATISFACTION_IDS = {
    "historical-replay-obligation:"
    "1361c2fdf817c97666de8fbe8cb13c6e93f8ef9e203222c0df789ecdd8acc751": (
        "historical-replay-satisfaction:"
        "82b4ec64fa377d14ae503b54b2d759927197fd43aa7313c8e04fddad86a01d1e"
    ),
    "historical-replay-obligation:"
    "8276c4e62ceb3d45afbf72794843178c3d0dd69d30e0a1e1f4266c63fbc37bd8": (
        "historical-replay-satisfaction:"
        "4dce1542aff5d10c2ed32d1de8a55eb044e1abc67b64a51698b69da90c7e798f"
    ),
    "historical-replay-obligation:"
    "a33963139b4259b688cfe2655d717300d6f461d80a6a71ffa634b0e26fd4d861": (
        "historical-replay-satisfaction:"
        "423f0c8d8a9dc272ffd8a65cc0b22e7a58971c9d5a6b34834ba6b6db32bdb4ef"
    ),
    "historical-replay-obligation:"
    "a65b172e0ab2c0f335bc2b62ff308622f1d2a6e50dde6746dfdbc647f34a82f5": (
        "historical-replay-satisfaction:"
        "3a6c0ae0fed3450637a7c5ecb4fa2780625afad07f365c51d477463eb49c2afb"
    ),
    "historical-replay-obligation:"
    "b888e29d83d91e2dac6ee0ed377027007067f29dc35a94f4710de60fa2be181c": (
        "historical-replay-satisfaction:"
        "7b063c03a3b999624a1d0e2b806d37cc7dadec89aa086091b90ab6ee53da1a4f"
    ),
    "historical-replay-obligation:"
    "f2b5b1b87506c1adb29623c08a7a1be52b1d512f0f653347408958de0b554447": (
        "historical-replay-satisfaction:"
        "9e88b8ae31a5c81de1f4cc6965464c7fb49a3d66780b73715b83029640ef376c"
    ),
}
SCIENTIFIC_INVENTORY_KINDS = (
    "candidate",
    "historical-scientific-adjudication",
    "job-completed",
    "negative-memory",
    "release",
    "trial",
)


def _git(*arguments: str, text: bool = False) -> bytes | str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=text,
        timeout=120,
    )
    return result.stdout


def _git_blob(reference: str, relative: str) -> bytes:
    result = _git("show", f"{reference}:{relative}")
    assert isinstance(result, bytes)
    return result


def _canonical_json(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayFamilyBatchingRepairError(f"{label} is malformed") from exc
    if not isinstance(value, dict):
        raise ReplayFamilyBatchingRepairError(f"{label} is not an object")
    return value


def _baseline_control() -> dict[str, Any]:
    control = _canonical_json(
        _git_blob("origin/main", "state/control.json"),
        label="baseline control",
    )
    if (
        control.get("revision") != EXPECTED_BASELINE_REVISION
        or control.get("heads", {}).get("journal", {}).get("event_id")
        != EXPECTED_BASELINE_EVENT_ID
        or control.get("heads", {}).get("index", {}).get(
            "required_record_count"
        )
        != EXPECTED_BASELINE_RECORD_COUNT
        or control.get("authority", {}).get("manifest_digest")
        != EXPECTED_BASELINE_AUTHORITY_DIGEST
    ):
        raise ReplayFamilyBatchingRepairError("baseline control drifted")
    return control


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control["authority"]
    return tuple(
        [authority["operating_direction"]]
        + list(authority["contracts"])
        + list(authority["foundation_inputs"])
    )


def _authority_material() -> tuple[dict[str, bytes], str]:
    control = _baseline_control()
    paths = _authority_paths(control)
    replacements = {
        relative: (ROOT / relative).read_bytes()
        for relative in paths
        if (ROOT / relative).read_bytes()
        != _git_blob("origin/main", relative)
    }
    expected_changed = {
        "OPERATING_DIRECTION.md",
        "contracts/evidence.yaml",
        "contracts/operations.yaml",
        "contracts/science.yaml",
    }
    if set(replacements) != expected_changed:
        raise ReplayFamilyBatchingRepairError(
            "authority replacement surface differs from the audited set"
        )
    hashes = {
        relative: sha256(
            replacements.get(relative, _git_blob("origin/main", relative))
        ).hexdigest()
        for relative in paths
    }
    digest = StateWriter._authority_digest_from_hashes(hashes)
    if digest != EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST:
        raise ReplayFamilyBatchingRepairError(
            "prospective authority manifest differs from the audited repair"
        )
    return replacements, digest


def _registry() -> EvidenceValidatorRegistry:
    return EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))


def _inventory(index: Any) -> dict[str, int]:
    return {
        kind: len(index.records_by_kind(kind))
        for kind in SCIENTIFIC_INVENTORY_KINDS
    }


def _family_authorities(index: Any) -> tuple[HistoricalFamilyAuthority, ...]:
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
    }
    authorities: list[HistoricalFamilyAuthority] = []
    for obligation_id in sorted(EXPECTED_AUTHORITY_IDS):
        pair = heads.get(obligation_id)
        if pair is None or pair[1].status != "pending":
            raise ReplayFamilyBatchingRepairError(
                "recertification target is not exactly pending"
            )
        obligation = pair[0]
        if obligation.original_study_id == "STU-0048":
            base = STU0048_HISTORICAL_FAMILY
            module = "historical_family_stu0048.py"
        elif obligation.original_study_id == "STU-0051":
            base = STU0051_HISTORICAL_FAMILY
            module = "historical_family_stu0051.py"
        else:
            raise ReplayFamilyBatchingRepairError(
                "recertification target names an unexpected historical Study"
            )
        manifest = base.manifest()
        manifest["target_historical_executable_id"] = (
            obligation.original_executable_id
        )
        relative = f"src/axiom_rift/research/{module}"
        source_hash = sha256((ROOT / relative).read_bytes()).hexdigest()
        if HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.get(module) != source_hash:
            raise ReplayFamilyBatchingRepairError(
                "historical family source bytes drifted"
            )
        authority = HistoricalFamilyAuthority(
            replay_obligation_id=obligation_id,
            family=historical_family_from_manifest(manifest),
            reconstruction_source_path=relative,
            reconstruction_source_sha256=source_hash,
        )
        if authority.identity != EXPECTED_AUTHORITY_IDS[obligation_id]:
            raise ReplayFamilyBatchingRepairError(
                "derived target-specific family authority drifted"
            )
        authorities.append(authority)
    return tuple(authorities)


def _activation(authority_digest: str) -> ResearchProtocolActivation:
    report = (ROOT / AUDIT_REPORT_PATH).read_bytes()
    return ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=authority_digest,
        audit_artifact_hash=sha256(report).hexdigest(),
    )


def _copy_git_file(root: Path, relative: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_git_blob("origin/main", relative))


@contextmanager
def _predecessor_foundation() -> Iterator[Path]:
    with TemporaryDirectory(prefix="axiom-family-predecessor-") as name:
        foundation = Path(name)
        for relative in _authority_paths(_baseline_control()):
            _copy_git_file(foundation, relative)
        yield foundation


@contextmanager
def _baseline_shadow() -> Iterator[StateWriter]:
    with TemporaryDirectory(prefix="axiom-family-shadow-") as name:
        shadow_root = Path(name).resolve()
        journal_paths_raw = _git(
            "ls-tree",
            "-r",
            "--name-only",
            "origin/main",
            "records/journal",
            text=True,
        )
        assert isinstance(journal_paths_raw, str)
        for relative in (
            "state/control.json",
            *journal_paths_raw.splitlines(),
            *_authority_paths(_baseline_control()),
        ):
            _copy_git_file(shadow_root, relative)
        for relative in (
            "src/axiom_rift/research/historical_family_stu0048.py",
            "src/axiom_rift/research/historical_family_stu0051.py",
        ):
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        writer = StateWriter(
            shadow_root,
            engineering_fixture=True,
            foundation_root=shadow_root,
            validation_registry=_registry(),
        )
        recovered = writer.recover()
        if (
            recovered.get("journal_sequence") != EXPECTED_BASELINE_REVISION
            or recovered.get("index_rebuilt") is not True
        ):
            raise ReplayFamilyBatchingRepairError(
                "isolated baseline reconstruction drifted"
            )
        yield writer


def _apply_actions(
    writer: StateWriter,
    *,
    replacements: Mapping[str, bytes],
    authority_digest: str,
    start_ordinal: int = 1,
    stop_ordinal: int = 3,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    report = (ROOT / AUDIT_REPORT_PATH).read_bytes()
    artifact = writer.evidence.finalize(report)
    activation = _activation(authority_digest)
    if artifact.sha256 != activation.audit_artifact_hash:
        raise ReplayFamilyBatchingRepairError("audit report evidence drifted")
    if start_ordinal <= 1 <= stop_ordinal:
        result = writer.migrate_authority(
            replacements=replacements,
            reason=AUTHORITY_REASON,
            operation_id=OPERATION_IDS[0],
            allow_active_stable_boundary=True,
        )
        results.append({"event_id": result.event_id, "revision": result.revision})
    if start_ordinal <= 2 <= stop_ordinal:
        result = writer.activate_research_protocol(
            activation=activation,
            operation_id=OPERATION_IDS[1],
            allow_active_stable_boundary=True,
        )
        results.append({"event_id": result.event_id, "revision": result.revision})
    if start_ordinal <= 3 <= stop_ordinal:
        with writer.open_stable_index() as (_control, index):
            authorities = _family_authorities(index)
        result = writer.recertify_historical_replay_sibling_evidence(
            source_satisfaction_ids=SOURCE_SATISFACTION_IDS,
            historical_family_authorities=authorities,
            operation_id=OPERATION_IDS[2],
        )
        results.append({"event_id": result.event_id, "revision": result.revision})
    return results


def _assert_final(
    writer: StateWriter,
    *,
    authority_digest: str,
    baseline_inventory: Mapping[str, int],
) -> dict[str, Any]:
    with writer.open_stable_index() as (control, index):
        heads = {
            obligation.identity: head
            for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
        }
        observed_satisfactions = {
            obligation_id: heads[obligation_id].record_id
            for obligation_id in EXPECTED_SATISFACTION_IDS
        }
        pending = sorted(
            obligation_id
            for obligation_id, head in heads.items()
            if head.status == "pending"
        )
        operations = [index.get("operation", item) for item in OPERATION_IDS]
        if any(operation is None for operation in operations):
            raise ReplayFamilyBatchingRepairError(
                "final Writer operation suffix is incomplete"
            )
        sequences = [operation.authority_sequence for operation in operations]
        for obligation_id, authority_id in EXPECTED_AUTHORITY_IDS.items():
            record = index.get("historical-family-authority", authority_id)
            if record is None:
                raise ReplayFamilyBatchingRepairError(
                    "final historical family authority is absent"
                )
            authority = require_recorded_historical_family_authority(index, record)
            if authority.replay_obligation_id != obligation_id:
                raise ReplayFamilyBatchingRepairError(
                    "final historical family authority target drifted"
                )
        protocol = require_current_research_protocol_activation(
            index,
            authority_manifest_digest=authority_digest,
        )
        if (
            control.get("revision") != EXPECTED_FINAL_REVISION
            or index.record_count() != EXPECTED_FINAL_RECORD_COUNT
            or control.get("authority", {}).get("manifest_digest")
            != authority_digest
            or observed_satisfactions != EXPECTED_SATISFACTION_IDS
            or len(pending) != 17
            or _inventory(index) != dict(baseline_inventory)
            or control.get("scientific", {}).get("claim") != "none"
            or control.get("scientific", {}).get("holdout_reveals") != 0
            or sequences
            != list(
                range(EXPECTED_BASELINE_REVISION + 1, EXPECTED_FINAL_REVISION + 1)
            )
            or [operation.payload.get("event_kind") for operation in operations]
            != list(EVENT_KINDS)
        ):
            raise ReplayFamilyBatchingRepairError(
                "final authority, science, or scheduler projection drifted"
            )
        return {
            "authority_manifest_digest": authority_digest,
            "candidate_count": baseline_inventory["candidate"],
            "pending_replay_obligation_count": len(pending),
            "protocol_activation_id": protocol.record_id,
            "record_count": index.record_count(),
            "revision": control["revision"],
            "satisfied_replay_obligation_ids": sorted(
                EXPECTED_SATISFACTION_IDS
            ),
            "trial_count": baseline_inventory["trial"],
        }


def read_only_plan() -> dict[str, Any]:
    replacements, authority_digest = _authority_material()
    with _baseline_shadow() as writer:
        with writer.open_stable_index() as (_control, index):
            baseline_inventory = _inventory(index)
        events = _apply_actions(
            writer,
            replacements=replacements,
            authority_digest=authority_digest,
        )
        final = _assert_final(
            writer,
            authority_digest=authority_digest,
            baseline_inventory=baseline_inventory,
        )
    return {
        "apply_mutation_performed": False,
        "authority_replacement_paths": sorted(replacements),
        "baseline_scientific_inventory": baseline_inventory,
        "event_count": len(events),
        "event_kinds": list(EVENT_KINDS),
        "final_projection": final,
        "schema": "replay_family_batching_repair_plan.v1",
    }


def _require_code_checkpoint() -> tuple[str, str]:
    branch = str(_git("branch", "--show-current", text=True)).strip()
    head = str(_git("rev-parse", "HEAD", text=True)).strip()
    origin = str(_git("rev-parse", "origin/main", text=True)).strip()
    changed_raw = str(_git("diff", "--name-only", "HEAD", text=True))
    changed = set(changed_raw.splitlines())
    allowed_state = {"state/control.json"}
    allowed_state.update(
        path
        for path in changed
        if path.startswith("records/journal/")
    )
    if (
        branch != "main"
        or origin != EXPECTED_ORIGIN_MAIN_COMMIT
        or head == origin
        or _git("merge-base", "--is-ancestor", "origin/main", "HEAD") != b""
        or changed - allowed_state
        or _git("diff", "--cached", "--quiet") != b""
        or _git_blob("HEAD", "state/control.json")
        != _git_blob("origin/main", "state/control.json")
        or _git_blob("HEAD", Path(__file__).resolve().relative_to(ROOT).as_posix())
        != Path(__file__).read_bytes()
    ):
        raise ReplayFamilyBatchingRepairError(
            "apply requires one clean unpublished local-main code checkpoint"
        )
    return head, origin


def apply() -> dict[str, Any]:
    if not _SAFE_STARTUP:
        raise ReplayFamilyBatchingRepairError("apply startup is not isolated")
    checkpoint, origin = _require_code_checkpoint()
    preview = read_only_plan()
    replacements, authority_digest = _authority_material()
    delivery = capture_study_close_delivery_observation(
        ROOT,
        expected_main_head=checkpoint,
        expected_origin_main=origin,
    )
    current = _canonical_json(
        (ROOT / "state/control.json").read_bytes(),
        label="current control",
    )
    revision = current.get("revision")
    if type(revision) is not int or not (
        EXPECTED_BASELINE_REVISION <= revision <= EXPECTED_FINAL_REVISION
    ):
        raise ReplayFamilyBatchingRepairError(
            "current revision is outside the exact repair prefix"
        )
    start_ordinal = revision - EXPECTED_BASELINE_REVISION + 1
    baseline_inventory = preview["baseline_scientific_inventory"]
    if not isinstance(baseline_inventory, dict):
        raise ReplayFamilyBatchingRepairError(
            "shadow baseline scientific inventory is malformed"
        )
    results: list[dict[str, Any]] = []
    if start_ordinal == 1:
        with _predecessor_foundation() as predecessor:
            first_writer = StateWriter(
                ROOT,
                foundation_root=predecessor,
                study_close_delivery_observation=delivery,
                validation_registry=_registry(),
            )
            results.extend(
                _apply_actions(
                    first_writer,
                    replacements=replacements,
                    authority_digest=authority_digest,
                    start_ordinal=1,
                    stop_ordinal=1,
                )
            )
            start_ordinal = 2
    if start_ordinal <= 3:
        writer = StateWriter(
            ROOT,
            study_close_delivery_observation=delivery,
            validation_registry=_registry(),
        )
        results.extend(
            _apply_actions(
                writer,
                replacements=replacements,
                authority_digest=authority_digest,
                start_ordinal=start_ordinal,
            )
        )
    final_writer = StateWriter(
        ROOT,
        study_close_delivery_observation=delivery,
        validation_registry=_registry(),
    )
    final = _assert_final(
        final_writer,
        authority_digest=authority_digest,
        baseline_inventory=baseline_inventory,
    )
    return {
        "already_complete": not results,
        "applied_event_count": len(results),
        "code_checkpoint_commit": checkpoint,
        "final_projection": final,
        "shadow_plan": preview,
        "schema": "replay_family_batching_repair_apply.v1",
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the exact shadow-proven three-event suffix",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    result = apply() if arguments.apply else read_only_plan()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
