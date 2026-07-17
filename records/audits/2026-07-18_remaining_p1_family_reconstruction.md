# Remaining P1 Historical Family Reconstruction

Date: 2026-07-18
Mission: MIS-0006
Initiative: INI-0025
Scope: admission authority only; no scientific or scheduler credit

## Finding

After sibling recertification, sixteen of the seventeen pending P1 obligations
belong to four complete historical four-member Batches. Their trial order,
Executable manifests, feature/sign controls, original Study and Batch identity,
and frozen source semantics are available in the authenticated Journal
projection. They lacked target-specific HistoricalFamilyAuthority only because
the earlier correction admitted a small hard-coded family subset.

Serially reconstructing authority immediately before each Study would add
avoidable scheduler churn and could again encourage one-family-per-obligation
execution. The repaired contract instead admits every exact pending-member
authority in one zero-credit Writer event, after which each four-obligation
family can be selected and run once.

## Exact Families

- STU-0046 / batch dc34ce62: four gap-event members, holding 12 bars.
- STU-0047 / batch ac8964c2: four post-gap-path members, holding 6 bars.
- STU-0049 / batch 0ba42986: four drawdown interaction members, holding 12 bars.
- STU-0050 / batch a1ef094c: four volatility-duration members, holding 12 bars.

Each family is a complete two-feature by two-sign surface. For every member,
the opposite-sign member of the same feature is the opposite control and the
same-sign member of the other feature is the feature control.

## Target-Specific Authorities

- 159a5993 -> historical-family-authority:3e516ad3d0eded0868140717708ab719e862a54c90c1155cd9ef0bc1f87c7e95
- 2580acb5 -> historical-family-authority:49cf22ebbb0aacfb8a95b8a844cd81ae9c56a52f608e800684a3ae9d7fb8247d
- 9bbcca01 -> historical-family-authority:72ac28a5d7aca3baa48722e938499ec3282db3a59702d1c11a3d1dc455ea5ee9
- 9e01b7b2 -> historical-family-authority:0ba4b3572cf9c40d2e93b8bf7b34cf3ade0d53b1f194d5a3440c14605ffbd37e
- 671cfce2 -> historical-family-authority:10d8f52e164b019d5d5d75c6a66e6f0ec5241ec2e8eab8450142c4395fbfbeb0
- be4867b5 -> historical-family-authority:8d1929c8966fa6886a249199358dc138f7dec5e4d7256c7b0e9c11a1892408bb
- c9fb9597 -> historical-family-authority:25aba45822fa44dd45ee8663f1113c2ff8c6bd2cd737d81f3802a90007358c56
- d6926257 -> historical-family-authority:c58bf23ba6ac95a9fe5c9283d2d4bb2fe4334a661147ecf50ab0a153afb6e5d1
- 2e10d2ca -> historical-family-authority:de86e21862f2c8c4854fc5b08022db50aa3f995544ffab3e9d1c4578579c8fea
- 60f4c9cf -> historical-family-authority:14c887e4171a4be0d0ed31c4d428081396bedfd9160a57728229b349711362ab
- c2474c4b -> historical-family-authority:d6b96beb77ed02c7a6447579d57c415db5f6de395f088056922edc91dd67771e
- e267830f -> historical-family-authority:4878dcc4f84cd8c4808613fcd2207229703a297b927e69d50f858f28d819678e
- 17e4b86d -> historical-family-authority:f71a63008c0428c4d01017d955b287794485033be094829447cf703864888514
- 9d06939d -> historical-family-authority:44927666c0aab94fcb8fe02a3c8d65787d76b3badc4fcd1462d3b705ec4d2a34
- a635a464 -> historical-family-authority:d8f18b31702054bd2aed55d9550af168a5c74e8994bc120e9b2b73059f3ce5d5
- ac58c5a2 -> historical-family-authority:f7ae433a5b7fdcb52ae68e85717bdf932f5a84355723e7889696fa64267efe87

The short left-hand values are unambiguous prefixes of the exact pending
ReplayObligation identities recorded in revision 5491.

## Proof And Limits

The authenticated stable index admitted all sixteen proposed authority records
through `prepare_historical_family_authority_record`. This rechecked current
pending heads, source bytes, registry identity, original Study and Batch,
four-trial order, every historical Executable identity and parameter, and the
family controls. Focused family and authority tests passed 39 of 39.

Registration must leave revision science and scheduling unchanged except for
the additive authority records: pending remains 17, trial remains 620,
candidate and holdout remain zero, and next action remains `portfolio_decision`.
This audit does not claim that any of the sixteen obligations is scientifically
satisfied; their four families still require prospective execution.
