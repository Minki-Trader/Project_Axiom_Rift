"""Load the audit-selected replay inventory as declarative Job input."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes


P0_REPLAY_INVENTORY_SCHEMA = "p0_replay_inventory.v1"
_MEMBER_FIELDS = {
    "adapter",
    "configuration_id",
    "executable_id",
    "legacy_evaluation_sha256",
    "study_id",
}


def p0_replay_inventory_path() -> Path:
    return Path(__file__).resolve().with_name("p0_replay_inventory.json")


def p0_replay_inventory_sha256() -> str:
    return sha256(p0_replay_inventory_path().read_bytes()).hexdigest()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(value not in "0123456789abcdef" for value in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def load_p0_replay_inventory() -> tuple[dict[str, str], ...]:
    path = p0_replay_inventory_path()
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("P0 replay inventory is unreadable") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"members", "schema"}
        or value.get("schema") != P0_REPLAY_INVENTORY_SCHEMA
        or not isinstance(value.get("members"), list)
        or not value["members"]
    ):
        raise ValueError("P0 replay inventory schema is invalid")
    members: list[dict[str, str]] = []
    for raw in value["members"]:
        if not isinstance(raw, dict) or set(raw) != _MEMBER_FIELDS:
            raise ValueError("P0 replay inventory member schema is invalid")
        member = {
            "adapter": _ascii("adapter", raw["adapter"]),
            "configuration_id": _ascii(
                "configuration_id", raw["configuration_id"]
            ),
            "executable_id": _ascii("executable_id", raw["executable_id"]),
            "legacy_evaluation_sha256": _digest(
                "legacy_evaluation_sha256", raw["legacy_evaluation_sha256"]
            ),
            "study_id": _ascii("study_id", raw["study_id"]),
        }
        executable_digest = member["executable_id"].removeprefix("executable:")
        if (
            not member["executable_id"].startswith("executable:")
            or len(executable_digest) != 64
            or any(value not in "0123456789abcdef" for value in executable_digest)
        ):
            raise ValueError("P0 replay inventory Executable identity is invalid")
        members.append(member)
    for field in ("configuration_id", "executable_id", "study_id"):
        values = [member[field] for member in members]
        if len(set(values)) != len(values):
            raise ValueError(f"P0 replay inventory {field} values are not unique")
    canonical_bytes({"members": members, "schema": P0_REPLAY_INVENTORY_SCHEMA})
    return tuple(members)


__all__ = [
    "P0_REPLAY_INVENTORY_SCHEMA",
    "load_p0_replay_inventory",
    "p0_replay_inventory_path",
    "p0_replay_inventory_sha256",
]
