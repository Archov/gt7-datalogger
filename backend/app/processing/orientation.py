"""Pure helpers for GT7's native vehicle orientation quaternion."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

Quaternion = tuple[float, float, float, float]
Vector3 = tuple[float, float, float]
ORIENTATION_CHANNELS = (
    "orientation_x",
    "orientation_y",
    "orientation_z",
    "orientation_w",
)

NORM_TOLERANCE = 0.05
MIN_TRAVEL_SPEED_MPS = 0.1


def normalize_quaternion(values: Sequence[float]) -> Quaternion | None:
    """Validate and normalize a native (x, y, z, w) quaternion."""
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        return None
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0.0 or abs(norm - 1.0) > NORM_TOLERANCE:
        return None
    return cast(Quaternion, tuple(value / norm for value in values))


def chassis_forward(quaternion: Sequence[float]) -> Vector3 | None:
    """Rotate vehicle-local -Z (the nose direction) into world coordinates."""
    normalized = normalize_quaternion(quaternion)
    if normalized is None:
        return None
    x, y, z, w = normalized
    return (
        -2.0 * (x * z + y * w),
        2.0 * (x * w - y * z),
        -(1.0 - 2.0 * (x * x + y * y)),
    )


def chassis_up(quaternion: Sequence[float]) -> Vector3 | None:
    """Rotate vehicle-local +Y into world coordinates."""
    normalized = normalize_quaternion(quaternion)
    if normalized is None:
        return None
    x, y, z, w = normalized
    return (
        2.0 * (x * y - z * w),
        1.0 - 2.0 * (x * x + z * z),
        2.0 * (y * z + x * w),
    )


def wrap_angle(angle: float) -> float:
    """Wrap radians into (-pi, pi]."""
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    while angle > math.pi:
        angle -= 2.0 * math.pi
    return angle


def slerp(left: Sequence[float], right: Sequence[float], fraction: float) -> Quaternion | None:
    """Shortest-path interpolation, including the q/-q hemisphere equivalence."""
    q0 = normalize_quaternion(left)
    q1 = normalize_quaternion(right)
    if q0 is None or q1 is None:
        return None
    dot = sum(a * b for a, b in zip(q0, q1, strict=True))
    if dot < 0.0:
        q1 = cast(Quaternion, tuple(-value for value in q1))
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        blended = tuple(a + fraction * (b - a) for a, b in zip(q0, q1, strict=True))
        return normalize_quaternion(blended)
    angle = math.acos(dot)
    scale = math.sin(angle)
    if scale == 0.0:
        return q0
    left_weight = math.sin((1.0 - fraction) * angle) / scale
    right_weight = math.sin(fraction * angle) / scale
    return cast(
        Quaternion,
        tuple(left_weight * a + right_weight * b for a, b in zip(q0, q1, strict=True)),
    )
