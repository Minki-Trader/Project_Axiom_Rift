"""Frozen legacy modules that are evidence history, never prospective engines."""

from __future__ import annotations


# These byte identities preserve historical reconstruction.  StateWriter
# rejects them as ordinary new Job implementation evidence because their
# source contains a concrete Mission or Study id.  Exact replay adapters may
# use them only through Writer-verified historical replay-obligation lineage;
# unrelated new research must use a context-bound reusable engine.
HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256 = {
    "adaptive_lifecycle_study.py": "849ea7a8b303520f36a09b6b9a8f8153d7e63c40e417f5796f08798046aa653f",
    "analog_state_scoped_job.py": "523b02edfefff8215ed74efb0f2711edcabef12ed942ba4619d5e41a709857ab",
    "auction_location_study.py": "361c47db2a6f2a20a6d6db10655ce723633c145307dcd5ea750810c98fb06a7d",
    "candle_geometry_study.py": "131cdd42ba2bef07615ab1647238ac69881be1d9e8961ca993c94d567fadade5",
    "complementary_sleeve_discovery.py": "c4d87805eaf1ebcdab8c5b6e7962ef9846aaaec00eb88c731372a0bdd36103de",
    "complementary_sleeve_study.py": "60eca5ea68dcb5e5e5b448285070af11de93bd2c32fe03d09b1e89517335b290",
    "composite_consensus_study.py": "f1a7d86d443f0a1433c2d24de3e1fd4f19bab4bfd39a38294fdccb99323916cd",
    "composite_consensus_replay_job.py": "5eb2475eafe1fbff0af3264d906b6eb735df5814db8e0f897c83866467f4282e",
    "composite_router_replay_job.py": "1a7dae31ae4c3bcaf316bfcc867103e8c68d271e9f11afa1b401024557a3f0b2",
    "composite_router_study.py": "bd0c8640de4d0524ff4199263ba09f3f1eeb0d62a3a68e58dce2c13d8dbd3a97",
    "cost_utility_objective_discovery.py": "0bb11e328d81c76f58756da5583e46aa8f7708f300d3412a9805c8a73cb53f27",
    "cost_utility_objective_study.py": "f1ecf8abfe14d03da8d09d25c81c421d127d25743ce60096aeb8a7d5828b69f2",
    "cross_asset_downside_spillover_study.py": "2e1b641bb0a2ac419542b5fc22a02ab4787d08fbbe05731f119b5a495f79d4ab",
    "cross_asset_relative_strength_study.py": "e7de3e310d0c612929611f57aec76a65f1b3e8f93fd4d40d172c2db1f5b95739",
    "cyclical_harmonic_study.py": "559e3f0f0d7cb621db2e467c7ba1dae37bca37bcde8837a7a7b47369ec64de17",
    "cyclical_phase_study.py": "b3f08cf644409264059217690778705c2090625aef68d1a18072609cdea2c005",
    "distribution_study.py": "5234bf7706b5bfa9ffffc9ebe2f9b13a5dafb01857a9322c48ee1bc2801e1d80",
    "distribution_asymmetry_replay.py": "00dfba3fb158baf356a65937657feb80c5b3dd37b3ec880c309903b653be52a0",
    "distribution_asymmetry_replay_parity.py": "ea56e6ad22368a43b5e6d89ae953499add0428b3e31ed6ed23685573ffa6f3ee",
    "drawdown_state_study.py": "3326b8321118f03fc691246871ed451e482868b55d85691bb41182f6c2767700",
    "event_label_study.py": "99c6db5894881861dc595e31e884dcc8fee1c6c0465aeee18895bd6f41853379",
    "gap_recovery_diagnostic.py": "f48a8fac46e386b870e643d0df840aade5d636f0521ae730a9fe67c1c9186572",
    "gap_recovery_study.py": "4ea4c294cef4c6a47f0e6f13c64d076e7ec2a60b2e21067c720c75f141422727",
    "higher_order_volatility_study.py": "24c34397aa413791746199f0616d587e1a24478b0331944d2cc813a5295dfc18",
    "historical_analog_family_stu0061.py": "53a286354493b758225448c2d282c104544a23d7d9c7a018605731e82311b522",
    "historical_family_stu0016.py": "5373371cbda260657ec38f2be45f71759c2d5b66ab1e53d1776e9352e50c8e1f",
    "historical_family_stu0017.py": "2f179b35ff70c706a9ce155a40f90c8f9b86dd20e855825482e22deecd08c0fb",
    "historical_family_stu0032.py": "9230ecd8cdfe4e5abf0051f63448b29d10e189ea28f527a4cd7dfc6baefa5a6e",
    "historical_family_stu0048.py": "ffa6af9f93b7598f668b4385caed85af08c7e4fc5b77cd6dc0f16fe0c322435b",
    "historical_family_stu0051.py": "803936b35a1b36639351d85931f9cfd1c6d58d708d371bf7c2080c994c37e68a",
    "historical_family_stu0061.py": "215282cdc5a63d11d248817be5dc0e807aa3d882429625e71ba33099ca073ee4",
    "learned_state_study.py": "26ee72e7b13a36b69310c07996d62346e0471dc590c6fa706048940becf1f44b",
    "liquidity_supply_study.py": "a8ba1eee234e47aabff939b473fde0d7425a7dfd9d68b9144c3f521f64f9770f",
    "long_horizon_drift_study.py": "086bbab722a2f9d218818c1657d676e18f6a707b0b4b7f1b42776e976f10bc8c",
    "nonlinear_interaction_study.py": "21f0a4fe3e80476dda4e274a88cedfed0d910035049a7adc3ebc3f345fb72101",
    "ordinal_transition_study.py": "e9a46759c8a163b78f70764bfd0c94e65026c7f0c748ec1a25d5c253a7763e12",
    "path_efficiency_study.py": "91e1b62710c1be14ba5cb5621aa3dd8c96a613173484d6ca9d0d4f98755b9ebb",
    "path_roughness_study.py": "05da593566b6932c8fdd2c50556524b8478a8d482f7f242c8ff99a18540aeb8f",
    "post_break_study.py": "73d6b72166aac93891251322ff945b97a544ed3f1cea5db2ce4cc719daf8b32c",
    "price_level_study.py": "01b6f7bcc29f5fa187fb79afb9fe9fc12cfb05b9a17c608e2aeb38aa11035b2f",
    "probability_calibration_discovery.py": "9f72e8db87f13b5debca8c4d631f2bf5e44a52b167e0eec733ddc6d2f77d8cde",
    "probability_calibration_study.py": "b1508be35dcac4872399ed26222ba48ef028120b67ffce0917d22c87add458b1",
    "rank_bin_calibration_discovery.py": "03b4b8d653dcf97ce2dba7005ff7a0dc323143becad1ac6202004aa6787fda27",
    "rank_bin_calibration_study.py": "907c7e682c03ec74b5403ca1d8874d19c7e3f565ecc831a4f79f682931828693",
    "reversion_regime_followup_study.py": "1964f904928b0b20738b8c1e7faa27cfba6da97f0337ccb1658e084566803948",
    "reversion_study.py": "354f3b81099bd2dc6a04cb4e2484c7e0856ec660ccf50200e025b4ec5364149c",
    "session_inventory_final_study.py": "185b26ae4237ef4cb99f3d644eeb41a3f359a5f05c064f9360366b95dcc126ff",
    "session_inventory_followup_final_study.py": "bb77697ebbba08e94e002253646282398af392dd41a693c2946cc858877dafa9",
    "session_inventory_followup_study.py": "1da8989b4be53a830b1665496356b2098dc05f239217c354f5df4a65ef5bd89c",
    "session_inventory_followup_terminal_study.py": "a9e5cf7912f260c33de2c33cef93a618978202255b11e45e9f269386e3daa56f",
    "session_inventory_retry_study.py": "60d57824276cb8658652b82cdb8b89c1c72bb27381b65f1d1900d5a48fceec93",
    "session_inventory_study.py": "92805b59dcac3aa6e4119f8892936d783679086c4c330e90056516742109969b",
    "shock_aftereffect_study.py": "0ca7ede8c3662a5e876096de3d73e421c7cdfa24cc006628c3ca300f6824ca8c",
    "shock_cluster_study.py": "fd600555c841d54e6883c8bab6d6d1513846ff92a1740a4f6a0177936d03038a",
    "shock_level_interaction_study.py": "921ace551588e6c6c909694f8efe53b5ba2a2c710e0f7ba292d229f720033f62",
    "structural_break_study.py": "ff0bc80b417ff80eef20f53b31808407f14833398d24e817008bb9b8e99b410d",
    "transition_mixture_study.py": "af7540b060d37316243a5ae001e8b5a10db90d4fb09f788ff5946034b9e9f2b2",
    "trend_null_followup_study.py": "4ed50eb7701b5f033030d824ff8d11325f5656058a9bec87a824a9389575949f",
    "trend_study.py": "3061c20e45235d0010133694c3886e50fc1bc5ec5d489a68478437cf343198c4",
    "volatility_duration_study.py": "d09274881af55e3ce582d56c38ae5424a688014dfdc5e3ef80cec05bf3abd399",
    "volatility_duration_replay.py": "0012c37f185120856f46f77c6e97155a192a9475b83cd82dbcfc8ad6402a8aa5",
    "volatility_duration_replay_job.py": "c44e307fd79acf07fde8cfdd8b325940a52f6a57383f58ea8b140e3e70490c1a",
    "volatility_duration_replay_parity.py": "378d4eab967aeb0f87b29fbe0d0bbe227515cd29efe343b752c219d74d6df135",
    "volatility_regime_followup_study.py": "f1e498eaac56a364a4b30f5f6148448e1b4a53313fc3b33adf7f3b5c581a8aa9",
    "volatility_study.py": "a3b8d02306dcfd486a760d6b141e38cb8d4738c6ecf51da61bd260597180f8c3",
    "volume_price_followup_study.py": "472c27b8e5060b83732f8f0deb39248466fb19fde69fd082f59e682670390a8f",
    "volume_price_study.py": "503087552b839948e2e27cff4a52ddfba6f31a2cb1796626b987b8201e7dea3d",
}

HISTORICAL_FAMILY_IDENTITY_BY_MODULE = {
    "historical_family_stu0016.py": (
        "historical-family:"
        "6d3187af024d51b75af134afcffd5db6f84d221fab2cfe4f60b580d71d3ba24a"
    ),
    "historical_family_stu0017.py": (
        "historical-family:"
        "f63945aff1ca219edd4e56ae15295bc489eec50a37ab67d21d788107a9990e48"
    ),
    "historical_family_stu0032.py": (
        "historical-family:"
        "b3e2e15c99781ce0cda56e6468392e227be2d33920658b06ee185db111c5425b"
    ),
    "historical_family_stu0048.py": (
        "historical-family:"
        "445e7a4d8b56830491a4833260d808500537b0cd6b00fd4f8ed985f2d2f3c92e"
    ),
    "historical_family_stu0051.py": (
        "historical-family:"
        "cf3eb75283e4657eea250f993ad0379d719020d3611031177822ab1f83994ea2"
    ),
    "historical_family_stu0061.py": (
        "historical-family:"
        "9b7d57e66deb6d570a1e352fb2354873a4c1ab71cb09643410f74b0f68af102f"
    ),
}


__all__ = [
    "HISTORICAL_FAMILY_IDENTITY_BY_MODULE",
    "HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256",
]
