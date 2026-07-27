"""Detect chassis events in a lap's sample series.

Runs once at lap save (and on import), never per tick. Each event is a plain
dict so it JSON-serializes into the lap row:

    {"type": "lockup" | "wheelspin" | "bottoming" | "kerb",
     "start_dist": m, "end_dist": m, "wheels": ["fl", ...], "severity": float}

Severity is the worst slip ratio for slip events (min for lockups, max for
wheelspin) and the compression fraction for suspension events.
"""

from __future__ import annotations

from typing import Any

Event = dict[str, Any]
Samples = dict[str, list[float]]

WHEELS = ("fl", "fr", "rl", "rr")

LOCKUP_SLIP = 0.9  # braking with wheel slip below this = locking
WHEELSPIN_SLIP = 1.1  # on throttle with slip above this = spinning
MIN_SLIP_TICKS = 6  # ~0.1 s sustained before it counts
BRAKE_ON = 20.0  # %
THROTTLE_ON = 40.0  # %
BOTTOM_FRACTION = 0.98  # of the lap's max compression
MIN_BOTTOM_TICKS = 3
KERB_SPIKE_FRACTION = 0.35  # of the wheel's travel range, single-tick jump
MAX_EVENTS_PER_TYPE = 40  # noisy data guard — keep the payload bounded


def _runs(active: list[bool], min_ticks: int) -> list[tuple[int, int]]:
    """Contiguous [start, end] index runs of True at least min_ticks long."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            if i - start >= min_ticks:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(active) - start >= min_ticks:
        runs.append((start, len(active) - 1))
    return runs


def _slip_events(s: Samples) -> list[Event]:
    slips = [s.get(f"slip_{w}") for w in WHEELS]
    if any(col is None for col in slips):
        return []
    dist, throttle, brake = s["dist"], s["throttle"], s["brake"]
    n = min(len(dist), *(len(col) for col in slips if col is not None))
    events: list[Event] = []

    for kind, gate, threshold, worst in (
        ("lockup", brake, LOCKUP_SLIP, min),
        ("wheelspin", throttle, WHEELSPIN_SLIP, max),
    ):
        below = kind == "lockup"
        active = [
            gate[i] >= (BRAKE_ON if below else THROTTLE_ON)
            and any(
                (col[i] < threshold) if below else (col[i] > threshold)
                for col in slips
                if col is not None
            )
            for i in range(n)
        ]
        for start, end in _runs(active, MIN_SLIP_TICKS)[:MAX_EVENTS_PER_TYPE]:
            wheels = [
                w
                for w, col in zip(WHEELS, slips, strict=True)
                if col is not None
                and any(
                    (col[i] < threshold) if below else (col[i] > threshold)
                    for i in range(start, end + 1)
                )
            ]
            window = [
                col[i]
                for col in slips
                if col is not None
                for i in range(start, end + 1)
            ]
            events.append(
                {
                    "type": kind,
                    "start_dist": dist[start],
                    "end_dist": dist[end],
                    "wheels": wheels,
                    "severity": round(worst(window), 3),
                }
            )
    return events


def _suspension_events(s: Samples) -> list[Event]:
    dist = s["dist"]
    events: list[Event] = []
    kerb_count = 0
    for w in WHEELS:
        col = s.get(f"sus_{w}")
        if not col:
            continue
        n = min(len(dist), len(col))
        lo, hi = min(col[:n]), max(col[:n])
        rng = hi - lo
        if rng < 1e-6:
            continue
        # Bottoming: compression within a few % of the lap's max, sustained.
        # Absolute travel varies per car, so normalize per lap.
        limit = lo + rng * BOTTOM_FRACTION
        active = [col[i] >= limit for i in range(n)]
        for start, end in _runs(active, MIN_BOTTOM_TICKS)[:MAX_EVENTS_PER_TYPE]:
            events.append(
                {
                    "type": "bottoming",
                    "start_dist": dist[start],
                    "end_dist": dist[end],
                    "wheels": [w],
                    "severity": round((max(col[start : end + 1]) - lo) / rng, 3),
                }
            )
        # Kerb strike: a single-tick spike well above both neighbors.
        spike = rng * KERB_SPIKE_FRACTION
        for i in range(2, n - 2):
            if kerb_count >= MAX_EVENTS_PER_TYPE:
                break
            neighbors = (col[i - 2] + col[i + 2]) / 2
            if col[i] - neighbors > spike:
                events.append(
                    {
                        "type": "kerb",
                        "start_dist": dist[i],
                        "end_dist": dist[i],
                        "wheels": [w],
                        "severity": round((col[i] - lo) / rng, 3),
                    }
                )
                kerb_count += 1
    return events


def detect_events(samples: Samples) -> list[Event]:
    """All detected events for a lap, sorted by start distance."""
    if not samples.get("dist"):
        return []
    events = _slip_events(samples) + _suspension_events(samples)
    events.sort(key=lambda e: (e["start_dist"], e["type"]))
    return events
