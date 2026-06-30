# Config

schema: axiom_rift_config_dir_v2
status: pending_active_config
active_truth_dir: true
encoding: ascii_only

files:
  market: configs/market.yaml
  paths: configs/paths.yaml
  runtime: configs/runtime.yaml

rules:
  - active_axiom_config_goes_here
  - archived_fpmarkets_v2_config_is_not_active_truth
  - runtime_claims_require_active_axiom_runtime_config

archive_reference_dir: archive/imported_fpmarkets_v2_delete_after_axiom_contracts/foundation/config
