"""Narrow parsing for evidence-bound ASCII audit finding blocks."""

from __future__ import annotations


class AuditReportBindingError(ValueError):
    """Raised when a report does not contain one exact bound finding block."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise AuditReportBindingError(f"{name} must be non-empty ASCII")
    return value


def require_ascii_finding_block(
    document: bytes,
    *,
    finding_id: str,
    required_fragments: tuple[str, ...],
) -> str:
    """Return one bullet finding block only when all facts belong to that block."""

    if type(document) is not bytes:
        raise AuditReportBindingError("audit report must be exact bytes")
    try:
        text = document.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AuditReportBindingError("audit report must be ASCII") from exc
    finding = _ascii("audit finding id", finding_id)
    if type(required_fragments) is not tuple or not required_fragments:
        raise AuditReportBindingError("audit finding facts must be a non-empty tuple")
    fragments = tuple(_ascii("audit finding fact", item) for item in required_fragments)
    if len(set(fragments)) != len(fragments):
        raise AuditReportBindingError("audit finding facts must be unique")

    marker = f"- {finding}:"
    lines = text.splitlines()
    positions = [position for position, line in enumerate(lines) if line == marker]
    if len(positions) != 1:
        raise AuditReportBindingError("audit report finding is absent or duplicated")
    start = positions[0]
    block_lines = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip() or line.startswith("- ") or line.startswith("#"):
            break
        if not line.startswith("  "):
            raise AuditReportBindingError("audit finding continuation is malformed")
        block_lines.append(line)
    block = "\n".join(block_lines)
    if any(block.count(fragment) != 1 for fragment in fragments):
        raise AuditReportBindingError(
            "audit report finding does not contain its exact bound facts"
        )
    return block


__all__ = ["AuditReportBindingError", "require_ascii_finding_block"]
