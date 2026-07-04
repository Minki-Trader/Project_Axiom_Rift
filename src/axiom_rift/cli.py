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
