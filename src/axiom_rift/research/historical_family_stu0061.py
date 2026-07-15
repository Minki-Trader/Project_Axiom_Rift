"""Exact original-family authority binding for historical STU-0061."""

from axiom_rift.research.historical_family_replay import (
    ControlBinding,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)


_MULTISCALE_POSITIVE = (
    "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463"
)
_MULTISCALE_NEGATIVE = (
    "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7"
)
_RETURN_POSITIVE = (
    "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df"
)
_RETURN_NEGATIVE = (
    "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8"
)


def _member(
    ordinal: int,
    configuration_id: str,
    historical_reference_executable_id: str,
    *,
    profile: str,
    signal_sign: int,
) -> HistoricalMemberSpec:
    return HistoricalMemberSpec(
        ordinal=ordinal,
        configuration_id=configuration_id,
        historical_reference_executable_id=(
            historical_reference_executable_id
        ),
        parameters={
            "family_id": "family:stu0061-analog-state-h24-n25-replay-v1",
            "holding_bars": 24,
            "library_stride": 12,
            "neighbors": 25,
            "profile": profile,
            "selector_quantile_bp": 8_500,
            "signal_sign": signal_sign,
        },
    )


def _control(
    subject: str,
    opposite: str,
    feature: str,
) -> ControlBinding:
    return ControlBinding(
        subject_historical_executable_id=subject,
        opposite_historical_executable_id=opposite,
        feature_historical_executable_ids=(feature,),
    )


STU0061_HISTORICAL_FAMILY = HistoricalFamilySpec(
    original_study_id="STU-0061",
    original_batch_id=(
        "batch:90a31a1906e681d0758a26aec0c21815481c3cfb31c8be5400ef02bff5902123"
    ),
    target_historical_executable_id=_RETURN_NEGATIVE,
    members=(
        _member(
            1,
            "knn_multiscale_state_25-analog-h24",
            _MULTISCALE_POSITIVE,
            profile="knn_multiscale_state_25",
            signal_sign=1,
        ),
        _member(
            2,
            "knn_multiscale_state_25-inverse-h24",
            _MULTISCALE_NEGATIVE,
            profile="knn_multiscale_state_25",
            signal_sign=-1,
        ),
        _member(
            3,
            "knn_return_control_25-analog-h24",
            _RETURN_POSITIVE,
            profile="knn_return_control_25",
            signal_sign=1,
        ),
        _member(
            4,
            "knn_return_control_25-inverse-h24",
            _RETURN_NEGATIVE,
            profile="knn_return_control_25",
            signal_sign=-1,
        ),
    ),
    controls=(
        _control(
            _MULTISCALE_POSITIVE,
            _MULTISCALE_NEGATIVE,
            _RETURN_POSITIVE,
        ),
        _control(
            _MULTISCALE_NEGATIVE,
            _MULTISCALE_POSITIVE,
            _RETURN_NEGATIVE,
        ),
        _control(
            _RETURN_POSITIVE,
            _RETURN_NEGATIVE,
            _MULTISCALE_POSITIVE,
        ),
        _control(
            _RETURN_NEGATIVE,
            _RETURN_POSITIVE,
            _MULTISCALE_NEGATIVE,
        ),
    ),
)


__all__ = ["STU0061_HISTORICAL_FAMILY"]
