"""Native quaternion convention and derived chassis vectors."""

from __future__ import annotations

import math

import pytest

from app.processing.orientation import chassis_forward, chassis_up, normalize_quaternion, slerp


def test_identity_uses_local_negative_z_as_chassis_nose() -> None:
    assert chassis_forward((0.0, 0.0, 0.0, 1.0)) == pytest.approx((0.0, 0.0, -1.0))
    assert chassis_up((0.0, 0.0, 0.0, 1.0)) == pytest.approx((0.0, 1.0, 0.0))


def test_world_positive_x_heading_and_quaternion_sign_equivalence() -> None:
    half = math.sqrt(0.5)
    quaternion = (0.0, -half, 0.0, half)
    assert chassis_forward(quaternion) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert chassis_forward(tuple(-value for value in quaternion)) == pytest.approx(
        (1.0, 0.0, 0.0), abs=1e-6
    )
    midpoint = slerp(quaternion, tuple(-value for value in quaternion), 0.5)
    assert midpoint is not None
    assert chassis_forward(midpoint) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)


@pytest.mark.parametrize(
    "values",
    [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0, 1.0),
        (math.nan, 0.0, 0.0, 1.0),
        (math.inf, 0.0, 0.0, 1.0),
    ],
)
def test_invalid_orientation_is_not_normalized(values: tuple[float, ...]) -> None:
    assert normalize_quaternion(values) is None
