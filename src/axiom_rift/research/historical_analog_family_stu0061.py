"""Frozen analog-family compatibility binding for historical STU-0061.

Prospective code must derive this shape from a Writer-authenticated
``HistoricalFamilySpec`` instead of importing this reconstruction module.
"""

from axiom_rift.research.analog_state_family import (
    MULTISCALE_STATE_FEATURE_PROTOCOL,
    RETURN_ONLY_FEATURE_PROTOCOL,
    AnalogFamilySpec,
    AnalogProfileSpec,
)


STU0061_ANALOG_FAMILY = AnalogFamilySpec(
    family_id="family:stu0061-analog-state-h24-n25-replay-v1",
    horizon=24,
    library_stride=12,
    neighbors=25,
    profiles=(
        AnalogProfileSpec(
            profile_id="knn_multiscale_state_25",
            feature_protocol=MULTISCALE_STATE_FEATURE_PROTOCOL,
            positive_historical_reference_executable_id=(
                "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463"
            ),
            negative_historical_reference_executable_id=(
                "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7"
            ),
        ),
        AnalogProfileSpec(
            profile_id="knn_return_control_25",
            feature_protocol=RETURN_ONLY_FEATURE_PROTOCOL,
            positive_historical_reference_executable_id=(
                "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df"
            ),
            negative_historical_reference_executable_id=(
                "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8"
            ),
        ),
    ),
    selector_quantile_bp=8_500,
)


__all__ = ["STU0061_ANALOG_FAMILY"]
