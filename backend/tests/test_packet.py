"""Packet building, encryption round-trip, and field decoding."""

from app.models import SimulatorFlags
from app.telemetry.crypto import decrypt_packet, encrypt_packet
from app.telemetry.packet import PACKET_SIZE, build_packet, parse_packet


def make_plain(**kwargs) -> bytes:
    return build_packet(**kwargs)


def test_packet_size() -> None:
    assert len(make_plain()) == PACKET_SIZE


def test_encrypt_decrypt_roundtrip() -> None:
    plain = make_plain(packet_id=1234, speed_mps=55.5, current_lap=3)
    wire = encrypt_packet(plain)
    assert wire != plain
    recovered = decrypt_packet(wire)
    assert recovered is not None
    # The 4 IV bytes at 0x40 are consumed by the nonce derivation and decrypt
    # to keystream garbage; every other byte must round-trip exactly.
    assert recovered[:0x40] == plain[:0x40]
    assert recovered[0x44:] == plain[0x44:]


def test_decrypt_rejects_garbage() -> None:
    assert decrypt_packet(b"\x00" * PACKET_SIZE) is None
    assert decrypt_packet(b"short") is None


def test_parse_core_fields() -> None:
    plain = make_plain(
        packet_id=42,
        speed_mps=50.0,
        engine_rpm=7200.0,
        current_lap=2,
        total_laps=10,
        best_lap_time_ms=95_432,
        last_lap_time_ms=96_001,
        fuel_level=42.5,
        throttle=255,
        brake=128,
        current_gear=4,
        suggested_gear=3,
        boost=0.8,
        flags=int(SimulatorFlags.CAR_ON_TRACK | SimulatorFlags.HAS_TURBO),
        car_id=3298,
    )
    p = parse_packet(plain)
    assert p.packet_id == 42
    assert p.speed_mps == 50.0
    assert abs(p.speed_kmh - 180.0) < 1e-6
    assert p.engine_rpm == 7200.0
    assert p.current_lap == 2
    assert p.total_laps == 10
    assert p.best_lap_time_ms == 95_432
    assert p.last_lap_time_ms == 96_001
    assert abs(p.fuel_level - 42.5) < 1e-6
    assert p.throttle == 255
    assert abs(p.throttle_pct - 100.0) < 0.1
    assert p.brake == 128
    assert p.current_gear == 4
    assert p.suggested_gear == 3
    assert abs(p.boost - 0.8) < 1e-6
    assert p.is_on_track
    assert not p.is_paused
    assert p.car_id == 3298


def test_tire_slip_ratio() -> None:
    # 30 m/s car speed, wheels spinning at surface speed 36 m/s -> ratio 1.2
    plain = make_plain(
        speed_mps=30.0,
        wheel_rps=(36 / 0.33,) * 4,
        tire_radius=(0.33,) * 4,
    )
    p = parse_packet(plain)
    assert abs(p.tire_slip_ratio - 1.2) < 0.01


def test_tire_slip_ratio_at_standstill() -> None:
    p = parse_packet(make_plain(speed_mps=0.0))
    assert p.tire_slip_ratio == 1.0
