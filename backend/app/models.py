"""Typed telemetry model normalized from raw GT7 packets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntFlag


class SimulatorFlags(IntFlag):
    NONE = 0
    CAR_ON_TRACK = 1 << 0
    PAUSED = 1 << 1
    LOADING = 1 << 2
    IN_GEAR = 1 << 3
    HAS_TURBO = 1 << 4
    REV_LIMITER = 1 << 5
    HANDBRAKE = 1 << 6
    LIGHTS = 1 << 7
    HIGH_BEAM = 1 << 8
    LOW_BEAM = 1 << 9
    ASM_ACTIVE = 1 << 10
    TCS_ACTIVE = 1 << 11


@dataclass(slots=True)
class TelemetryPacket:
    packet_id: int

    # Position / motion (meters, meters/second, radians/second)
    position_x: float
    position_y: float
    position_z: float
    velocity_x: float
    velocity_y: float
    velocity_z: float
    rotation_pitch: float
    rotation_yaw: float
    rotation_roll: float
    rel_orientation_to_north: float
    angular_velocity_x: float
    angular_velocity_y: float
    angular_velocity_z: float

    body_height: float  # meters
    engine_rpm: float
    fuel_level: float
    fuel_capacity: float
    speed_mps: float
    boost: float  # bar (raw value - 1)

    oil_pressure: float
    water_temp: float
    oil_temp: float

    tire_temp_fl: float
    tire_temp_fr: float
    tire_temp_rl: float
    tire_temp_rr: float

    current_lap: int
    total_laps: int
    best_lap_time_ms: int  # -1 when not set
    last_lap_time_ms: int  # -1 when not set
    day_progression_ms: int

    race_position: int
    total_positions: int

    rpm_alert_min: float
    rpm_alert_max: float
    calculated_max_speed: int

    flags: int
    current_gear: int  # 0 = reverse/neutral handling per GT7 (15 = neutral)
    suggested_gear: int  # 15 = none
    throttle: int  # 0..255
    brake: int  # 0..255

    # Wheel angular speed (rad/s, signed) and tire radius (m)
    wheel_rps_fl: float
    wheel_rps_fr: float
    wheel_rps_rl: float
    wheel_rps_rr: float
    tire_radius_fl: float
    tire_radius_fr: float
    tire_radius_rl: float
    tire_radius_rr: float

    suspension_fl: float
    suspension_fr: float
    suspension_rl: float
    suspension_rr: float

    clutch: float
    clutch_engagement: float
    rpm_after_clutch: float
    transmission_top_speed: float
    gear_ratios: tuple[float, ...]

    car_id: int

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6

    @property
    def is_on_track(self) -> bool:
        return bool(self.flags & SimulatorFlags.CAR_ON_TRACK)

    @property
    def is_paused(self) -> bool:
        return bool(self.flags & SimulatorFlags.PAUSED)

    @property
    def is_loading(self) -> bool:
        return bool(self.flags & SimulatorFlags.LOADING)

    @property
    def throttle_pct(self) -> float:
        return self.throttle / 2.55

    @property
    def brake_pct(self) -> float:
        return self.brake / 2.55

    @property
    def tire_slip_ratio(self) -> float:
        """Average tire surface speed / car speed. ~1.0 when gripping."""
        if self.speed_mps < 1.0:
            return 1.0
        surface = (
            abs(self.wheel_rps_fl) * self.tire_radius_fl
            + abs(self.wheel_rps_fr) * self.tire_radius_fr
            + abs(self.wheel_rps_rl) * self.tire_radius_rl
            + abs(self.wheel_rps_rr) * self.tire_radius_rr
        ) / 4.0
        return surface / self.speed_mps

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
