# Spread Time Semantics And Historical Validity Audit

date: 2026-07-16
status: causal_inventory_complete_repairs_in_progress
scope: repository_history_code_authority_scientific_completions_and_replay
history_boundary: f959ca5d18098f7a47f112ccd6a2641a0d849963
control_boundary: sequence_5385
holdout_value_reads: 0
quarantine_value_reads: 0
ignored_repository_index_reads: 0

## Method And Authority Boundary

The historical inventory was derived from the immutable Journal through the
authenticated read-only authoritative index. The tracked source and authority
review used the committed history boundary above. Uncommitted prospective
repairs were classified separately and never used to alter historical facts.
Protected data, quarantine values, holdout values, and the ignored repository
index were not opened.

Primary platform references:

- https://www.mql5.com/en/docs/constants/structures/mqlrates
- https://www.mql5.com/en/docs/series/copyrates
- https://www.mql5.com/en/docs/series/copyticksrange
- https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py

MqlRates exposes one spread field on a period bar and CopyRates identifies the
bar by its period start. Neither reference grants authority to interpret that
field as the bid-ask quote at the bar open or before an order within the same
bar. CopyTicksRange exposes timestamped bid and ask observations. The project
therefore makes the fail-closed inference that MqlRates spread is available as
a completed-period observation only; a historical point-in-time quote requires
timestamped bid-ask, tick, order, deal, or execution-receipt evidence.

## Bound Findings

- AX-SPREAD-TIME-001:
  reason decision_input_point_in_time_unproven
  field MqlRates.spread
  prohibited use same_scheduled_or_deferred_entry_bar_order_decision
  affected scientific completion count 34
  affected Study contexts STU-0046 STU-0047 STU-0048 STU-0049 STU-0050 STU-0051 STU-0070 STU-0071 STU-0101 STU-0107 STU-0108
  STU-0046 executable:7af6e5bc53cc96315fb9db9652fda221243188e6ec00209e21180341b51bd536 completion 1b08305e8dd61d949e0da83cd605a754497fa23d0ca31404b2d8da33b4f65987
  STU-0046 executable:a5223063c1cbaad273fa6a88ce986c89f05d6f8dad6ab059fb8e0052e4228afa completion 1e27ee01a1463867bb7fbc51e75207f68d0974e80b859edc1b897531de3e53ab
  STU-0046 executable:109b5e7e865a5c6bf0fffb5ab8aec17d01cfa6805368545ead58537676c2b903 completion 3e9be3c9ee275086057cada682ff4972320aa696f3d980a2b7b273854aa5a86a
  STU-0046 executable:66b951f0a1dd61396d5c350ba4d471914b6ebcebb4dcefd5777520fb0f47a335 completion d3f37c9f6e8c050636d65f435483f81ff12b3e83d0f33d0610c2985590bf0865
  STU-0047 executable:32c20b02cefee954338c0aa8e59562ff3e2c774ac07145a2d326e85546fa79bd completion 052b500f8c15977f81eaaf4b576f4931332bf20dc9efba0e02ca0ae8f59555f8
  STU-0047 executable:f33b5130bff13c97b76a376480115a8e5d4efabfbc1dec519cbe3ff73298e360 completion 0cb2d6613ff011a2261bf9d72d72b249207c295c35f255cceba5e030b7aab8eb
  STU-0047 executable:7d6965fae41cf40d73dab95cb11e2c62f26962610c6814b4fcb9337d52a0ba0f completion 5db9989132c98e59e1a50846b3e154915ba7abcc5bfb4aaf50f2dce3babd46d4
  STU-0047 executable:cc0ec384262e15cd42da33ead9d2ac58b9a41083e355333924ecf0f9bab7badc completion bb7a48ef9c57db1470e6666e4fe0582ac0fcfedaa2f4b3b640724375dcf9ad5e
  STU-0048 executable:4c6b58e03685bcca2037eb0f4731305d94423b00b7adb5ab54f99e147e645ab5 completion 22c2fd40ad0402e853e241c6a11de4b2b7d48dfc08f22ce3de3ba475e1e1c7df
  STU-0048 executable:4b203b0f0eb4e1e12b59f2baafe7e83202b866bc90f0034ad48cf0989bcaa09c completion 446b9dd0ab77ab07de189219c22b8ba415017c35708fa5d6235abb33baf66937
  STU-0048 executable:672b5ce2ab8bd5419b49b9b09db271f8d51ba2c1fb14057112ce180306f226ed completion 79093acbbaef954af968025dc880ef4a45551d434fa531da5a97c74e9d9b2bd2
  STU-0048 executable:032ba71324366292953787e1fa79378274dcb99d9d8dcfe2825738969a6ebf2b completion 9765f44d5c872bcba69cd3838b0758e7978720e3926cadd78e91d42e020eb1d8
  STU-0049 executable:5ddc970ceaf451377f49c3bf17f7b2b026175381cf28c2d375ec966a8c5f90a4 completion 042dd7f36d8c9ce736aaed5bf60e51587fbdc9b5390cff555d98cf03c8b8cc20
  STU-0049 executable:3ff3f7bbbed7193984a3d3a94fdd11e3c5849256a2b8d0b953a3813894e44318 completion 3253b3bdb53cd8f616d518c26b4878b6a9baa19e4b1e5667658e9d2c9e0f6b07
  STU-0049 executable:fb58cdf8f6fabff38deb72cb4c089fd759b0abb7bfe37ea74b7415caae83a26e completion 73bcc20c962cef7416c6103ece2fc2e15032dcf6bd4ba0525306f89396d8d463
  STU-0049 executable:72eb24bf5f73a141d193fc23b4f12023d98e600fbe4bdb08efdb490d6c962396 completion ec5c6c588d444c227cd5771b6bdf9ac4b9a7ac96181f7037322ef25abc987d63
  STU-0050 executable:ab0e239807092e4d499788651ec8ab222330165c9d52df8f76570f34f777b2a6 completion 0ba922d930f76fe9a38cb07644a488ee735608ecffc7e257e441b02883c63032
  STU-0050 executable:88ea5f16e0a92c9aeacc160bf899013fee1061af2d700aa61f062b07afb0a095 completion 0cdd5aa1ee1aac2ac38a37a28ccb4f7ed02293ee52f10f85f09a84435a7fe348
  STU-0050 executable:f1171e5747b2c95c0f20a45cf1274fc4d39a8c0e5914c5b5706c87941a6e1af3 completion 582b58fa7e3307810f361cb4f9a1e44b7abc3a5f36c1149dc5fea77a72cdb588
  STU-0050 executable:2a0751ab91e0aeb0dc3f07d4c8890cf019ff1698cac3377218e3976fc3e945a5 completion ee301c9a3fdebbc0acb3120694437164cf677bf26eb45252db56be4e77676443
  STU-0051 executable:43bce7d49399848c5fe2a7de0351417a8832b6a004105fafed538743fa2977a9 completion 731e78ec1fa83c667d0370d600de6b4ced384cde60499fa47f07f04c81047d03
  STU-0051 executable:d07169b4d76bc6a449951b3e2c9fc178f2c52029b80fcaedad200d497848b6f9 completion cbadcc0ef76b06b5754572c9beed8f9aae036a7fcc99f4531100ddd44ecca32b
  STU-0051 executable:ff53b8828db4e61c1fbdfaccf84d7d8b3493c2e796e19cd1fddf50bb23e94137 completion e06b4c91ae469ebca10c009df0d39821f2d12ce03f25de57bce9099b99e13f8c
  STU-0051 executable:05a4320996e315a57eea1c37c542c1d87b23b003a86167526544ea50e7f27bf2 completion f4d20c3358fc7dd535050917b6775f549f5495610f05923502cbfab993a66464
  STU-0071 executable:33ad1cd7b5eabe24d65fad22be9757826a19fa20f6a2e16f871c6ff32a68a9d3 completion ac28e7085040b2a2ccf322479ff7fb2489ffc35fd39841d137c4742256459e3c
  STU-0101 executable:eb5ecdeddedfd5028fdb194c88517109b4495af86afb8c90115f0f01d3becced completion 0e396a98308e99792591ad8dd1b80b8ce26c69825bb68e00606173dda7a6d3f8
  STU-0107 executable:c8b62dac5ef859ee2db6e6adbdcc758384867811174e5be3a765da904db4dcaf completion 22bb311ac594f45b09e7b415bded67e8ea538774ebc30b599ad82aec6798ee89
  STU-0107 executable:51193460ecf100b1c0053ebf87acc5197928d01e7c28385d3d39770cbe6977bc completion 5c310f460fffd7c4860b314803a8d097ff701a6dcf797d8fe68849a6aca717ec
  STU-0107 executable:93c03f0a5d8545cafc53fbfcbcb7791ac0ac27175b2a05e26947281f09fe81d1 completion b818329c02cd39132c9364e9851c79bd9b5dfcd085f866fccd59153f4d7bca7c
  STU-0107 executable:0fc036a7825f29ca2aca8129855c4315e4b81cfa894330afe2d899b2c3b42762 completion cd7e66658754e052cf0dbef8296d3fddcdd2a05ceefaeea55eea56088e5ef2ec
  STU-0108 executable:d8f54d95a5a630377d9a82f7c2801d362008304d1e3096e1fb3117966799d905 completion 2cd40c38e0ad9b12c30e4924d5e00c83c72c38c8a557c2905f86d5647ed73e98
  STU-0108 executable:eabf4c41722ac77fadccff0b669be9e9226cd250fd911878c8d594b7acbc7990 completion 333cf1f646f57f6c22c04d8b636632895038cdce6eafe4dd5b98bf2681c435f2
  STU-0108 executable:3a90958f5e1dca92bf61f7ed5abd0375ce1c15c8cab161512ffb480b37f0f915 completion 57874787f16c8bce535c5053abc0e8715657b59ff29b6a85519bedf08bb4f5d0
  STU-0108 executable:8392b61ce0b248381ac51be7975cacb75d7d74467b0903393656cbc2491f88e4 completion 73ffa93885fbbaf01aedd50249967de8cd8bce39c78a34ac1d697b393055c949

- AX-SPREAD-TIME-002:
  STU-0107 obligation historical-replay-obligation:c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e
  STU-0107 satisfaction historical-replay-satisfaction:6a0d460befc957bad4cb250fdc1a0cb3a74fd7c00ed5643e93f7fc60a59790d4
  STU-0108 obligation historical-replay-obligation:a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904
  STU-0108 satisfaction historical-replay-satisfaction:6b59a863de2e5f4833ae7dd6786423c7b1642b4c741db1bc10e8357648fdda2f
  affected criterion C03-decision-time-causality
  claimed satisfied criterion count 20
  exact source index transitions 415914_to_415915 and 415915_to_415916
  STU-0107 atomic traces 0191f8749af87345028bd9e6f47fbd960fc43a79b8e60fdfc9dd87152cccd40c e44af5f127f28c7dd015a9141f26b3fe0612d9f780a615f9d9b4a5481200223e 15da44a2a9cacea0142d33eab9e2239a9c9642b90173662f83d500f403731e61 0d0cf2d1f593223139d75b7818426908f4fd5c363e904b88e504ac800ad917de
  STU-0108 atomic traces 4d27f016bc0e2db1f669f37eb837612d37369846a6e85c8e59bf61dbea15f874 d9038175a6b1c29ca91afc270cab8e4da0d1583bdb959d307389938585cc301d a06edb036a127764d7e22fb0c4ceca00e5dae484e419b0fa4d6ff3a1ee58ca09 9042c8095c2522e94844717fba6e1472ab84180c09569b6b033e27cce21eea5e
  observed branch entry_cancelled_unknown_cost
  each stored family trace contains 8 full_or_prefix rows representing 4 distinct events

- AX-SPREAD-COST-001:
  spread cost Study operation count 104
  causal invalid A Study context count 11
  proxy-only B Study operation count 93
  proxy-only B completion count 501
  proxy-only B scientific completion count 488
  proxy-only B engineering completion count 13
  proxy-only B negative memory count 438
  proxy-only B historical adjudication count 444
  authority Git head f959ca5d18098f7a47f112ccd6a2641a0d849963
  authority Journal sequence 5385
  authority Journal event 6b47964a60a8490e76ce921945071f282be61334e27706093bd51469ae519f65
  Study operation inventory digest 03309a5846e1df2d353247d2d1030e52a6c3fbc9f4298e74d31924850d359394
  completion inventory digest 6da1d79ad925b596f18d5ef2f42ecdeaa8c83fa4c0baf032968bcdc64b0b9a33
  scientific completion inventory digest f406cd94f82581367a7f52851e63e5799c9e81c8f7343b0e307051447fb501f9
  scientific Executable inventory digest 68cebe34170a1a185c5ff2acd787f343c0d85c1fbcfb6e442bb183c4328b8162
  adjudication inventory digest 12fd4a6947abd880cca8f81e1ff46bea9b64b47fc93cdbb72e7be0779527c6af
  negative memory inventory digest 4e8965d5a2e1b76f16b3520d6812d8bff5b712f9fafb4d02c3cb127e811b1de4
  execution_cost_measurement_only scientific completion count 437
  completed_period_proxy_feature scientific completion count 8
  native_cost_outcome_label_only scientific completion count 36
  decision_surface_cost_dependent scientific completion count 6
  causal_policy_cost_state_dependent scientific completion count 1
  exact proxy state retained criteria C01 C02 C05
  actual cost unresolved criteria A01 A02 A03 A04 B01 B02 B03 C03 C04 D01 D02 D03 D04 E01 F01 F02 F03
  diagnostic criterion B04
  STU-0073 STU-0083 cross-Study duplicate Executable completion join required
  STU-0103 STU-0104 engineering-to-scientific Executable reuse join required
  permitted historical interpretation completed_period_bar_spread_proxy
  forbidden historical interpretation actual_point_in_time_native_quote
  direct review required after_cost_fixed_lot_economics activity control selection temporal_regime
  independently preservable scopes gross_mechanism feature_causality

- AX-SPREAD-NONAFFECTED-001:
  STU-0036 and STU-0037 completed decision-bar liquidity feature is causal
  their execution cost result remains within AX-SPREAD-COST-001 proxy scope
  prior-reference shift one is causal
  data and schema carrier files are not scientific invalidations
  immutable Journal records are preserved and corrected additively

## Required Correction Semantics

All 34 AX-SPREAD-TIME-001 scientific completions lose effective scientific,
economic, candidate, and terminal credit. Their immutable records remain. The
26 associated negative memories remain as diagnostic history but cannot prune
or close an axis. STU-0101 retains its existing source invalidation and gains a
union-monotone timing invalidation. The two AX-SPREAD-TIME-002 satisfactions
remain immutable while their obligation heads return to pending.

The B inventory is not blanket-invalidated. Completed-period proxy economics
must be labeled as such. Actual-cost-dependent claims become unresolved until
timestamped quote or execution evidence exists, while independent gross and
causal evidence remains available. Completion membership is derived through
completion to Job declaration evidence subject to Trial, never from the Trial
Study label. The semantic qualification is one frozen-head class latch rather
than 488 caller-authored overlays; it excludes future completions and cannot
restore authority removed by timing or source invalidations. A corrected replay
or new Study uses only a
completed decision bar and strictly prior reference bars for decisions, freezes
any delayed-entry decision, and binds exact cost source indices in its atomic
trace.

The latch is not a documentary label. Current completion, claim, negative-
memory, axis-disposition, Portfolio, architecture, exhaustion, and terminal
readers must consume its authenticated effective qualification. An affected
historical prune whose negative authority depended on actual-cost meaning
becomes deferred pending an explicit reopen or independent re-establishment;
independent gross-mechanism and feature-causality scopes remain available.
Routine reads use exact completion and negative-memory keys and must not repeat
the complete 501-completion audit scan per axis or Decision.

## Close Condition

This audit closes only after prospective code and trace validation pass,
authority migration activates the new semantics, exact completion validity
heads are recorded, historical adjudications are superseded, both replay
satisfactions are revoked, corrected replay Studies are diagnosed, and a
second exhaustive audit finds no remaining time-semantics bypass.
