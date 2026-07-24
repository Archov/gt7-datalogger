"""Derived calculations: resampling, deltas, deviation, fuel map, race line."""

import pytest

from app.processing import analysis
from app.processing.laps import new_sample_store


def make_lap(total_dist: float, speed: float, n: int = 100) -> dict[str, list[float]]:
    """Constant-speed lap: distance grows linearly, t = dist / speed."""
    s = new_sample_store()
    for i in range(n):
        d = total_dist * i / (n - 1)
        s["t"].append(d / speed)
        s["dist"].append(d)
        s["speed"].append(speed * 3.6)
        s["throttle"].append(100.0)
        s["brake"].append(0.0)
        s["coast"].append(0.0)
        s["gear"].append(4.0)
        s["rpm"].append(6000.0)
        s["boost"].append(0.0)
        s["tire_slip"].append(1.0)
        s["yaw_rate"].append(0.1)
        s["pos_x"].append(d)
        s["pos_z"].append(0.0)
        s["body_height"].append(90.0)
        s["fuel"].append(100.0 - d / 1000)
    return s


def test_resample_by_distance() -> None:
    lap = make_lap(1000.0, 50.0)
    out = analysis.resample_by_distance(lap, step=100.0, columns=("speed", "t"))
    assert out["dist"] == [i * 100.0 for i in range(11)]
    assert all(v == pytest.approx(180.0) for v in out["speed"])
    assert out["t"][5] == pytest.approx(500 / 50, abs=0.01)


def test_time_delta_series_slower_lap_positive() -> None:
    fast = make_lap(1000.0, 50.0)
    slow = make_lap(1000.0, 40.0)
    delta = analysis.time_delta_series(slow, fast, step=100.0)
    # At 1000 m: slow t=25 s, fast t=20 s -> +5000 ms
    assert delta["delta_ms"][-1] == pytest.approx(5000.0, abs=10)
    assert all(d >= 0 for d in delta["delta_ms"])


def test_time_delta_reference_vs_itself_is_zero() -> None:
    lap = make_lap(1000.0, 50.0)
    delta = analysis.time_delta_series(lap, lap, step=100.0)
    assert all(abs(d) < 1e-6 for d in delta["delta_ms"])


def test_speed_deviation() -> None:
    laps = [make_lap(1000.0, 50.0), make_lap(1000.0, 50.0), make_lap(1000.0, 60.0)]
    out = analysis.speed_deviation(laps, step=100.0)
    assert out["median"][0] == pytest.approx(180.0)  # median of 180,180,216
    assert all(d > 0 for d in out["deviation"])
    # Identical laps -> zero deviation
    same = analysis.speed_deviation([make_lap(1000.0, 50.0)] * 3, step=100.0)
    assert all(d == pytest.approx(0.0) for d in same["deviation"])


def test_speed_deviation_needs_two_laps() -> None:
    out = analysis.speed_deviation([make_lap(1000.0, 50.0)])
    assert out["dist"] == []


def test_race_line_zones() -> None:
    lap = make_lap(300.0, 50.0, n=3)
    lap["throttle"] = [100.0, 0.0, 0.0]
    lap["brake"] = [0.0, 100.0, 0.0]
    line = analysis.race_line(lap)
    assert line["zone"] == [2, 0, 1]  # throttle, brake, coast


def test_fuel_map() -> None:
    rows = analysis.fuel_map(fuel_level=50.0, fuel_per_lap=2.0, lap_time_ms=90_000)
    assert len(rows) == 11
    neutral = next(r for r in rows if r.setting == 0)
    assert neutral.fuel_per_lap == pytest.approx(2.0)
    assert neutral.laps_remaining == pytest.approx(25.0)
    assert neutral.time_remaining_ms == 25 * 90_000
    lean = next(r for r in rows if r.setting == -5)
    rich = next(r for r in rows if r.setting == 5)
    # Leaner -> less fuel per lap, more laps remaining, slower laps
    assert lean.fuel_per_lap < neutral.fuel_per_lap < rich.fuel_per_lap
    assert lean.laps_remaining > neutral.laps_remaining > rich.laps_remaining
    assert lean.lap_time_delta_ms > 0 > rich.lap_time_delta_ms


def test_fuel_map_invalid_inputs() -> None:
    assert analysis.fuel_map(50.0, 0.0, 90_000) == []
    assert analysis.fuel_map(50.0, 2.0, 0) == []


def test_interp_edges() -> None:
    xs, ys = [0.0, 10.0], [0.0, 100.0]
    assert analysis._interp(xs, ys, -5.0) == 0.0
    assert analysis._interp(xs, ys, 15.0) == 100.0
    assert analysis._interp(xs, ys, 5.0) == pytest.approx(50.0)
