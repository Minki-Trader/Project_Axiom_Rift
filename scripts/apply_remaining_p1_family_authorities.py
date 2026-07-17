"""Plan or apply the exact remaining-P1 historical-family authorities.

The code checkpoint must precede this zero-credit mutation.  The script first
replays the one-event transition in an isolated canonical shadow.  ``--apply``
then registers sixteen target-specific authorities atomically.  It never
stages, commits, pushes, creates trials, changes replay status, or grants any
scientific credit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterator, Mapping, Sequence


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
        "apply_remaining_p1_family_authorities.py --apply`"
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
        prefix="axiom-remaining-family-bytecode-"
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
from axiom_rift.operations.study_close_git import (
    capture_study_close_delivery_observation,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_stu0046 import (
    STU0046_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0047 import (
    STU0047_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0049 import (
    STU0049_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0050 import (
    STU0050_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.validation_v2 import (
    ScientificAdjudicationValidatorV2,
)


class RemainingP1FamilyAuthorityError(RuntimeError):
    """The exact audited authority-registration boundary has drifted."""


EXPECTED_ORIGIN_MAIN_COMMIT = (
    "6ab05e4d4453ce8aff619edc0477ab556f5b2d57"
)
EXPECTED_BASELINE_REVISION = 5491
EXPECTED_BASELINE_EVENT_ID = (
    "cdb30c5354638fa7bbb45af681ddebdaa5995a914944288804848d8fddec1f94"
)
EXPECTED_BASELINE_RECORD_COUNT = 21695
EXPECTED_AUTHORITY_DIGEST = (
    "5403723bbf9dfbd8124568b6acab91be7a85c8d1cb2fba060288f79216df5757"
)
EXPECTED_FINAL_REVISION = EXPECTED_BASELINE_REVISION + 1
EXPECTED_FINAL_RECORD_COUNT = EXPECTED_BASELINE_RECORD_COUNT + 18
MISSION_ID = "MIS-0006"
OPERATION_ID = "axiom-remaining-p1-family-authorities:register"
EVENT_KIND = "historical_replay_family_authorities_registered"
AUDIT_REPORT_PATH = (
    "records/audits/2026-07-18_remaining_p1_family_reconstruction.md"
)
SOURCE_MODULE_PATHS = (
    "src/axiom_rift/research/historical_family_stu0046.py",
    "src/axiom_rift/research/historical_family_stu0047.py",
    "src/axiom_rift/research/historical_family_stu0049.py",
    "src/axiom_rift/research/historical_family_stu0050.py",
)
CODE_CHECKPOINT_PATHS = (
    AUDIT_REPORT_PATH,
    "scripts/apply_remaining_p1_family_authorities.py",
    "src/axiom_rift/research/historical_fixed_four_family.py",
    "src/axiom_rift/research/historical_study_registry.py",
    *SOURCE_MODULE_PATHS,
)
SCIENTIFIC_INVENTORY_KINDS = (
    "candidate",
    "historical-scientific-adjudication",
    "job-completed",
    "negative-memory",
    "release",
    "trial",
)
EXPECTED_REPLAY_STATUS_COUNTS = {
    "deferred": 1,
    "pending": 17,
    "satisfied": 18,
}
EXPECTED_AUTHORITY_IDS = {
    (
        "historical-replay-obligation:"
        "159a599340c95f130c1b674344557a0312219b76c16b863cae4bf228f0769d94"
    ): (
        "historical-family-authority:"
        "3e516ad3d0eded0868140717708ab719e862a54c90c1155cd9ef0bc1f87c7e95"
    ),
    (
        "historical-replay-obligation:"
        "2580acb5b07384e277bc51747e78c56c765640bbb0e431b4270f2acd3365ac30"
    ): (
        "historical-family-authority:"
        "49cf22ebbb0aacfb8a95b8a844cd81ae9c56a52f608e800684a3ae9d7fb8247d"
    ),
    (
        "historical-replay-obligation:"
        "9bbcca0175b84c00c68ea37b98e18f31d60e808b58793ac75bf1f8b9388fc7b6"
    ): (
        "historical-family-authority:"
        "72ac28a5d7aca3baa48722e938499ec3282db3a59702d1c11a3d1dc455ea5ee9"
    ),
    (
        "historical-replay-obligation:"
        "9e01b7b2d1056e667f00ef2694791acb47d97c71f119a589d47d7c114cf26655"
    ): (
        "historical-family-authority:"
        "0ba4b3572cf9c40d2e93b8bf7b34cf3ade0d53b1f194d5a3440c14605ffbd37e"
    ),
    (
        "historical-replay-obligation:"
        "671cfce27c8d763e8238fdd15c9e4dd00c04450c789dc96d8d18eddd98d5037f"
    ): (
        "historical-family-authority:"
        "10d8f52e164b019d5d5d75c6a66e6f0ec5241ec2e8eab8450142c4395fbfbeb0"
    ),
    (
        "historical-replay-obligation:"
        "be4867b5989b526eebd033d0ccac666df45580d887585bb3afca7e55125d0efe"
    ): (
        "historical-family-authority:"
        "8d1929c8966fa6886a249199358dc138f7dec5e4d7256c7b0e9c11a1892408bb"
    ),
    (
        "historical-replay-obligation:"
        "c9fb9597dc1fc432d1a9185f9e0b0c7b7539824cb8013e1d67091f63b0dadb1f"
    ): (
        "historical-family-authority:"
        "25aba45822fa44dd45ee8663f1113c2ff8c6bd2cd737d81f3802a90007358c56"
    ),
    (
        "historical-replay-obligation:"
        "d6926257f10fbfeaffa1a5c31c7ac89a7e68bd350bb25d59af3f1f111220da8e"
    ): (
        "historical-family-authority:"
        "c58bf23ba6ac95a9fe5c9283d2d4bb2fe4334a661147ecf50ab0a153afb6e5d1"
    ),
    (
        "historical-replay-obligation:"
        "2e10d2ca5b2edf2eab10e03f4a6e397062248a1c763e0a154f172af5740eefe9"
    ): (
        "historical-family-authority:"
        "de86e21862f2c8c4854fc5b08022db50aa3f995544ffab3e9d1c4578579c8fea"
    ),
    (
        "historical-replay-obligation:"
        "60f4c9cf299a9b96fb1bf343d0c72276fa0b8754d6a32a421265a2f135c19274"
    ): (
        "historical-family-authority:"
        "14c887e4171a4be0d0ed31c4d428081396bedfd9160a57728229b349711362ab"
    ),
    (
        "historical-replay-obligation:"
        "c2474c4b772dfa0f59407b5dfc6b89f71becfa6ba9587f465b26dba4a5b2bc84"
    ): (
        "historical-family-authority:"
        "d6b96beb77ed02c7a6447579d57c415db5f6de395f088056922edc91dd67771e"
    ),
    (
        "historical-replay-obligation:"
        "e267830fc7cb3fca62d331c40fca836f4c6c624722dd121a0c6e2e0950d36151"
    ): (
        "historical-family-authority:"
        "4878dcc4f84cd8c4808613fcd2207229703a297b927e69d50f858f28d819678e"
    ),
    (
        "historical-replay-obligation:"
        "17e4b86d8538c0dbd3b644ce1e3e33dc64e10d22c9dba419488bcd80187e6be5"
    ): (
        "historical-family-authority:"
        "f71a63008c0428c4d01017d955b287794485033be094829447cf703864888514"
    ),
    (
        "historical-replay-obligation:"
        "9d06939dcc26075efbb0c9e081ed060a8ea84f8e19a65e320139df6c22b0580a"
    ): (
        "historical-family-authority:"
        "44927666c0aab94fcb8fe02a3c8d65787d76b3badc4fcd1462d3b705ec4d2a34"
    ),
    (
        "historical-replay-obligation:"
        "a635a46426c85fe4fb9e4426270bd36fd902ef1f0e1da351d0beb41ba5d7451d"
    ): (
        "historical-family-authority:"
        "d8f18b31702054bd2aed55d9550af168a5c74e8994bc120e9b2b73059f3ce5d5"
    ),
    (
        "historical-replay-obligation:"
        "ac58c5a2bc7a885edc771416afc82a6fda26cf3404b3389bffc71ccc8d941685"
    ): (
        "historical-family-authority:"
        "f7ae433a5b7fdcb52ae68e85717bdf932f5a84355723e7889696fa64267efe87"
    ),
}


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
        raise RemainingP1FamilyAuthorityError(f"{label} is malformed") from exc
    if not isinstance(value, dict):
        raise RemainingP1FamilyAuthorityError(f"{label} is not an object")
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
        != EXPECTED_AUTHORITY_DIGEST
    ):
        raise RemainingP1FamilyAuthorityError("baseline control drifted")
    return control


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control["authority"]
    return tuple(
        [authority["operating_direction"]]
        + list(authority["contracts"])
        + list(authority["foundation_inputs"])
    )


def _registry() -> EvidenceValidatorRegistry:
    return EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))


def _inventory(index: Any) -> dict[str, int]:
    return {
        kind: len(index.records_by_kind(kind))
        for kind in SCIENTIFIC_INVENTORY_KINDS
    }


def _replay_status_counts(index: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _obligation, head in obligation_heads(index, mission_id=MISSION_ID):
        counts[head.status] = counts.get(head.status, 0) + 1
    return counts


def _family_surface(
    study_id: str,
) -> tuple[HistoricalFamilySpec, str]:
    surfaces = {
        "STU-0046": (
            STU0046_HISTORICAL_FAMILY,
            "historical_family_stu0046.py",
        ),
        "STU-0047": (
            STU0047_HISTORICAL_FAMILY,
            "historical_family_stu0047.py",
        ),
        "STU-0049": (
            STU0049_HISTORICAL_FAMILY,
            "historical_family_stu0049.py",
        ),
        "STU-0050": (
            STU0050_HISTORICAL_FAMILY,
            "historical_family_stu0050.py",
        ),
    }
    try:
        return surfaces[study_id]
    except KeyError as exc:
        raise RemainingP1FamilyAuthorityError(
            "pending family target names an unexpected historical Study"
        ) from exc


def _family_authorities(index: Any) -> tuple[HistoricalFamilyAuthority, ...]:
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
    }
    authorities: list[HistoricalFamilyAuthority] = []
    for obligation_id in sorted(EXPECTED_AUTHORITY_IDS):
        pair = heads.get(obligation_id)
        if pair is None or pair[1].status != "pending":
            raise RemainingP1FamilyAuthorityError(
                "family-authority target is not exactly pending"
            )
        obligation = pair[0]
        base, module = _family_surface(obligation.original_study_id)
        manifest = base.manifest()
        manifest["target_historical_executable_id"] = (
            obligation.original_executable_id
        )
        relative = f"src/axiom_rift/research/{module}"
        source_hash = sha256((ROOT / relative).read_bytes()).hexdigest()
        if HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.get(module) != source_hash:
            raise RemainingP1FamilyAuthorityError(
                "historical family source bytes drifted"
            )
        authority = HistoricalFamilyAuthority(
            replay_obligation_id=obligation_id,
            family=historical_family_from_manifest(manifest),
            reconstruction_source_path=relative,
            reconstruction_source_sha256=source_hash,
        )
        if authority.identity != EXPECTED_AUTHORITY_IDS[obligation_id]:
            raise RemainingP1FamilyAuthorityError(
                "derived target-specific family authority drifted"
            )
        authorities.append(authority)
    return tuple(authorities)


def _copy_git_file(root: Path, relative: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_git_blob("origin/main", relative))


@contextmanager
def _baseline_shadow() -> Iterator[StateWriter]:
    with TemporaryDirectory(prefix="axiom-remaining-family-shadow-") as name:
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
        for relative in SOURCE_MODULE_PATHS:
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
            raise RemainingP1FamilyAuthorityError(
                "isolated baseline reconstruction drifted"
            )
        yield writer


def _register(writer: StateWriter) -> dict[str, Any]:
    with writer.open_stable_index() as (_control, index):
        authorities = _family_authorities(index)
    result = writer.register_historical_replay_family_authorities(
        historical_family_authorities=authorities,
        operation_id=OPERATION_ID,
    )
    return {"event_id": result.event_id, "revision": result.revision}


def _assert_final(
    writer: StateWriter,
    *,
    baseline_inventory: Mapping[str, int],
    baseline_family_authority_count: int,
) -> dict[str, Any]:
    baseline = _baseline_control()
    with writer.open_stable_index() as (control, index):
        operation = index.get("operation", OPERATION_ID)
        for obligation_id, authority_id in EXPECTED_AUTHORITY_IDS.items():
            record = index.get("historical-family-authority", authority_id)
            if record is None:
                raise RemainingP1FamilyAuthorityError(
                    "registered historical family authority is absent"
                )
            authority = require_recorded_historical_family_authority(
                index,
                record,
            )
            if authority.replay_obligation_id != obligation_id:
                raise RemainingP1FamilyAuthorityError(
                    "registered historical family authority target drifted"
                )
        status_counts = _replay_status_counts(index)
        family_authority_count = len(
            index.records_by_kind("historical-family-authority")
        )
        operation_result = (
            None if operation is None else operation.payload.get("result")
        )
        checks = {
            "authority_digest": (
                control.get("authority", {}).get("manifest_digest")
                == EXPECTED_AUTHORITY_DIGEST
            ),
            "candidate_delta": (
                isinstance(operation_result, Mapping)
                and operation_result.get("candidate_delta") == 0
            ),
            "event_kind": (
                operation is not None
                and operation.payload.get("event_kind") == EVENT_KIND
            ),
            "family_authority_count": (
                family_authority_count
                == baseline_family_authority_count + len(EXPECTED_AUTHORITY_IDS)
            ),
            "holdout_reveal_delta": (
                isinstance(operation_result, Mapping)
                and operation_result.get("holdout_reveal_delta") == 0
            ),
            "inventory": _inventory(index) == dict(baseline_inventory),
            "next_action": control.get("next_action") == baseline.get("next_action"),
            "operation": operation is not None,
            "record_count": index.record_count() == EXPECTED_FINAL_RECORD_COUNT,
            "replay_status_counts": status_counts == EXPECTED_REPLAY_STATUS_COUNTS,
            "revision": control.get("revision") == EXPECTED_FINAL_REVISION,
            "science": control.get("scientific") == baseline.get("scientific"),
            "sequence": (
                operation is not None
                and operation.authority_sequence == EXPECTED_FINAL_REVISION
            ),
            "scientific_trial_delta": (
                isinstance(operation_result, Mapping)
                and operation_result.get("scientific_trial_delta") == 0
            ),
        }
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise RemainingP1FamilyAuthorityError(
                "final authority, science, replay, or scheduler projection "
                f"drifted: {failed}"
            )
        return {
            "candidate_count": baseline_inventory["candidate"],
            "family_authority_count": family_authority_count,
            "holdout_reveal_count": control["scientific"]["holdout_reveals"],
            "record_count": index.record_count(),
            "replay_status_counts": status_counts,
            "revision": control["revision"],
            "trial_count": baseline_inventory["trial"],
        }


def _report_digest() -> str:
    content = (ROOT / AUDIT_REPORT_PATH).read_bytes()
    try:
        content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RemainingP1FamilyAuthorityError(
            "authority reconstruction report is not ASCII"
        ) from exc
    return sha256(content).hexdigest()


def read_only_plan() -> dict[str, Any]:
    report_digest = _report_digest()
    with _baseline_shadow() as writer:
        with writer.open_stable_index() as (_control, index):
            baseline_inventory = _inventory(index)
            baseline_family_authority_count = len(
                index.records_by_kind("historical-family-authority")
            )
            if _replay_status_counts(index) != EXPECTED_REPLAY_STATUS_COUNTS:
                raise RemainingP1FamilyAuthorityError(
                    "baseline replay inventory drifted"
                )
        event = _register(writer)
        final = _assert_final(
            writer,
            baseline_inventory=baseline_inventory,
            baseline_family_authority_count=baseline_family_authority_count,
        )
    return {
        "apply_mutation_performed": False,
        "audit_report_sha256": report_digest,
        "authority_count": len(EXPECTED_AUTHORITY_IDS),
        "baseline_scientific_inventory": baseline_inventory,
        "event": event,
        "final_projection": final,
        "schema": "remaining_p1_family_authority_plan.v1",
    }


def _require_code_checkpoint() -> tuple[str, str]:
    branch = str(_git("branch", "--show-current", text=True)).strip()
    head = str(_git("rev-parse", "HEAD", text=True)).strip()
    origin = str(_git("rev-parse", "origin/main", text=True)).strip()
    changed_raw = str(_git("diff", "--name-only", "HEAD", text=True))
    changed = set(changed_raw.splitlines())
    allowed_state = {"state/control.json"}
    allowed_state.update(
        path for path in changed if path.startswith("records/journal/")
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
        or any(
            _git_blob("HEAD", relative) != (ROOT / relative).read_bytes()
            for relative in CODE_CHECKPOINT_PATHS
        )
    ):
        raise RemainingP1FamilyAuthorityError(
            "apply requires one clean unpublished local-main code checkpoint"
        )
    return head, origin


def apply() -> dict[str, Any]:
    if not _SAFE_STARTUP:
        raise RemainingP1FamilyAuthorityError("apply startup is not isolated")
    checkpoint, origin = _require_code_checkpoint()
    preview = read_only_plan()
    baseline_inventory = preview["baseline_scientific_inventory"]
    final_preview = preview["final_projection"]
    if not isinstance(baseline_inventory, dict) or not isinstance(
        final_preview,
        dict,
    ):
        raise RemainingP1FamilyAuthorityError("shadow plan is malformed")
    baseline_family_authority_count = (
        final_preview["family_authority_count"] - len(EXPECTED_AUTHORITY_IDS)
    )
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
    result: dict[str, Any] | None = None
    if revision == EXPECTED_BASELINE_REVISION:
        writer = StateWriter(
            ROOT,
            study_close_delivery_observation=delivery,
            validation_registry=_registry(),
        )
        result = _register(writer)
    elif revision != EXPECTED_FINAL_REVISION:
        raise RemainingP1FamilyAuthorityError(
            "current revision is outside the exact registration prefix"
        )
    final_writer = StateWriter(
        ROOT,
        study_close_delivery_observation=delivery,
        validation_registry=_registry(),
    )
    final = _assert_final(
        final_writer,
        baseline_inventory=baseline_inventory,
        baseline_family_authority_count=baseline_family_authority_count,
    )
    return {
        "already_complete": result is None,
        "applied_event": result,
        "code_checkpoint_commit": checkpoint,
        "final_projection": final,
        "schema": "remaining_p1_family_authority_apply.v1",
        "shadow_plan": preview,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the exact shadow-proven one-event authority registration",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    result = apply() if arguments.apply else read_only_plan()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
