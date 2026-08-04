"""Live race-event detection: overtakes, positions lost, off-road excursions."""

from app.models import SimulatorFlags, TelemetryPacket
from app.notify import ALL_EVENTS, Notifier, parse_events
from app.processing.live_events import (
    OFFROAD_MIN_TICKS,
    OFFROAD_REARM_TICKS,
    POSITION_HOLD_TICKS,
    LiveEventWatcher,
)
from app.telemetry.packet import build_packet, parse_packet

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


def racing_packet(position: int = 3, total: int = 12, **kwargs) -> TelemetryPacket:
    return parse_packet(
        build_packet(
            fmt="C",
            flags=ON_TRACK,
            race_position=position,
            total_positions=total,
            speed_mps=kwargs.pop("speed_mps", 40.0),
            **kwargs,
        )
    )


def feed_n(watcher: LiveEventWatcher, packet: TelemetryPacket, n: int) -> list:
    events = []
    for _ in range(n):
        events.extend(watcher.feed(packet))
    return events


def test_overtake_fires_after_hold() -> None:
    w = LiveEventWatcher()
    w.feed(racing_packet(position=3))  # baseline
    events = feed_n(w, racing_packet(position=2), POSITION_HOLD_TICKS + 2)
    assert len(events) == 1
    assert events[0].kind == "overtake"
    assert events[0].position == 2
    assert events[0].previous_position == 3
    # Holding the position produces no further events
    assert feed_n(w, racing_packet(position=2), 200) == []


def test_position_lost_fires_after_hold() -> None:
    w = LiveEventWatcher()
    w.feed(racing_packet(position=3))
    events = feed_n(w, racing_packet(position=4), POSITION_HOLD_TICKS + 2)
    assert [e.kind for e in events] == ["position_lost"]


def test_side_by_side_flapping_does_not_fire() -> None:
    w = LiveEventWatcher()
    w.feed(racing_packet(position=3))
    events = []
    for _ in range(20):  # P2/P3 swap every 10 ticks — never holds for 1 s
        events.extend(feed_n(w, racing_packet(position=2), 10))
        events.extend(feed_n(w, racing_packet(position=3), 10))
    assert events == []


def test_no_position_events_without_live_position() -> None:
    w = LiveEventWatcher()
    # GT7 reports -1 outside supported race types, and 1-of-1 in time trials
    assert feed_n(w, racing_packet(position=-1), 100) == []
    assert feed_n(w, racing_packet(position=1, total=1), 100) == []


def test_no_events_while_paused_or_off_track() -> None:
    w = LiveEventWatcher()
    w.feed(racing_packet(position=3))
    paused = parse_packet(
        build_packet(
            fmt="C",
            flags=int(SimulatorFlags.CAR_ON_TRACK | SimulatorFlags.PAUSED),
            race_position=2,
            total_positions=12,
        )
    )
    assert feed_n(w, paused, 200) == []


def test_off_road_fires_once_and_rearms() -> None:
    w = LiveEventWatcher()
    grass = racing_packet(surface_types="GGGG")
    tarmac = racing_packet(surface_types="TTTT")
    events = feed_n(w, grass, OFFROAD_MIN_TICKS + 50)
    assert [e.kind for e in events] == ["off_road"]
    # Still off-road: no repeat until re-armed
    assert feed_n(w, grass, 500) == []
    # Back on tarmac long enough to re-arm, then a second excursion fires
    assert feed_n(w, tarmac, OFFROAD_REARM_TICKS + 1) == []
    events = feed_n(w, grass, OFFROAD_MIN_TICKS + 1)
    assert [e.kind for e in events] == ["off_road"]


def test_track_limits_nibble_is_not_off_road() -> None:
    w = LiveEventWatcher()
    two_wheels = racing_packet(surface_types="GGTT")
    assert feed_n(w, two_wheels, 300) == []


def test_kerbs_are_not_off_road() -> None:
    w = LiveEventWatcher()
    kerb = racing_packet(surface_types="CCTT")
    assert feed_n(w, kerb, 300) == []


def test_slow_excursion_is_ignored() -> None:
    w = LiveEventWatcher()
    crawling = racing_packet(surface_types="GGGG", speed_mps=2.0)
    assert feed_n(w, crawling, 300) == []


def test_packet_a_has_no_surface_so_no_off_road() -> None:
    w = LiveEventWatcher()
    p = parse_packet(
        build_packet(flags=ON_TRACK, race_position=3, total_positions=12, speed_mps=40.0)
    )
    assert p.surface_types is None
    assert feed_n(w, p, 300) == []


def test_event_helpers_use_canonical_names(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(
        Notifier, "notify", lambda self, event, title, fields: sent.append(event)
    )
    n = Notifier()
    n.overtake(2, 3, 12, "car", "track")
    n.position_lost(3, 2, 12, "car", "track")
    n.off_road(5, "car", "track")
    assert sent == ["overtake", "position_lost", "off_road"]
    assert all(e in ALL_EVENTS for e in sent)


def test_notify_respects_enabled_set() -> None:
    # The real notify() drops disabled events before scheduling any send.
    n = Notifier()
    n.url = "https://example.invalid/hook"
    n.enabled = set()
    # Would raise RuntimeError (no running loop) if it tried to schedule a task
    n.notify("overtake", "t", [])
    n.enabled = {"overtake"}
    try:
        n.notify("overtake", "t", [])
    except RuntimeError:
        pass  # reached task scheduling — the event passed the gate
    else:  # pragma: no cover - defensive
        raise AssertionError("expected notify to attempt scheduling")


def test_parse_events() -> None:
    assert parse_events("overtake, off_road") == {"overtake", "off_road"}
    assert parse_events("bogus,overtake") == {"overtake"}
    assert parse_events("") == set()
