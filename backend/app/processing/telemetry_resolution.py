"""Read-only resolution of missing normalized channels from raw archives."""

from __future__ import annotations

import logging
import math
from bisect import bisect_left
from pathlib import Path
from typing import Any, cast

from app.processing import laps as lap_processing
from app.processing.orientation import ORIENTATION_CHANNELS, normalize_quaternion, slerp
from app.telemetry import raw_archive

log = logging.getLogger(__name__)

DISCRETE_CHANNELS = frozenset(("gear", "aids", "surface"))

Samples = dict[str, list[float]]


def _aligned_channels(samples: Samples) -> set[str]:
    size = len(samples.get("t") or [])
    available = {name for name, values in samples.items() if len(values) == size}
    surface = samples.get("surface") or []
    if "surface" in available and (not surface or all(int(value) == 0 for value in surface)):
        available.discard("surface")
    orientation_arrays = [samples.get(channel) or [] for channel in ORIENTATION_CHANNELS]
    orientation_valid = all(len(values) == size for values in orientation_arrays) and all(
        normalize_quaternion(tuple(values[index] for values in orientation_arrays)) is not None
        for index in range(size)
    )
    if not orientation_valid:
        available.difference_update(ORIENTATION_CHANNELS)
    return available


def _archive_path(data_root: Path, metadata: object) -> Path | None:
    if not isinstance(metadata, dict):
        return None
    if metadata.get("status") != "complete" or metadata.get("complete") is not True:
        return None
    value = metadata.get("path")
    if not isinstance(value, str) or not value:
        return None
    root = data_root.resolve()
    candidate = (root / value).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


def _interpolate(
    source_t: list[float], source_values: list[float], target_t: list[float], *, discrete: bool
) -> list[float] | None:
    if not source_t or len(source_values) != len(source_t):
        return None
    if any(
        not math.isfinite(value)
        for values in (source_t, source_values, target_t)
        for value in values
    ):
        return None
    if source_t == target_t:
        return list(source_values)
    if not target_t or target_t[0] < source_t[0] or target_t[-1] > source_t[-1]:
        return None
    result: list[float] = []
    for value in target_t:
        right = bisect_left(source_t, value)
        if right == 0:
            result.append(source_values[0])
            continue
        if right == len(source_t):
            result.append(source_values[-1])
            continue
        if source_t[right] == value:
            result.append(source_values[right])
            continue
        left = right - 1
        if discrete:
            selected = right if source_t[right] - value < value - source_t[left] else left
            result.append(source_values[selected])
            continue
        span = source_t[right] - source_t[left]
        if span <= 0:
            return None
        fraction = (value - source_t[left]) / span
        result.append(source_values[left] + (source_values[right] - source_values[left]) * fraction)
    return result


def _interpolate_quaternions(
    source: Samples, source_t: list[float], target_t: list[float]
) -> dict[str, list[float]] | None:
    arrays = [source.get(channel) or [] for channel in ORIENTATION_CHANNELS]
    if any(len(values) != len(source_t) for values in arrays):
        return None
    quaternions = [tuple(values[i] for values in arrays) for i in range(len(source_t))]
    if any(normalize_quaternion(quaternion) is None for quaternion in quaternions):
        return None
    if source_t == target_t:
        return {
            channel: list(values)
            for channel, values in zip(ORIENTATION_CHANNELS, arrays, strict=True)
        }
    if not target_t or not source_t or target_t[0] < source_t[0] or target_t[-1] > source_t[-1]:
        return None
    resolved: list[tuple[float, float, float, float]] = []
    for value in target_t:
        right = bisect_left(source_t, value)
        if right == 0:
            quaternion = normalize_quaternion(quaternions[0])
        elif right == len(source_t):
            quaternion = normalize_quaternion(quaternions[-1])
        elif source_t[right] == value:
            quaternion = normalize_quaternion(quaternions[right])
        else:
            left = right - 1
            span = source_t[right] - source_t[left]
            if span <= 0:
                return None
            quaternion = slerp(
                quaternions[left], quaternions[right], (value - source_t[left]) / span
            )
        if quaternion is None:
            return None
        resolved.append(quaternion)
    return {
        channel: [quaternion[index] for quaternion in resolved]
        for index, channel in enumerate(ORIENTATION_CHANNELS)
    }


def persisted_session_view(bundle: dict[str, Any], requested_channels: set[str]) -> dict[str, Any]:
    """Clone a bundle and describe only its currently persisted availability."""
    resolved = dict(bundle)
    resolved["session"] = dict(bundle.get("session") or {})
    laps: list[dict[str, Any]] = []
    for persisted_lap in bundle.get("laps") or []:
        lap = dict(persisted_lap)
        samples = persisted_lap.get("samples")
        lap["samples"] = dict(samples) if isinstance(samples, dict) else {}
        laps.append(lap)
    resolved["laps"] = laps
    requested = {
        channel
        for channel in requested_channels
        if channel in lap_processing.STORED_SAMPLE_COLUMNS
    }
    provenance: dict[int, dict[str, list[str]]] = {}
    for lap in laps:
        samples_value = lap.get("samples")
        samples = cast(Samples, samples_value) if isinstance(samples_value, dict) else {}
        available = _aligned_channels(samples)
        unavailable = requested - available
        provenance[int(lap["id"])] = {
            "persisted": sorted(available),
            "archive_replay": [],
            "unavailable": sorted(unavailable),
        }
    resolved["channel_provenance"] = provenance
    return resolved


async def resolve_session_telemetry(
    bundle: dict[str, Any],
    requested_channels: set[str],
    data_root: Path,
    *,
    force_replay: bool = False,
) -> dict[str, Any]:
    """Resolve missing channels in memory and attach an explicit replay report."""
    resolved = persisted_session_view(bundle, requested_channels)
    laps = cast(list[dict[str, Any]], resolved["laps"])
    provenance = cast(dict[int, dict[str, list[str]]], resolved["channel_provenance"])
    missing = force_replay or any(state["unavailable"] for state in provenance.values())
    report: dict[str, Any] = {
        "status": "not_needed",
        "error": None,
        "matched_lap_ids": [],
        "skipped_lap_ids": [],
        "recovered_channel_count": 0,
    }

    if missing:
        path = _archive_path(data_root, resolved.get("raw_archive_meta"))
        if path is None:
            report.update(status="failed", error="archive_unavailable")
        else:
            reconstructed_laps: list[lap_processing.CompletedLap] = []
            reconstructed_sessions: list[lap_processing.SessionInfo] = []

            async def on_lap(lap: lap_processing.CompletedLap) -> None:
                reconstructed_laps.append(lap)

            async def on_session(session: lap_processing.SessionInfo) -> None:
                reconstructed_sessions.append(session)

            processor = lap_processing.LapProcessor(on_lap=on_lap, on_session=on_session)
            try:
                await raw_archive.replay_archive(path, processor.feed, strict_truncation=True)
                session = resolved.get("session") or {}
                expected_car = int(session.get("car_id", -1))
                if (
                    len(reconstructed_sessions) != 1
                    or reconstructed_sessions[0].car_id != expected_car
                ):
                    raise raw_archive.ArchiveError(
                        "archive replay did not reconstruct exactly the persisted session"
                    )
                by_key: dict[tuple[int, int, int], lap_processing.CompletedLap | None] = {}
                for replayed in reconstructed_laps:
                    key = (replayed.car_id, replayed.number, replayed.time_ms)
                    by_key[key] = None if key in by_key else replayed
                for lap in laps:
                    lap_id = int(lap["id"])
                    state = provenance[lap_id]
                    missing_for_lap = set(state["unavailable"])
                    telemetry_meta = lap.get("telemetry_meta")
                    if isinstance(telemetry_meta, dict) and telemetry_meta.get("partial") is True:
                        report["skipped_lap_ids"].append(lap_id)
                        continue
                    if not missing_for_lap:
                        continue
                    key = (int(lap["car_id"]), int(lap["number"]), int(lap["time_ms"]))
                    matched_lap = by_key.get(key)
                    if matched_lap is None:
                        report["skipped_lap_ids"].append(lap_id)
                        continue
                    target = lap["samples"]
                    source = matched_lap.samples
                    target_t = target.get("t") or []
                    source_t = source.get("t") or []
                    recovered: dict[str, list[float]] = {}
                    missing_orientation = missing_for_lap.intersection(ORIENTATION_CHANNELS)
                    if missing_orientation:
                        orientation = _interpolate_quaternions(source, source_t, target_t)
                        if orientation is not None:
                            recovered.update(
                                {channel: orientation[channel] for channel in missing_orientation}
                            )
                    for channel in sorted(missing_for_lap - set(ORIENTATION_CHANNELS)):
                        values = source.get(channel) or []
                        aligned = _interpolate(
                            source_t,
                            values,
                            target_t,
                            discrete=channel in DISCRETE_CHANNELS,
                        )
                        if aligned is not None:
                            recovered[channel] = aligned
                    for channel, values in recovered.items():
                        target[channel] = values
                    state["archive_replay"] = sorted(recovered)
                    state["unavailable"] = sorted(missing_for_lap - recovered.keys())
                    if recovered:
                        report["matched_lap_ids"].append(lap_id)
                        report["recovered_channel_count"] += len(recovered)
                report["status"] = "partial" if report["skipped_lap_ids"] else "complete"
            except Exception as exc:  # noqa: BLE001 - archive recovery must never break export
                report.update(status="failed", error=type(exc).__name__)
                log.warning(
                    "raw telemetry recovery failed for session %s: %s",
                    (resolved.get("session") or {}).get("id"),
                    exc,
                )

    report["matched_lap_ids"] = sorted(set(report["matched_lap_ids"]))
    report["skipped_lap_ids"] = sorted(set(report["skipped_lap_ids"]))
    resolved["_telemetry_resolution"] = report
    return resolved
