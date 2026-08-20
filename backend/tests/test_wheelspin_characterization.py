"""Deterministic drivetrain-aware wheelspin characterization."""

from __future__ import annotations

from typing import Any

from app.processing import spatial
from app.processing import wheelspin_characterization as characterization


def _lap(
    lap_id: int,
    *,
    event: bool = False,
    event_slip: float = 1.30,
    yaw: float = 0.0,
    bottoming: bool = False,
) -> dict[str, Any]:
    count = 101
    times = [index * 0.05 for index in range(count)]
    distances = [index * 2.5 for index in range(count)]
    samples: dict[str, list[float]] = {
        "t": times,
        "dist": distances,
        "pos_x": list(distances),
        "pos_z": [0.0] * count,
        "speed": [180.0] * count,
        "throttle": [40.0] * count,
        "brake": [0.0] * count,
        "gear": [3.0] * count,
        "yaw_rate_signed": [yaw] * count,
        "steering_wheel_rad": [0.1] * count,
    }
    for wheel in ("fl", "fr", "rl", "rr"):
        samples[f"slip_{wheel}"] = [1.02] * count
        samples[f"torque_{wheel}"] = [0.0 if wheel.startswith("f") else 10.0] * count
    events: list[dict[str, Any]] = []
    if event:
        for index in range(40, 49):
            samples["slip_rl"][index] = event_slip
            samples["slip_rr"][index] = event_slip
        events.append(
            {
                "type": "wheelspin",
                "start_dist": 100.0,
                "end_dist": 120.0,
                "wheels": ["rl", "rr"],
                "severity": event_slip,
            }
        )
    if bottoming:
        events.append(
            {
                "type": "bottoming",
                "start_dist": 105.0,
                "end_dist": 115.0,
                "wheels": ["rl", "rr"],
                "severity": 1.0,
            }
        )
    return {
        "id": lap_id,
        "number": lap_id,
        "time_ms": 5_000,
        "car_id": 7,
        "counts_for_best": True,
        "clean_lap": True,
        "samples": samples,
        "events": events,
    }


def _characterize(
    laps: list[dict[str, Any]], layout: str | None = "FR"
) -> characterization.CharacterizationResult:
    path = spatial.build_reference_path(laps[0]["samples"])
    assert path is not None
    trajectories = {
        int(lap["id"]): trajectory
        for lap in laps
        if (
            trajectory := spatial.project_lap(
                path, lap["samples"], completed_time_ms=int(lap["time_ms"])
            )
        )
        is not None
    }
    return characterization.characterize_wheelspin_events(
        laps,
        spatial_reference=path,
        trajectories=trajectories,
        corners=[],
        drivetrain_layout=layout,
    )


def _candidate(
    event: characterization.WheelspinCharacterization, mechanism: str
) -> characterization.Candidate:
    return next(item for item in event.candidates if item.mechanism == mechanism)


def test_authoritative_catalog_drivetrain_mapping_never_uses_telemetry() -> None:
    expected = {
        "FF": ("fwd", ("fl", "fr")),
        "FR": ("rwd", ("rl", "rr")),
        "MR": ("rwd", ("rl", "rr")),
        "RR": ("rwd", ("rl", "rr")),
        "4WD": ("awd", ("fl", "fr", "rl", "rr")),
        None: ("unknown", ()),
        "unsupported": ("unknown", ()),
    }
    for layout, (effective, wheels) in expected.items():
        result = characterization.catalog_drivetrain(layout)
        assert result.effective == effective
        assert result.effective_powered_wheels == wheels
        assert result.source == ("catalog" if wheels else "catalog_missing")


def test_bottoming_alone_does_not_remove_a_useful_comparator() -> None:
    result = _characterize([_lap(1, event=True), _lap(2, bottoming=True), _lap(3)])
    quality = result.events[0].comparators
    assert quality.lap_ids == (2, 3)
    assert quality.bottoming_context_count == 1
    assert quality.quality == "strong"


def test_signed_motion_scoring_uses_absolute_peer_magnitude() -> None:
    event_lap = _lap(1, event=True, yaw=-0.2)
    result = _characterize([event_lap, _lap(2, yaw=0.2), _lap(3, yaw=0.2)])
    event = result.events[0]
    combined = _candidate(event, "combined_lateral_longitudinal_load_candidate")
    yaw_rule = next(item for item in combined.contributions if item.feature == "yaw_deviation")
    assert event.observed["yaw_rate_signed_at_onset"] == -0.2
    assert yaw_rule.available is True
    assert yaw_rule.activation == 0
    assert yaw_rule.signed_contribution == 0.0


def test_full_contribution_trace_sums_and_export_is_bounded() -> None:
    result = _characterize([_lap(1, event=True), _lap(2), _lap(3)])
    event = result.events[0]
    for candidate in event.candidates:
        assert candidate.preclamp_score == sum(
            contribution.signed_contribution for contribution in candidate.contributions
        )
        assert all(contribution.activation in (0, 1) for contribution in candidate.contributions)

    exported = characterization.bounded_candidates(event)
    assert len(exported) <= characterization.DEFAULT_CONFIG.resolution.exported_candidates
    assert all(
        len(candidate["evidence"]) <= characterization.DEFAULT_CONFIG.resolution.exported_support
        and len(candidate["counterevidence"])
        <= characterization.DEFAULT_CONFIG.resolution.exported_counter
        for candidate in exported
    )
    assert result == _characterize([_lap(1, event=True), _lap(2), _lap(3)])


def test_rotation_precedes_power_and_counters_power_step() -> None:
    event_lap = _lap(1, event=True)
    for index in range(32, len(event_lap["samples"]["t"])):
        event_lap["samples"]["yaw_rate_signed"][index] = -0.5
    event_lap["samples"]["throttle"] = [10.0] * 38 + [60.0] * 63

    event = _characterize([event_lap, _lap(2), _lap(3)]).events[0]
    assert event.sequence["rotation_deviation_start_ms"] is not None
    assert event.sequence["meaningful_throttle_rise_start_ms"] is not None
    assert event.derived["ordering"] == "rotation_before_power"
    rotation = _candidate(event, "rotation_instability_candidate")
    power = _candidate(event, "power_step_candidate")
    assert any(
        item.feature == "rotation_before_power" and item.signed_contribution > 0
        for item in rotation.contributions
    )
    assert any(
        item.feature == "rotation_before_power" and item.signed_contribution < 0
        for item in power.contributions
    )


def test_power_before_rotation_does_not_claim_preexisting_rotation() -> None:
    event_lap = _lap(1, event=True)
    event_lap["samples"]["throttle"] = [10.0] * 30 + [60.0] * 71
    for index in range(38, len(event_lap["samples"]["t"])):
        event_lap["samples"]["yaw_rate_signed"][index] = 0.5

    event = _characterize([event_lap, _lap(2), _lap(3)]).events[0]
    assert event.derived["ordering"] == "power_before_rotation"
    rotation = _candidate(event, "rotation_instability_candidate")
    assert not any(
        item.feature == "rotation_before_power" and item.activation
        for item in rotation.contributions
    )
    assert any(
        item.feature == "power_before_rotation" and item.signed_contribution < 0
        for item in rotation.contributions
    )


def test_near_simultaneous_onsets_remain_unresolved() -> None:
    event_lap = _lap(1, event=True)
    event_lap["samples"]["throttle"] = [10.0] * 36 + [60.0] * 65
    for index in range(37, len(event_lap["samples"]["t"])):
        event_lap["samples"]["yaw_rate_signed"][index] = 0.5

    event = _characterize([event_lap, _lap(2), _lap(3)]).events[0]
    assert event.derived["ordering"] == "near_simultaneous_or_unknown"
    assert event.resolution == "mixed_or_unresolved"
    assert "temporal_order_ambiguous" in event.unresolved_reasons
    assert all(item.mechanism != "mixed_or_unresolved" for item in event.candidates)


def test_steering_is_context_only_and_motion_can_discriminate_without_large_steering() -> None:
    aligned = _lap(1, event=True)
    aligned["samples"]["steering_wheel_rad"] = [2.0] * 101
    aligned_event = _characterize([aligned, _lap(2), _lap(3)]).events[0]
    aligned_candidate = _candidate(aligned_event, "combined_lateral_longitudinal_load_candidate")
    steering_rule = next(
        item
        for item in aligned_candidate.contributions
        if item.feature == "steering_with_motion_evidence"
    )
    assert steering_rule.activation == 0

    rotating = _lap(1, event=True)
    rotating["samples"]["steering_wheel_rad"] = [0.01] * 101
    for index in range(34, 50):
        rotating["samples"]["yaw_rate_signed"][index] = 0.5
    rotating_event = _characterize([rotating, _lap(2), _lap(3)]).events[0]
    rotating_candidate = _candidate(rotating_event, "combined_lateral_longitudinal_load_candidate")
    assert any(
        item.feature == "yaw_deviation" and item.signed_contribution > 0
        for item in rotating_candidate.contributions
    )


def test_weak_comparator_pool_forces_unresolved() -> None:
    event = _characterize([_lap(1, event=True), _lap(2)]).events[0]
    assert event.comparators.count == 1
    assert event.comparators.quality == "weak"
    assert event.resolution == "mixed_or_unresolved"


def test_symmetric_and_persistent_asymmetric_spin_are_distinguished() -> None:
    symmetric = _characterize([_lap(1, event=True), _lap(2), _lap(3)]).events[0]
    symmetric_candidate = _candidate(symmetric, "single_wheel_differential_spin_candidate")
    assert any(
        item.feature == "symmetric_bilateral_spin" and item.signed_contribution < 0
        for item in symmetric_candidate.contributions
    )

    asymmetric_lap = _lap(1, event=True)
    for index in range(40, 49):
        asymmetric_lap["samples"]["slip_rr"][index] = 1.02
    asymmetric = _characterize([asymmetric_lap, _lap(2), _lap(3)]).events[0]
    asymmetric_candidate = _candidate(asymmetric, "single_wheel_differential_spin_candidate")
    assert asymmetric_candidate.score >= 0.70
    assert any(
        item.feature == "persistent_asymmetry" and item.signed_contribution > 0
        for item in asymmetric_candidate.contributions
    )


def test_surface_and_shift_evidence_respect_event_order() -> None:
    before = _lap(1, event=True)
    before["samples"]["surface"] = [float(0x1111)] * 101
    for index in range(36, 43):
        before["samples"]["surface"][index] = float(0x2222)
    before_event = _characterize([before, _lap(2), _lap(3)]).events[0]
    surface_before = _candidate(before_event, "surface_or_vertical_disturbance_candidate")
    assert any(
        item.feature == "surface_before_slip" and item.signed_contribution > 0
        for item in surface_before.contributions
    )

    after = _lap(1, event=True)
    after["samples"]["surface"] = [float(0x1111)] * 101
    for index in range(44, 51):
        after["samples"]["surface"][index] = float(0x2222)
    after["samples"]["gear"] = [3.0] * 44 + [4.0] * 57
    after_event = _characterize([after, _lap(2), _lap(3)]).events[0]
    surface_after = _candidate(after_event, "surface_or_vertical_disturbance_candidate")
    shift_after = _candidate(after_event, "shift_transient_candidate")
    assert not any(
        item.feature == "surface_before_slip" and item.activation
        for item in surface_after.contributions
    )
    assert any(
        item.feature == "disturbance_after_slip" and item.signed_contribution < 0
        for item in surface_after.contributions
    )
    assert any(
        item.feature == "shift_after_slip" and item.signed_contribution < 0
        for item in shift_after.contributions
    )


def test_missing_or_nonmatching_catalog_drivetrain_forces_unresolved() -> None:
    no_torque = [_lap(1, event=True), _lap(2), _lap(3)]
    for lap in no_torque:
        for wheel in ("fl", "fr", "rl", "rr"):
            del lap["samples"][f"torque_{wheel}"]
    unknown_event = _characterize(no_torque, None).events[0]
    assert unknown_event.derived["trustworthy_powered_wheel_intersection"] is False
    assert unknown_event.resolution == "mixed_or_unresolved"
    assert "powered_wheels_untrusted" in unknown_event.unresolved_reasons

    nonmatching = _characterize([_lap(1, event=True), _lap(2), _lap(3)], "FF").events[0]
    assert nonmatching.derived["trustworthy_powered_wheel_intersection"] is False
    assert nonmatching.resolution == "mixed_or_unresolved"
    assert "powered_wheels_untrusted" in nonmatching.unresolved_reasons


def test_lower_slip_wheelspin_events_are_relative_controls() -> None:
    result = _characterize(
        [
            _lap(1, event=True, event_slip=1.30),
            _lap(2, event=True, event_slip=1.20),
            _lap(3, event=True, event_slip=1.18),
        ]
    )
    event = next(item for item in result.events if item.lap_id == 1)
    assert event.comparators.count == 2
    assert event.comparators.strong_control_count == 0
    assert event.comparators.relative_control_count == 2
    assert event.comparators.quality == "moderate"
    assert [item["control_class"] for item in event.comparator_details] == [
        "relative",
        "relative",
    ]


def test_relative_control_dominance_boundaries() -> None:
    config = characterization.DEFAULT_CONFIG

    def metrics(peak: float, integral: float, duration: float) -> dict[str, Any]:
        return {
            "peak_slip": {"rl": peak},
            "slip_excess_integral": integral,
            "duration_above_threshold_ms": duration,
        }

    event = metrics(1.30, 1.0, 100.0)
    assert characterization._control_class(event, metrics(1.27, 0.8, 110.0), config) == "relative"
    assert characterization._control_class(event, metrics(1.27, 0.79, 110.1), config) is None
    assert characterization._control_class(event, metrics(1.10, 1.0, 100.0), config) == "ideal"


def test_motion_context_is_derived_once_per_lap(monkeypatch: Any) -> None:
    laps = [_lap(1, event=True), _lap(2), _lap(3)]
    path = spatial.build_reference_path(laps[0]["samples"])
    assert path is not None
    trajectories = {
        lap["id"]: spatial.project_lap(path, lap["samples"], completed_time_ms=lap["time_ms"])
        for lap in laps
    }
    original = characterization._motion_series
    calls = 0

    def counted(*args: Any, **kwargs: Any) -> dict[str, list[float]]:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(characterization, "_motion_series", counted)
    characterization.characterize_wheelspin_events(
        laps,
        spatial_reference=path,
        trajectories={key: value for key, value in trajectories.items() if value is not None},
        corners=[],
    )
    assert calls == len(laps)


def test_ineligible_wheelspin_is_retained_but_not_used_as_comparator() -> None:
    excluded = _lap(1, event=True)
    excluded["counts_for_best"] = False
    result = _characterize([excluded, _lap(2), _lap(3)])
    event = next(item for item in result.events if item.lap_id == 1)
    assert event.resolution == "mixed_or_unresolved"
    assert "lap_not_comparison_eligible" in event.unresolved_reasons
    assert event.comparators.count == 0


def test_surface_evidence_does_not_activate_vertical_corroboration() -> None:
    event_lap = _lap(1, event=True)
    event_lap["samples"]["surface"] = [float(0x1111)] * 101
    for index in range(36, 43):
        event_lap["samples"]["surface"][index] = float(0x2222)
    event = _characterize([event_lap, _lap(2), _lap(3)]).events[0]
    candidate = _candidate(event, "surface_or_vertical_disturbance_candidate")
    surface = next(
        item for item in candidate.contributions if item.feature == "surface_before_slip"
    )
    vertical = next(
        item for item in candidate.contributions if item.feature == "body_suspension_disturbance"
    )
    assert surface.activation == 1
    assert vertical.activation == 0


def test_surface_transition_before_causal_window_has_no_support() -> None:
    event_lap = _lap(1, event=True)
    event_lap["samples"]["surface"] = [float(0x1111)] * 101
    for index in range(20, 27):
        event_lap["samples"]["surface"][index] = float(0x2222)
    event = _characterize([event_lap, _lap(2), _lap(3)]).events[0]
    candidate = _candidate(event, "surface_or_vertical_disturbance_candidate")
    surface = next(
        item for item in candidate.contributions if item.feature == "surface_before_slip"
    )
    assert event.sequence["surface_transition_ms"] is not None
    assert event.sequence["surface_transition_ms"] < -400
    assert surface.activation == 0


def test_strong_local_shift_sequence_can_resolve_without_comparators() -> None:
    event_lap = _lap(1, event=True)
    event_lap["samples"]["gear"] = [3.0] * 36 + [4.0] * 65
    event_lap["samples"]["throttle"] = [10.0] * 36 + [60.0] * 65
    event = _characterize([event_lap]).events[0]
    assert event.comparators.quality == "weak"
    assert event.candidates[0].mechanism == "shift_transient_candidate"
    assert event.resolution == "resolved"
    assert "comparator_quality_weak" not in event.unresolved_reasons


def test_corner_context_is_noncausal_and_wrap_aware() -> None:
    lap = _lap(1)
    path = spatial.build_reference_path(lap["samples"])
    assert path is not None
    corners = [
        {"n": 1, "entry_dist": 50.0, "apex_dist": 75.0, "exit_dist": 100.0},
        {"n": 8, "entry_dist": 225.0, "apex_dist": 240.0, "exit_dist": 20.0},
    ]
    assert characterization._corner_context(path, corners, 110.0) == (
        None,
        1,
        "after_exit",
        10.0,
    )
    reference, context, relation, distance = characterization._corner_context(
        path, corners, 5.0
    )
    assert reference == context == 8
    assert relation == "apex_to_exit"
    assert distance == 0.0
