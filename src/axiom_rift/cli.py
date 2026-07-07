"""Small command line entrypoint for workspace checks."""

from __future__ import annotations

import argparse
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import CAMPAIGN_DIR, CONFIG_DIR, CONTRACT_DIR, PROJECT_ROOT, REGISTRY_DIR


LOGIC_PARITY_MODE = "logic_parity"
TICK_EXECUTION_MODE = "tick_execution"
MODE_CHOICES = (LOGIC_PARITY_MODE, TICK_EXECUTION_MODE)
RESULT_JSON_TARGET = "axiom_rift.validation.work_units:result_json"


@dataclass(frozen=True)
class ArgSpec:
    flags: tuple[str, ...]
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help: str
    kind: str
    target: str | None = None
    args: tuple[ArgSpec, ...] = ()


@dataclass(frozen=True)
class RunSpec:
    slug: str
    mt5_module: str
    proxy_module: str
    logic_func: str | None = None

    @property
    def command_stem(self) -> str:
        return self.slug.replace("_", "-")

    @property
    def proxy_func(self) -> str:
        return f"run_{self.slug}_proxy"

    @property
    def compile_func(self) -> str:
        return f"compile_{self.slug}_ea"

    @property
    def mt5_logic_func(self) -> str:
        return self.logic_func or f"run_{self.slug}_mt5_logic_workflow"

    @property
    def mt5_tick_func(self) -> str:
        return f"run_{self.slug}_mt5_tick_workflow"

    @property
    def mt5_tick_by_fold_func(self) -> str:
        return f"run_{self.slug}_mt5_tick_by_fold_workflow"

    @property
    def parse_func(self) -> str:
        return f"parse_{self.slug}_mt5"

    @property
    def parity_func(self) -> str:
        return f"record_{self.slug}_parity"

    @property
    def divergence_func(self) -> str:
        return f"record_{self.slug}_execution_divergence"


def arg(*flags: str, **kwargs: Any) -> ArgSpec:
    return ArgSpec(flags=tuple(flags), kwargs=kwargs)


def target(module: str, function: str) -> str:
    return f"{module}:{function}"


DRY_RUN_ARG = arg("--dry-run", action="store_true", help="print proxy payload without writing files")
MT5_TIMEOUT_ARG = arg("--timeout-seconds", type=int, default=1800)
PARSE_MODE_ARG = arg("--mode", choices=MODE_CHOICES, default=LOGIC_PARITY_MODE)


RUN_SPECS: tuple[RunSpec, ...] = (
    RunSpec("r0001", "axiom_rift.mt5.r0001_probe", "axiom_rift.proxies.r0001_volatility_expansion"),
    RunSpec("r0002", "axiom_rift.mt5.r0002_probe", "axiom_rift.proxies.r0002_failed_continuation_reversal"),
    RunSpec("r0003", "axiom_rift.mt5.r0003_probe", "axiom_rift.proxies.r0003_failed_breakout_reclaim_reversal"),
    RunSpec("r0004", "axiom_rift.mt5.r0004_probe", "axiom_rift.proxies.r0004_compression_breakout_continuation"),
    RunSpec("r0005", "axiom_rift.mt5.r0005_probe", "axiom_rift.proxies.r0005_expansion_exhaustion_reversal"),
    RunSpec("r0006", "axiom_rift.mt5.r0006_probe", "axiom_rift.proxies.r0006_compression_breakout_reversal"),
    RunSpec("r0007", "axiom_rift.mt5.r0007_probe", "axiom_rift.proxies.r0007_core_session_expansion_continuation"),
    RunSpec("c0002_r0001", "axiom_rift.mt5.c0002_r0001_probe", "axiom_rift.proxies.c0002_r0001_score_conditioned"),
    RunSpec("c0002_r0002", "axiom_rift.mt5.c0002_r0002_probe", "axiom_rift.proxies.c0002_r0002_exhaustion_reversal"),
    RunSpec("c0002_r0003", "axiom_rift.mt5.c0002_r0003_probe", "axiom_rift.proxies.c0002_r0003_dual_direction_cell_score"),
    RunSpec("c0002_r0004", "axiom_rift.mt5.c0002_r0004_probe", "axiom_rift.proxies.c0002_r0004_stump_rank_ensemble"),
    RunSpec(
        "sc0001_sr0001",
        "axiom_rift.mt5.sc0001_sr0001_probe",
        "axiom_rift.proxies.sc0001_sr0001_synthesis_constraints",
        logic_func="run_sc0001_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0002_sr0001",
        "axiom_rift.mt5.sc0002_sr0001_probe",
        "axiom_rift.proxies.sc0002_sr0001_cross_surface_veto_inversion",
        logic_func="run_sc0002_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0003_sr0001",
        "axiom_rift.mt5.sc0003_sr0001_probe",
        "axiom_rift.proxies.sc0003_sr0001_cross_family_fragile_candidate_hardening",
        logic_func="run_sc0003_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0004_sr0001",
        "axiom_rift.mt5.sc0004_sr0001_probe",
        "axiom_rift.proxies.sc0004_sr0001_post_sc0003_mixed_evidence_synthesis",
        logic_func="run_sc0004_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0005_sr0001",
        "axiom_rift.mt5.sc0005_sr0001_probe",
        "axiom_rift.proxies.sc0005_sr0001_post_c0022_negative_memory_synthesis",
        logic_func="run_sc0005_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0006_sr0001",
        "axiom_rift.mt5.sc0006_sr0001_probe",
        "axiom_rift.proxies.sc0006_sr0001_post_c0030_negative_memory_synthesis",
        logic_func="run_sc0006_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0007_sr0001",
        "axiom_rift.mt5.sc0007_sr0001_probe",
        "axiom_rift.proxies.sc0007_sr0001_post_sc0006_price_memory_negative_context",
        logic_func="run_sc0007_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0008_sr0001",
        "axiom_rift.mt5.sc0008_sr0001_probe",
        "axiom_rift.proxies.sc0008_sr0001_post_sc0007_regression_channel_residual_mixed_evidence",
        logic_func="run_sc0008_sr0001_logic_parity_workflow",
    ),
    RunSpec(
        "sc0009_sr0001",
        "axiom_rift.mt5.sc0009_sr0001_probe",
        "axiom_rift.proxies.sc0009_sr0001_post_sc0008_range_energy_mixed_evidence_synthesis",
        logic_func="run_sc0009_sr0001_logic_parity_workflow",
    ),
    RunSpec("c0004_r0001", "axiom_rift.mt5.c0004_r0001_probe", "axiom_rift.proxies.c0004_r0001_fold_local_state_archetype"),
    RunSpec("c0004_r0002", "axiom_rift.mt5.c0004_r0002_probe", "axiom_rift.proxies.c0004_r0002_path_quality_archetype"),
    RunSpec("c0004_r0003", "axiom_rift.mt5.c0004_r0003_probe", "axiom_rift.proxies.c0004_r0003_adverse_archetype_inversion"),
    RunSpec("c0004_r0004", "axiom_rift.mt5.c0004_r0004_probe", "axiom_rift.proxies.c0004_r0004_temporal_stability_archetype"),
    RunSpec("c0005_r0001", "axiom_rift.mt5.c0005_r0001_probe", "axiom_rift.proxies.c0005_r0001_continuous_analog_memory"),
    RunSpec("c0005_r0002", "axiom_rift.mt5.c0005_r0002_probe", "axiom_rift.proxies.c0005_r0002_directional_contrast_analog_memory"),
    RunSpec("c0005_r0003", "axiom_rift.mt5.c0005_r0003_probe", "axiom_rift.proxies.c0005_r0003_temporal_stability_analog_memory"),
    RunSpec(
        "c0005_r0004",
        "axiom_rift.mt5.c0005_r0004_probe",
        "axiom_rift.proxies.c0005_r0004_target_first_tail_hazard_analog_memory",
    ),
    RunSpec("c0005_r0005", "axiom_rift.mt5.c0005_r0005_probe", "axiom_rift.proxies.c0005_r0005_calibrated_analog_classifier"),
    RunSpec(
        "c0005_r0006",
        "axiom_rift.mt5.c0005_r0006_probe",
        "axiom_rift.proxies.c0005_r0006_metric_rank_ensemble_analog_memory",
    ),
    RunSpec("c0006_r0001", "axiom_rift.mt5.c0006_r0001_probe", "axiom_rift.proxies.c0006_r0001_liquidity_sweep_reclaim"),
    RunSpec("c0006_r0002", "axiom_rift.mt5.c0006_r0002_probe", "axiom_rift.proxies.c0006_r0002_sweep_acceptance_continuation"),
    RunSpec("c0006_r0003", "axiom_rift.mt5.c0006_r0003_probe", "axiom_rift.proxies.c0006_r0003_delayed_sweep_trap_rejection"),
    RunSpec("c0006_r0004", "axiom_rift.mt5.c0006_r0004_probe", "axiom_rift.proxies.c0006_r0004_two_sided_sweep_reversion"),
    RunSpec("c0006_r0005", "axiom_rift.mt5.c0006_r0005_probe", "axiom_rift.proxies.c0006_r0005_reclaim_retest_rejection"),
    RunSpec("c0007_r0001", "axiom_rift.mt5.c0007_r0001_probe", "axiom_rift.proxies.c0007_r0001_fold_local_supervised_edge"),
    RunSpec("c0007_r0002", "axiom_rift.mt5.c0007_r0002_probe", "axiom_rift.proxies.c0007_r0002_dual_hazard_logistic_edge"),
    RunSpec("c0007_r0003", "axiom_rift.mt5.c0007_r0003_probe", "axiom_rift.proxies.c0007_r0003_nonlinear_interaction_edge_ensemble"),
    RunSpec("c0008_r0001", "axiom_rift.mt5.c0008_r0001_probe", "axiom_rift.proxies.c0008_r0001_multi_timeframe_structural_context"),
    RunSpec("c0008_r0002", "axiom_rift.mt5.c0008_r0002_probe", "axiom_rift.proxies.c0008_r0002_structural_trap_reversal"),
    RunSpec("c0008_r0003", "axiom_rift.mt5.c0008_r0003_probe", "axiom_rift.proxies.c0008_r0003_structural_trap_robustness"),
    RunSpec(
        "c0008_r0004",
        "axiom_rift.mt5.c0008_r0004_probe",
        "axiom_rift.proxies.c0008_r0004_structural_acceptance_continuation",
    ),
    RunSpec(
        "c0009_r0001",
        "axiom_rift.mt5.c0009_r0001_probe",
        "axiom_rift.proxies.c0009_r0001_execution_friction_regime",
    ),
    RunSpec(
        "c0009_r0002",
        "axiom_rift.mt5.c0009_r0002_probe",
        "axiom_rift.proxies.c0009_r0002_execution_degradation_abstention",
    ),
    RunSpec(
        "c0009_r0003",
        "axiom_rift.mt5.c0009_r0003_probe",
        "axiom_rift.proxies.c0009_r0003_intrabar_ambiguity_avoidance",
    ),
    RunSpec(
        "c0010_r0001",
        "axiom_rift.mt5.c0010_r0001_probe",
        "axiom_rift.proxies.c0010_r0001_monthly_regime_risk_control",
    ),
    RunSpec(
        "c0010_r0002",
        "axiom_rift.mt5.c0010_r0002_probe",
        "axiom_rift.proxies.c0010_r0002_monthly_loss_memory_abstention",
    ),
    RunSpec(
        "c0011_r0001",
        "axiom_rift.mt5.c0011_r0001_probe",
        "axiom_rift.proxies.c0011_r0001_setup_lifecycle_timing",
    ),
    RunSpec(
        "c0011_r0002",
        "axiom_rift.mt5.c0011_r0002_probe",
        "axiom_rift.proxies.c0011_r0002_setup_invalidation_reversal",
    ),
    RunSpec(
        "c0012_r0001",
        "axiom_rift.mt5.c0012_r0001_probe",
        "axiom_rift.proxies.c0012_r0001_session_auction_rotation",
    ),
    RunSpec(
        "c0012_r0002",
        "axiom_rift.mt5.c0012_r0002_probe",
        "axiom_rift.proxies.c0012_r0002_session_auction_rotation_robustness",
    ),
    RunSpec(
        "c0012_r0003",
        "axiom_rift.mt5.c0012_r0003_probe",
        "axiom_rift.proxies.c0012_r0003_session_auction_transition_hazard",
    ),
    RunSpec(
        "c0013_r0001",
        "axiom_rift.mt5.c0013_r0001_probe",
        "axiom_rift.proxies.c0013_r0001_path_resilience_recovery",
    ),
    RunSpec(
        "c0014_r0001",
        "axiom_rift.mt5.c0014_r0001_probe",
        "axiom_rift.proxies.c0014_r0001_interday_range_handoff",
    ),
    RunSpec(
        "c0015_r0001",
        "axiom_rift.mt5.c0015_r0001_probe",
        "axiom_rift.proxies.c0015_r0001_liquidity_vacuum_rebound",
    ),
    RunSpec(
        "c0016_r0001",
        "axiom_rift.mt5.c0016_r0001_probe",
        "axiom_rift.proxies.c0016_r0001_intraday_directional_imbalance",
    ),
    RunSpec(
        "c0017_r0001",
        "axiom_rift.mt5.c0017_r0001_probe",
        "axiom_rift.proxies.c0017_r0001_round_level_magnet_rejection",
    ),
    RunSpec(
        "c0018_r0001",
        "axiom_rift.mt5.c0018_r0001_probe",
        "axiom_rift.proxies.c0018_r0001_micro_gap_absorption",
    ),
    RunSpec(
        "c0019_r0001",
        "axiom_rift.mt5.c0019_r0001_probe",
        "axiom_rift.proxies.c0019_r0001_bar_quality_asymmetry",
    ),
    RunSpec(
        "c0020_r0001",
        "axiom_rift.mt5.c0020_r0001_probe",
        "axiom_rift.proxies.c0020_r0001_excursion_decay_memory",
    ),
    RunSpec(
        "c0021_r0001",
        "axiom_rift.mt5.c0021_r0001_probe",
        "axiom_rift.proxies.c0021_r0001_daily_profile_energy_balance",
    ),
    RunSpec(
        "c0022_r0001",
        "axiom_rift.mt5.c0022_r0001_probe",
        "axiom_rift.proxies.c0022_r0001_volatility_term_structure",
    ),
    RunSpec(
        "c0023_r0001",
        "axiom_rift.mt5.c0023_r0001_probe",
        "axiom_rift.proxies.c0023_r0001_tick_participation_pressure",
    ),
    RunSpec(
        "c0024_r0001",
        "axiom_rift.mt5.c0024_r0001_probe",
        "axiom_rift.proxies.c0024_r0001_calendar_phase_rhythm",
    ),
    RunSpec(
        "c0025_r0001",
        "axiom_rift.mt5.c0025_r0001_probe",
        "axiom_rift.proxies.c0025_r0001_range_overlap_topology",
    ),
    RunSpec(
        "c0026_r0001",
        "axiom_rift.mt5.c0026_r0001_probe",
        "axiom_rift.proxies.c0026_r0001_price_acceleration_curvature",
    ),
    RunSpec(
        "c0027_r0001",
        "axiom_rift.mt5.c0027_r0001_probe",
        "axiom_rift.proxies.c0027_r0001_symbolic_microstructure_grammar",
    ),
    RunSpec(
        "c0028_r0001",
        "axiom_rift.mt5.c0028_r0001_probe",
        "axiom_rift.proxies.c0028_r0001_intraday_swing_leg_maturity",
    ),
    RunSpec(
        "c0029_r0001",
        "axiom_rift.mt5.c0029_r0001_probe",
        "axiom_rift.proxies.c0029_r0001_intraday_fractal_pivot_transition",
    ),
    RunSpec(
        "c0030_r0001",
        "axiom_rift.mt5.c0030_r0001_probe",
        "axiom_rift.proxies.c0030_r0001_intraday_vwap_repricing_pressure",
    ),
    RunSpec(
        "c0031_r0001",
        "axiom_rift.mt5.c0031_r0001_probe",
        "axiom_rift.proxies.c0031_r0001_intraday_entropy_release",
    ),
    RunSpec(
        "c0032_r0001",
        "axiom_rift.mt5.c0032_r0001_probe",
        "axiom_rift.proxies.c0032_r0001_intraday_tail_risk_skew",
    ),
    RunSpec(
        "c0033_r0001",
        "axiom_rift.mt5.c0033_r0001_probe",
        "axiom_rift.proxies.c0033_r0001_intraday_seasonal_residual_dislocation",
    ),
    RunSpec(
        "c0034_r0001",
        "axiom_rift.mt5.c0034_r0001_probe",
        "axiom_rift.proxies.c0034_r0001_intraday_effort_price_absorption",
    ),
    RunSpec(
        "c0035_r0001",
        "axiom_rift.mt5.c0035_r0001_probe",
        "axiom_rift.proxies.c0035_r0001_intraday_cycle_phase_resonance",
    ),
    RunSpec(
        "c0036_r0001",
        "axiom_rift.mt5.c0036_r0001_probe",
        "axiom_rift.proxies.c0036_r0001_intraday_range_impulse_memory",
    ),
    RunSpec(
        "c0037_r0001",
        "axiom_rift.mt5.c0037_r0001_probe",
        "axiom_rift.proxies.c0037_r0001_intraday_price_memory_density",
    ),
    RunSpec(
        "c0037_r0002",
        "axiom_rift.mt5.c0037_r0002_probe",
        "axiom_rift.proxies.c0037_r0002_price_memory_density_robustness",
    ),
    RunSpec(
        "c0037_r0003",
        "axiom_rift.mt5.c0037_r0003_probe",
        "axiom_rift.proxies.c0037_r0003_price_memory_density_tail_stability",
    ),
    RunSpec(
        "c0037_r0004",
        "axiom_rift.mt5.c0037_r0004_probe",
        "axiom_rift.proxies.c0037_r0004_price_memory_density_monthly_distribution",
    ),
    RunSpec(
        "c0038_r0001",
        "axiom_rift.mt5.c0038_r0001_probe",
        "axiom_rift.proxies.c0038_r0001_intraday_dwell_transition_timing",
    ),
    RunSpec(
        "c0039_r0001",
        "axiom_rift.mt5.c0039_r0001_probe",
        "axiom_rift.proxies.c0039_r0001_intraday_moving_average_ribbon_phase",
    ),
    RunSpec(
        "c0040_r0001",
        "axiom_rift.mt5.c0040_r0001_probe",
        "axiom_rift.proxies.c0040_r0001_intraday_return_distribution_shape",
    ),
    RunSpec(
        "c0041_r0001",
        "axiom_rift.mt5.c0041_r0001_probe",
        "axiom_rift.proxies.c0041_r0001_intraday_autocorrelation_decay",
    ),
    RunSpec(
        "c0042_r0001",
        "axiom_rift.mt5.c0042_r0001_probe",
        "axiom_rift.proxies.c0042_r0001_intraday_path_symmetry_imbalance",
    ),
    RunSpec(
        "c0043_r0001",
        "axiom_rift.mt5.c0043_r0001_probe",
        "axiom_rift.proxies.c0043_r0001_intraday_range_shock_digest",
    ),
    RunSpec(
        "c0044_r0001",
        "axiom_rift.mt5.c0044_r0001_probe",
        "axiom_rift.proxies.c0044_r0001_intraday_extreme_recency_gradient",
    ),
    RunSpec(
        "c0045_r0001",
        "axiom_rift.mt5.c0045_r0001_probe",
        "axiom_rift.proxies.c0045_r0001_intraday_regression_channel_residual",
    ),
    RunSpec(
        "c0045_r0002",
        "axiom_rift.mt5.c0045_r0002_probe",
        "axiom_rift.proxies.c0045_r0002_intraday_regression_channel_residual_cost_buffer",
    ),
    RunSpec(
        "c0045_r0003",
        "axiom_rift.mt5.c0045_r0003_probe",
        "axiom_rift.proxies.c0045_r0003_intraday_regression_channel_residual_stress_materialization",
    ),
    RunSpec(
        "c0046_r0001",
        "axiom_rift.mt5.c0046_r0001_probe",
        "axiom_rift.proxies.c0046_r0001_intraday_flow_convexity_release",
    ),
    RunSpec(
        "c0046_r0002",
        "axiom_rift.mt5.c0046_r0002_probe",
        "axiom_rift.proxies.c0046_r0002_intraday_flow_convexity_release",
    ),
    RunSpec(
        "c0047_r0001",
        "axiom_rift.mt5.c0047_r0001_probe",
        "axiom_rift.proxies.c0047_r0001_intraday_liquidity_void_reversion",
    ),
    RunSpec(
        "c0047_r0002",
        "axiom_rift.mt5.c0047_r0002_probe",
        "axiom_rift.proxies.c0047_r0002_intraday_liquidity_void_rejection_continuation",
    ),
    RunSpec(
        "c0048_r0001",
        "axiom_rift.mt5.c0048_r0001_probe",
        "axiom_rift.proxies.c0048_r0001_intraday_range_energy_absorption",
    ),
    RunSpec(
        "c0048_r0002",
        "axiom_rift.mt5.c0048_r0002_probe",
        "axiom_rift.proxies.c0048_r0002_intraday_range_energy_absorption_reversal",
    ),
    RunSpec(
        "c0049_r0001",
        "axiom_rift.mt5.c0049_r0001_probe",
        "axiom_rift.proxies.c0049_r0001_intraday_execution_path_resilience",
    ),
    RunSpec(
        "c0050_r0001",
        "axiom_rift.mt5.c0050_r0001_probe",
        "axiom_rift.proxies.c0050_r0001_intraday_volatility_transfer",
    ),
    RunSpec(
        "c0051_r0001",
        "axiom_rift.mt5.c0051_r0001_probe",
        "axiom_rift.proxies.c0051_r0001_intraday_gap_continuity_decay",
    ),
    RunSpec(
        "c0052_r0001",
        "axiom_rift.mt5.c0052_r0001_probe",
        "axiom_rift.proxies.c0052_r0001_intraday_orderflow_dislocation_recovery",
    ),
    RunSpec(
        "c0053_r0001",
        "axiom_rift.mt5.c0053_r0001_probe",
        "axiom_rift.proxies.c0053_r0001_intraday_opening_range_retest",
    ),
    RunSpec(
        "c0054_r0001",
        "axiom_rift.mt5.c0054_r0001_probe",
        "axiom_rift.proxies.c0054_r0001_intraday_late_session_inventory_unwind",
    ),
    RunSpec(
        "c0055_r0001",
        "axiom_rift.mt5.c0055_r0001_probe",
        "axiom_rift.proxies.c0055_r0001_intraday_range_ladder_acceptance",
    ),
    RunSpec(
        "c0056_r0001",
        "axiom_rift.mt5.c0056_r0001_probe",
        "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
    ),
    RunSpec(
        "c0057_r0001",
        "axiom_rift.mt5.c0057_r0001_probe",
        "axiom_rift.proxies.c0057_r0001_intraday_impulse_response_latency",
    ),
    RunSpec(
        "c0058_r0001",
        "axiom_rift.mt5.c0058_r0001_probe",
        "axiom_rift.proxies.c0058_r0001_intraday_body_overlap_resorption",
    ),
    RunSpec(
        "c0059_r0001",
        "axiom_rift.mt5.c0059_r0001_probe",
        "axiom_rift.proxies.c0059_r0001_intraday_session_handoff_pressure",
    ),
    RunSpec(
        "c0060_r0001",
        "axiom_rift.mt5.c0060_r0001_probe",
        "axiom_rift.proxies.c0060_r0001_intraday_close_location_migration",
    ),
    RunSpec(
        "c0061_r0001",
        "axiom_rift.mt5.c0061_r0001_probe",
        "axiom_rift.proxies.c0061_r0001_intraday_adverse_excursion_recovery",
    ),
    RunSpec(
        "c0062_r0001",
        "axiom_rift.mt5.c0062_r0001_probe",
        "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
    ),
    RunSpec(
        "c0063_r0001",
        "axiom_rift.mt5.c0063_r0001_probe",
        "axiom_rift.proxies.c0063_r0001_intraday_auction_imbalance_decay",
    ),
    RunSpec(
        "c0064_r0001",
        "axiom_rift.mt5.c0064_r0001_probe",
        "axiom_rift.proxies.c0064_r0001_intraday_polarity_flip_persistence",
    ),
    RunSpec(
        "c0065_r0001",
        "axiom_rift.mt5.c0065_r0001_probe",
        "axiom_rift.proxies.c0065_r0001_intraday_anchor_tension_resolution",
    ),
    RunSpec(
        "c0066_r0001",
        "axiom_rift.mt5.c0066_r0001_probe",
        "axiom_rift.proxies.c0066_r0001_intraday_shadow_inventory_release",
    ),
    RunSpec(
        "c0067_r0001",
        "axiom_rift.mt5.c0067_r0001_probe",
        "axiom_rift.proxies.c0067_r0001_intraday_trapped_range_reexpansion",
    ),
    RunSpec(
        "c0068_r0001",
        "axiom_rift.mt5.c0068_r0001_probe",
        "axiom_rift.proxies.c0068_r0001_intraday_failure_to_accept",
    ),
    RunSpec(
        "c0069_r0001",
        "axiom_rift.mt5.c0069_r0001_probe",
        "axiom_rift.proxies.c0069_r0001_intraday_drift_realignment",
    ),
    RunSpec(
        "c0070_r0001",
        "axiom_rift.mt5.c0070_r0001_probe",
        "axiom_rift.proxies.c0070_r0001_intraday_volatility_signature_transition",
    ),
    RunSpec(
        "c0071_r0001",
        "axiom_rift.mt5.c0071_r0001_probe",
        "axiom_rift.proxies.c0071_r0001_intraday_path_tortuosity_release",
    ),
    RunSpec(
        "c0072_r0001",
        "axiom_rift.mt5.c0072_r0001_probe",
        "axiom_rift.proxies.c0072_r0001_intraday_volume_imbalance_reconciliation",
    ),
    RunSpec(
        "c0073_r0001",
        "axiom_rift.mt5.c0073_r0001_probe",
        "axiom_rift.proxies.c0073_r0001_intraday_spread_shock_relief",
    ),
    RunSpec(
        "c0074_r0001",
        "axiom_rift.mt5.c0074_r0001_probe",
        "axiom_rift.proxies.c0074_r0001_intraday_session_range_reset",
    ),
    RunSpec(
        "c0075_r0001",
        "axiom_rift.mt5.c0075_r0001_probe",
        "axiom_rift.proxies.c0075_r0001_intraday_conviction_decay",
    ),
    RunSpec(
        "c0076_r0001",
        "axiom_rift.mt5.c0076_r0001_probe",
        "axiom_rift.proxies.c0076_r0001_intraday_extreme_dwell_imbalance",
    ),
    RunSpec(
        "c0077_r0001",
        "axiom_rift.mt5.c0077_r0001_probe",
        "axiom_rift.proxies.c0077_r0001_intraday_impulse_digestion_asymmetry",
    ),
    RunSpec(
        "c0078_r0001",
        "axiom_rift.mt5.c0078_r0001_probe",
        "axiom_rift.proxies.c0078_r0001_intraday_auction_skew_inflection",
    ),
    RunSpec(
        "c0079_r0001",
        "axiom_rift.mt5.c0079_r0001_probe",
        "axiom_rift.proxies.c0079_r0001_intraday_boundary_recoil_elasticity",
    ),
    RunSpec(
        "c0080_r0001",
        "axiom_rift.mt5.c0080_r0001_probe",
        "axiom_rift.proxies.c0080_r0001_intraday_micro_pullback_failure",
    ),
    RunSpec(
        "c0081_r0001",
        "axiom_rift.mt5.c0081_r0001_probe",
        "axiom_rift.proxies.c0081_r0001_intraday_failed_acceleration_absorption",
    ),
    RunSpec(
        "c0082_r0001",
        "axiom_rift.mt5.c0082_r0001_probe",
        "axiom_rift.proxies.c0082_r0001_intraday_midpoint_rotation_rejection",
    ),
    RunSpec(
        "c0082_r0002",
        "axiom_rift.mt5.c0082_r0002_probe",
        "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
    ),
    RunSpec(
        "c0083_r0001",
        "axiom_rift.mt5.c0083_r0001_probe",
        "axiom_rift.proxies.c0083_r0001_intraday_shelf_acceptance_continuation",
    ),
    RunSpec(
        "c0084_r0001",
        "axiom_rift.mt5.c0084_r0001_probe",
        "axiom_rift.proxies.c0084_r0001_intraday_local_equilibrium_displacement_reversion",
    ),
    RunSpec(
        "c0085_r0001",
        "axiom_rift.mt5.c0085_r0001_probe",
        "axiom_rift.proxies.c0085_r0001_intraday_zigzag_release",
    ),
    RunSpec(
        "c0086_r0001",
        "axiom_rift.mt5.c0086_r0001_probe",
        "axiom_rift.proxies.c0086_r0001_intraday_opening_balance_reanchor",
    ),
    RunSpec(
        "c0087_r0001",
        "axiom_rift.mt5.c0087_r0001_probe",
        "axiom_rift.proxies.c0087_r0001_intraday_range_third_transition",
    ),
    RunSpec(
        "c0088_r0001",
        "axiom_rift.mt5.c0088_r0001_probe",
        "axiom_rift.proxies.c0088_r0001_intraday_prior_close_magnet_rejection",
    ),
    RunSpec(
        "c0089_r0001",
        "axiom_rift.mt5.c0089_r0001_probe",
        "axiom_rift.proxies.c0089_r0001_intraday_session_vwap_dislocation_reversion",
    ),
    RunSpec(
        "c0090_r0001",
        "axiom_rift.mt5.c0090_r0001_probe",
        "axiom_rift.proxies.c0090_r0001_intraday_volatility_regime_break_compression_release",
    ),
    RunSpec(
        "c0091_r0001",
        "axiom_rift.mt5.c0091_r0001_probe",
        "axiom_rift.proxies.c0091_r0001_intraday_path_asymmetry_hazard",
    ),
    RunSpec(
        "c0092_r0001",
        "axiom_rift.mt5.c0092_r0001_probe",
        "axiom_rift.proxies.c0092_r0001_intraday_cost_pressure_absorption",
    ),
    RunSpec(
        "c0093_r0001",
        "axiom_rift.mt5.c0093_r0001_probe",
        "axiom_rift.proxies.c0093_r0001_intraday_participation_pulse_efficiency",
    ),
    RunSpec(
        "c0094_r0001",
        "axiom_rift.mt5.c0094_r0001_probe",
        "axiom_rift.proxies.c0094_r0001_intraday_streak_fatigue_reversal",
    ),
    RunSpec(
        "c0095_r0001",
        "axiom_rift.mt5.c0095_r0001_probe",
        "axiom_rift.proxies.c0095_r0001_intraday_close_cluster_escape",
    ),
    RunSpec(
        "c0096_r0001",
        "axiom_rift.mt5.c0096_r0001_probe",
        "axiom_rift.proxies.c0096_r0001_intraday_wick_stack_pressure_reversal",
    ),
    RunSpec(
        "c0097_r0001",
        "axiom_rift.mt5.c0097_r0001_probe",
        "axiom_rift.proxies.c0097_r0001_intraday_body_centroid_drift_reversal",
    ),
    RunSpec(
        "c0098_r0001",
        "axiom_rift.mt5.c0098_r0001_probe",
        "axiom_rift.proxies.c0098_r0001_intraday_range_variance_displacement_decoupling_reversal",
    ),
    RunSpec(
        "c0099_r0001",
        "axiom_rift.mt5.c0099_r0001_probe",
        "axiom_rift.proxies.c0099_r0001_intraday_failed_pullback_continuation",
    ),
    RunSpec(
        "c0100_r0001",
        "axiom_rift.mt5.c0100_r0001_probe",
        "axiom_rift.proxies.c0100_r0001_intraday_vwap_squeeze_expansion_breakout",
    ),
    RunSpec(
        "c0101_r0001",
        "axiom_rift.mt5.c0101_r0001_probe",
        "axiom_rift.proxies.c0101_r0001_intraday_volume_clock_desynchronization",
    ),
    RunSpec(
        "c0102_r0001",
        "axiom_rift.mt5.c0102_r0001_probe",
        "axiom_rift.proxies.c0102_r0001_intraday_open_close_energy_transfer",
    ),
    RunSpec(
        "c0103_r0001",
        "axiom_rift.mt5.c0103_r0001_probe",
        "axiom_rift.proxies.c0103_r0001_intraday_range_walk_entropy_transition",
    ),
    RunSpec(
        "c0104_r0001",
        "axiom_rift.mt5.c0104_r0001_probe",
        "axiom_rift.proxies.c0104_r0001_intraday_session_liquidity_vacuum_refill",
    ),
    RunSpec(
        "c0105_r0001",
        "axiom_rift.mt5.c0105_r0001_probe",
        "axiom_rift.proxies.c0105_r0001_intraday_close_pressure_followthrough",
    ),
    RunSpec(
        "c0106_r0001",
        "axiom_rift.mt5.c0106_r0001_probe",
        "axiom_rift.proxies.c0106_r0001_intraday_range_acceptance_failure_reversal",
    ),
    RunSpec(
        "c0107_r0001",
        "axiom_rift.mt5.c0107_r0001_probe",
        "axiom_rift.proxies.c0107_r0001_intraday_opening_drive_exhaustion_fade",
    ),
    RunSpec(
        "c0108_r0001",
        "axiom_rift.mt5.c0108_r0001_probe",
        "axiom_rift.proxies.c0108_r0001_intraday_gap_digestion_reversal",
    ),
    RunSpec(
        "c0109_r0001",
        "axiom_rift.mt5.c0109_r0001_probe",
        "axiom_rift.proxies.c0109_r0001_intraday_failed_vwap_reversion_continuation",
    ),
    RunSpec(
        "c0110_r0001",
        "axiom_rift.mt5.c0110_r0001_probe",
        "axiom_rift.proxies.c0110_r0001_intraday_extreme_retest_failure_reversal",
    ),
    RunSpec(
        "c0111_r0001",
        "axiom_rift.mt5.c0111_r0001_probe",
        "axiom_rift.proxies.c0111_r0001_intraday_cost_efficient_drift_continuation",
    ),
    RunSpec(
        "c0112_r0001",
        "axiom_rift.mt5.c0112_r0001_probe",
        "axiom_rift.proxies.c0112_r0001_intraday_micro_consolidation_breakout_continuation",
    ),
    RunSpec(
        "c0113_r0001",
        "axiom_rift.mt5.c0113_r0001_probe",
        "axiom_rift.proxies.c0113_r0001_intraday_session_percentile_transition",
    ),
    RunSpec(
        "c0114_r0001",
        "axiom_rift.mt5.c0114_r0001_probe",
        "axiom_rift.proxies.c0114_r0001_intraday_momentum_volume_divergence_reversal",
    ),
    RunSpec(
        "c0115_r0001",
        "axiom_rift.mt5.c0115_r0001_probe",
        "axiom_rift.proxies.c0115_r0001_intraday_prior_day_range_boundary_acceptance",
    ),
    RunSpec(
        "c0116_r0001",
        "axiom_rift.mt5.c0116_r0001_probe",
        "axiom_rift.proxies.c0116_r0001_intraday_day_open_anchor_reclaim",
    ),
    RunSpec(
        "c0117_r0001",
        "axiom_rift.mt5.c0117_r0001_probe",
        "axiom_rift.proxies.c0117_r0001_intraday_overnight_inventory_unwind",
    ),
    RunSpec(
        "c0118_r0001",
        "axiom_rift.mt5.c0118_r0001_probe",
        "axiom_rift.proxies.c0118_r0001_intraday_liquidity_shelf_decay_break",
    ),
    RunSpec(
        "c0119_r0001",
        "axiom_rift.mt5.c0119_r0001_probe",
        "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
    ),
    RunSpec(
        "c0120_r0001",
        "axiom_rift.mt5.c0120_r0001_probe",
        "axiom_rift.proxies.c0120_r0001_intraday_pullback_velocity_failure_reversal",
    ),
    RunSpec(
        "c0121_r0001",
        "axiom_rift.mt5.c0121_r0001_probe",
        "axiom_rift.proxies.c0121_r0001_intraday_counter_reversal_failure_continuation",
    ),
    RunSpec(
        "c0122_r0001",
        "axiom_rift.mt5.c0122_r0001_probe",
        "axiom_rift.proxies.c0122_r0001_intraday_compression_release_failure_fade",
    ),
    RunSpec(
        "c0123_r0001",
        "axiom_rift.mt5.c0123_r0001_probe",
        "axiom_rift.proxies.c0123_r0001_intraday_volatility_decay_trend_resumption",
    ),
    RunSpec(
        "c0124_r0001",
        "axiom_rift.mt5.c0124_r0001_probe",
        "axiom_rift.proxies.c0124_r0001_intraday_percentile_recoil_fade",
    ),
    RunSpec(
        "c0125_r0001",
        "axiom_rift.mt5.c0125_r0001_probe",
        "axiom_rift.proxies.c0125_r0001_intraday_halfback_inventory_transfer",
    ),
    RunSpec(
        "c0126_r0001",
        "axiom_rift.mt5.c0126_r0001_probe",
        "axiom_rift.proxies.c0126_r0001_intraday_volatility_budget_exhaustion_reversal",
    ),
    RunSpec(
        "c0127_r0001",
        "axiom_rift.mt5.c0127_r0001_probe",
        "axiom_rift.proxies.c0127_r0001_intraday_body_efficiency_cliff_reversal",
    ),
)


def add_command(commands: dict[str, CommandSpec], spec: CommandSpec) -> None:
    if spec.name in commands:
        raise RuntimeError(f"Duplicate CLI command: {spec.name}")
    commands[spec.name] = spec


def add_run_commands(commands: dict[str, CommandSpec], run: RunSpec) -> None:
    stem = run.command_stem
    label = stem.upper().replace("-", " ")
    add_command(
        commands,
        CommandSpec(
            name=f"run-{stem}-proxy",
            help=f"run {label} proxy evidence",
            kind="proxy_required_kpis",
            target=target(run.proxy_module, run.proxy_func),
            args=(DRY_RUN_ARG,),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"compile-{stem}-ea",
            help=f"compile {label} MT5 EA",
            kind="compile_ea",
            target=target(run.mt5_module, run.compile_func),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"run-{stem}-mt5-logic",
            help=f"run {label} MT5 closed-bar logic parity workflow",
            kind="mt5_workflow",
            target=target(run.mt5_module, run.mt5_logic_func),
            args=(MT5_TIMEOUT_ARG,),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"run-{stem}-mt5-tick",
            help=f"run {label} MT5 tick execution KPI workflow",
            kind="mt5_workflow",
            target=target(run.mt5_module, run.mt5_tick_func),
            args=(MT5_TIMEOUT_ARG,),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"run-{stem}-mt5-tick-by-fold",
            help=f"run {label} fold-isolated MT5 tick KPI and divergence workflow",
            kind="mt5_workflow",
            target=target(run.mt5_module, run.mt5_tick_by_fold_func),
            args=(MT5_TIMEOUT_ARG,),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"parse-{stem}-mt5",
            help=f"parse existing {label} MT5 output files",
            kind="parse_required_kpis",
            target=target(run.mt5_module, run.parse_func),
            args=(PARSE_MODE_ARG,),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"record-{stem}-parity",
            help=f"record {label} proxy-vs-MT5 logic parity",
            kind="record_required_kpis",
            target=target(run.mt5_module, run.parity_func),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            name=f"record-{stem}-execution-divergence",
            help=f"record {label} closed-bar-vs-tick execution divergence",
            kind="record_required_kpis",
            target=target(run.mt5_module, run.divergence_func),
        ),
    )


def build_commands() -> dict[str, CommandSpec]:
    commands: dict[str, CommandSpec] = {}
    add_command(commands, CommandSpec("status", "print key workspace paths as JSON", "status"))
    add_command(
        commands,
        CommandSpec(
            "export-mt5-max-bars",
            "fresh-export max MT5 bars",
            "export_mt5",
            target("axiom_rift.collectors.mt5_fresh_export", "run_terminal_export"),
            args=(
                arg("--symbol", default=None),
                arg("--timeframe", default=None),
                arg("--timeout-seconds", type=int, default=240),
            ),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            "build-us100-base-frame",
            "build US100 M5 base frame from raw CSV",
            "payload_json",
            target("axiom_rift.pipelines.base_frame", "build_us100_m5_base_frame"),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            "derive-us100-clean-periods",
            "derive clean period candidates",
            "payload_json",
            target("axiom_rift.pipelines.clean_periods", "derive_clean_periods"),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            "build-us100-rolling-windows",
            "build rolling-window split registry",
            "payload_json",
            target("axiom_rift.pipelines.rolling_windows", "build_rolling_windows"),
        ),
    )
    for run in RUN_SPECS:
        add_run_commands(commands, run)
    add_command(
        commands,
        CommandSpec(
            "validate-templates",
            "validate campaign templates and contract alignment",
            "validate_templates",
            target("axiom_rift.validation.work_units", "validate_templates"),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            "validate-repo-state",
            "validate whole-repository operating state",
            "validate_repo_state",
            target("axiom_rift.validation.repo_state", "validate_repo_state"),
        ),
    )
    add_command(
        commands,
        CommandSpec(
            "validate-work-unit",
            "validate a generated campaign work unit",
            "validate_work_unit",
            target("axiom_rift.validation.work_units", "validate_work_unit"),
            args=(arg("path", help="path such as campaigns/C0001_short_slug"),),
        ),
    )
    return commands


COMMANDS = build_commands()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    for spec in COMMANDS.values():
        command_parser = subparsers.add_parser(spec.name, help=spec.help)
        for argument in spec.args:
            command_parser.add_argument(*argument.flags, **argument.kwargs)
    return parser


def status_payload() -> dict[str, str]:
    paths: dict[str, Path] = {
        "project_root": PROJECT_ROOT,
        "configs": CONFIG_DIR,
        "contracts": CONTRACT_DIR,
        "campaigns": CAMPAIGN_DIR,
        "registries": REGISTRY_DIR,
        "claim_state": REGISTRY_DIR / "claim_state.yaml",
        "reentry": REGISTRY_DIR / "reentry.yaml",
    }
    return {key: value.as_posix() for key, value in paths.items()}


def resolve_target(target_path: str) -> Any:
    module_name, function_name = target_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_required_kpis(payload: dict[str, Any]) -> None:
    print_json(payload["required_kpis"])


def run_command(spec: CommandSpec, args: argparse.Namespace) -> int:
    if spec.kind == "status":
        print_json(status_payload())
        return 0
    if spec.target is None:
        raise RuntimeError(f"CLI command is missing a target: {spec.name}")
    command_func = resolve_target(spec.target)
    if spec.kind == "export_mt5":
        result = command_func(args.symbol, args.timeframe, timeout_seconds=args.timeout_seconds)
        print_json(
            {
                "raw_csv": result.raw_csv.as_posix(),
                "row_count": result.row_count,
                "first_time": result.first_time,
                "last_time": result.last_time,
                "sha256": result.sha256,
            }
        )
        return 0
    if spec.kind == "payload_json":
        print_json(command_func())
        return 0
    if spec.kind == "proxy_required_kpis":
        print_required_kpis(command_func(write=not args.dry_run))
        return 0
    if spec.kind == "compile_ea":
        result = command_func()
        print_json({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()})
        return 0
    if spec.kind == "mt5_workflow":
        print_json(command_func(timeout_seconds=args.timeout_seconds))
        return 0
    if spec.kind == "parse_required_kpis":
        print_required_kpis(command_func(mode=args.mode))
        return 0
    if spec.kind == "record_required_kpis":
        print_required_kpis(command_func())
        return 0
    if spec.kind == "validate_templates":
        result = command_func()
        print(resolve_target(RESULT_JSON_TARGET)(result))
        return 0 if result.ok else 1
    if spec.kind == "validate_repo_state":
        result = command_func()
        print(resolve_target(RESULT_JSON_TARGET)(result))
        return 0 if result.ok else 1
    if spec.kind == "validate_work_unit":
        result = command_func(Path(args.path))
        print(resolve_target(RESULT_JSON_TARGET)(result))
        return 0 if result.ok else 1
    raise RuntimeError(f"Unsupported CLI command kind: {spec.kind}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return run_command(COMMANDS[args.command], args)


if __name__ == "__main__":
    raise SystemExit(main())
