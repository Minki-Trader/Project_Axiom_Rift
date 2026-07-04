"""SC0004 source adapter for C0012 R0001 auction rotation evidence."""

from __future__ import annotations

from axiom_rift.proxies.c0012_r0001_session_auction_rotation import (
    FEATURE_NAMES,
    build_candidates,
    build_context,
    fit_linear_auction_model,
    linear_model_summary,
    read_trade_artifact,
    score_candidates,
)
