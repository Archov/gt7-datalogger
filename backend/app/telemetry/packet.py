"""Binary layout of the 296-byte GT7 "A" telemetry packet."""

from __future__ import annotations

import struct

from app.models import TelemetryPacket

PACKET_SIZE = 296
MAGIC = 0x47375330

# struct format for the full packet, little-endian.
# Offsets follow the community-documented Simulator Interface layout.
_HEAD = struct.Struct(
    "<i"  # 0x00 magic
    "3f"  # 0x04 position
    "3f"  # 0x10 velocity
    "3f"  # 0x1C rotation (pitch, yaw, roll)
    "f"  # 0x28 relative orientation to north
    "3f"  # 0x2C angular velocity
    "f"  # 0x38 body height
    "f"  # 0x3C engine rpm
    "4s"  # 0x40 iv (opaque)
    "f"  # 0x44 fuel level
    "f"  # 0x48 fuel capacity
    "f"  # 0x4C speed m/s
    "f"  # 0x50 boost (bar + 1)
    "f"  # 0x54 oil pressure
    "f"  # 0x58 water temp
    "f"  # 0x5C oil temp
    "4f"  # 0x60 tire temps FL FR RL RR
    "i"  # 0x70 packet id
    "h"  # 0x74 current lap
    "h"  # 0x76 total laps
    "i"  # 0x78 best lap time ms
    "i"  # 0x7C last lap time ms
    "i"  # 0x80 day progression ms
    "h"  # 0x84 race position
    "h"  # 0x86 total positions
    "H"  # 0x88 rpm alert min
    "H"  # 0x8A rpm alert max
    "h"  # 0x8C calculated max speed
    "H"  # 0x8E flags
    "B"  # 0x90 gears (low nibble current, high nibble suggested)
    "B"  # 0x91 throttle
    "B"  # 0x92 brake
    "B"  # 0x93 padding
    "4f"  # 0x94 road plane
    "4f"  # 0xA4 wheel rps FL FR RL RR
    "4f"  # 0xB4 tire radius FL FR RL RR
    "4f"  # 0xC4 suspension height FL FR RL RR
    "8f"  # 0xD4 reserved
    "f"  # 0xF4 clutch
    "f"  # 0xF8 clutch engagement
    "f"  # 0xFC rpm after clutch
    "f"  # 0x100 transmission top speed
    "8f"  # 0x104 gear ratios
    "i"  # 0x124 car id
)

assert _HEAD.size == PACKET_SIZE


def parse_packet(plain: bytes) -> TelemetryPacket:
    """Parse a decrypted 296-byte packet into the typed model."""
    if len(plain) < PACKET_SIZE:
        raise ValueError(f"packet too short: {len(plain)} bytes")
    v = _HEAD.unpack_from(plain)
    (
        _magic,
        pos_x, pos_y, pos_z,
        vel_x, vel_y, vel_z,
        rot_pitch, rot_yaw, rot_roll,
        rel_north,
        ang_x, ang_y, ang_z,
        body_height,
        rpm,
        _iv,
        fuel_level, fuel_capacity,
        speed_mps, boost,
        oil_pressure, water_temp, oil_temp,
        tt_fl, tt_fr, tt_rl, tt_rr,
        packet_id,
        current_lap, total_laps,
        best_lap, last_lap,
        day_progression,
        race_pos, total_pos,
        rpm_min, rpm_max,
        calc_max_speed,
        flags,
        gear_bits, throttle, brake, _pad,
        _rp0, _rp1, _rp2, _rp3,
        w_fl, w_fr, w_rl, w_rr,
        tr_fl, tr_fr, tr_rl, tr_rr,
        sus_fl, sus_fr, sus_rl, sus_rr,
        *rest,
    ) = v
    # rest = 8 reserved floats, clutch, clutch engagement, rpm after clutch,
    #        top speed, 8 gear ratios, car id
    clutch = rest[8]
    clutch_engagement = rest[9]
    rpm_after_clutch = rest[10]
    top_speed = rest[11]
    gear_ratios = tuple(rest[12:20])
    car_id = rest[20]

    return TelemetryPacket(
        packet_id=packet_id,
        position_x=pos_x, position_y=pos_y, position_z=pos_z,
        velocity_x=vel_x, velocity_y=vel_y, velocity_z=vel_z,
        rotation_pitch=rot_pitch, rotation_yaw=rot_yaw, rotation_roll=rot_roll,
        rel_orientation_to_north=rel_north,
        angular_velocity_x=ang_x, angular_velocity_y=ang_y, angular_velocity_z=ang_z,
        body_height=body_height,
        engine_rpm=rpm,
        fuel_level=fuel_level, fuel_capacity=fuel_capacity,
        speed_mps=speed_mps,
        boost=boost - 1.0,
        oil_pressure=oil_pressure, water_temp=water_temp, oil_temp=oil_temp,
        tire_temp_fl=tt_fl, tire_temp_fr=tt_fr, tire_temp_rl=tt_rl, tire_temp_rr=tt_rr,
        current_lap=current_lap, total_laps=total_laps,
        best_lap_time_ms=best_lap, last_lap_time_ms=last_lap,
        day_progression_ms=day_progression,
        race_position=race_pos, total_positions=total_pos,
        rpm_alert_min=float(rpm_min), rpm_alert_max=float(rpm_max),
        calculated_max_speed=calc_max_speed,
        flags=flags,
        current_gear=gear_bits & 0x0F,
        suggested_gear=gear_bits >> 4,
        throttle=throttle, brake=brake,
        wheel_rps_fl=w_fl, wheel_rps_fr=w_fr, wheel_rps_rl=w_rl, wheel_rps_rr=w_rr,
        tire_radius_fl=tr_fl, tire_radius_fr=tr_fr, tire_radius_rl=tr_rl, tire_radius_rr=tr_rr,
        suspension_fl=sus_fl, suspension_fr=sus_fr, suspension_rl=sus_rl, suspension_rr=sus_rr,
        clutch=clutch, clutch_engagement=clutch_engagement, rpm_after_clutch=rpm_after_clutch,
        transmission_top_speed=top_speed,
        gear_ratios=gear_ratios,
        car_id=car_id,
    )


def build_packet(
    *,
    packet_id: int = 0,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
    angular_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
    body_height: float = 0.1,
    engine_rpm: float = 0.0,
    iv: int = 0xDEADCAFE,
    fuel_level: float = 100.0,
    fuel_capacity: float = 100.0,
    speed_mps: float = 0.0,
    boost: float = 0.0,
    tire_temps: tuple[float, float, float, float] = (60.0, 60.0, 60.0, 60.0),
    current_lap: int = 0,
    total_laps: int = 0,
    best_lap_time_ms: int = -1,
    last_lap_time_ms: int = -1,
    day_progression_ms: int = 0,
    race_position: int = 1,
    total_positions: int = 1,
    flags: int = 0,
    current_gear: int = 1,
    suggested_gear: int = 15,
    throttle: int = 0,
    brake: int = 0,
    wheel_rps: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    tire_radius: tuple[float, float, float, float] = (0.33, 0.33, 0.33, 0.33),
    car_id: int = 0,
) -> bytes:
    """Build a plaintext packet (simulator / test fixture)."""
    return _HEAD.pack(
        MAGIC,
        *position,
        *velocity,
        0.0, 0.0, 0.0,  # rotation
        0.0,  # rel north
        *angular_velocity,
        body_height,
        engine_rpm,
        struct.pack("<I", iv),
        fuel_level, fuel_capacity,
        speed_mps, boost + 1.0,
        0.0, 85.0, 90.0,  # oil pressure, water temp, oil temp
        *tire_temps,
        packet_id,
        current_lap, total_laps,
        best_lap_time_ms, last_lap_time_ms,
        day_progression_ms,
        race_position, total_positions,
        1000, 9000,  # rpm alerts
        300,  # calc max speed
        flags,
        (suggested_gear << 4) | (current_gear & 0x0F),
        throttle, brake, 0,
        0.0, 0.0, 0.0, 0.0,  # road plane
        *wheel_rps,
        *tire_radius,
        0.0, 0.0, 0.0, 0.0,  # suspension
        *([0.0] * 8),  # reserved
        0.0, 1.0, 0.0,  # clutch, engagement, rpm after clutch
        300.0,  # top speed
        *([0.0] * 8),  # gear ratios
        car_id,
    )
