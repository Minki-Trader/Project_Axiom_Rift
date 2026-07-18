"""Small shared-proof contract for cost-aware paired execution traces.

The neutral pair trace is one family artifact.  Subject Jobs retain distinct
calculation, measurement, result, and completion authority while referring to
the same content-addressed trace bytes.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA = (
    "cost_aware_execution_pair_trace.v1"
)
COST_AWARE_EXECUTION_PAIR_TRACE_PROOF_KIND = (
    "atomic_cost_aware_execution_pair_trace.v1"
)
_THIS_FILE = Path(__file__).resolve()


def cost_aware_execution_shared_contract_implementation_sha256() -> str:
    """Bind the shared proof vocabulary to prospective Job identity."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


__all__ = [
    "COST_AWARE_EXECUTION_PAIR_TRACE_PROOF_KIND",
    "COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA",
    "cost_aware_execution_shared_contract_implementation_sha256",
]
