"""Track auto-identification from lap geometry.

A track is fingerprinted by its lap length and the bounding box of the racing
line. GT7 world coordinates are fixed per track, so a stored signature matches
future sessions on the same circuit regardless of car or lap time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

LENGTH_TOLERANCE = 0.04  # 4 % lap-length difference (racing line varies)
CENTER_TOLERANCE_M = 120.0
EXTENT_TOLERANCE = 0.20


@dataclass(slots=True)
class TrackSignature:
    length_m: float
    min_x: float
    max_x: float
    min_z: float
    max_z: float


class TrackLike(Protocol):
    length_m: float
    min_x: float
    max_x: float
    min_z: float
    max_z: float


def signature_from_samples(samples: dict[str, list[float]]) -> TrackSignature | None:
    if not samples.get("dist") or not samples.get("pos_x"):
        return None
    return TrackSignature(
        length_m=samples["dist"][-1],
        min_x=min(samples["pos_x"]),
        max_x=max(samples["pos_x"]),
        min_z=min(samples["pos_z"]),
        max_z=max(samples["pos_z"]),
    )


def matches(sig: TrackSignature, track: TrackLike) -> bool:
    if track.length_m <= 0 or sig.length_m <= 0:
        return False
    if abs(sig.length_m - track.length_m) / track.length_m > LENGTH_TOLERANCE:
        return False
    sig_cx = (sig.min_x + sig.max_x) / 2
    sig_cz = (sig.min_z + sig.max_z) / 2
    trk_cx = (track.min_x + track.max_x) / 2
    trk_cz = (track.min_z + track.max_z) / 2
    if abs(sig_cx - trk_cx) > CENTER_TOLERANCE_M or abs(sig_cz - trk_cz) > CENTER_TOLERANCE_M:
        return False
    for sig_ext, trk_ext in (
        (sig.max_x - sig.min_x, track.max_x - track.min_x),
        (sig.max_z - sig.min_z, track.max_z - track.min_z),
    ):
        if trk_ext > 0 and abs(sig_ext - trk_ext) / trk_ext > EXTENT_TOLERANCE:
            return False
    return True
