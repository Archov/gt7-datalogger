"""Declarative, byte-complete catalog for every known GT7 telemetry packet.

The catalog is deliberately independent from ``struct.Struct`` parsing.  It is the
contract used by coverage tests, normalized analysis, and export channel
catalog, and the protocol documentation.  Undocumented values keep offset-based names
so later discoveries never require pretending that a provisional meaning was fact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

PacketFormat = Literal["A", "B", "~", "C"]
FieldClass = Literal["header", "known", "unknown", "padding", "nonce", "extension"]

FORMAT_SIZES: dict[PacketFormat, int] = {"A": 296, "B": 316, "~": 344, "C": 368}
FORMAT_RANK: dict[PacketFormat, int] = {"A": 0, "B": 1, "~": 2, "C": 3}


@dataclass(frozen=True, slots=True)
class PacketField:
    names: tuple[str, ...]
    offset: int
    scalar_type: str
    count: int
    introduced: PacketFormat
    classification: FieldClass
    unit: str = "raw"
    confidence: str = "documented"
    interpretation: str = ""

    @property
    def scalar_size(self) -> int:
        return {"u8": 1, "i16": 2, "u16": 2, "i32": 4, "u32": 4, "f32": 4, "char": 1}[
            self.scalar_type
        ]

    @property
    def size(self) -> int:
        return self.scalar_size * self.count

    def applies_to(self, packet_format: PacketFormat) -> bool:
        return FORMAT_RANK[packet_format] >= FORMAT_RANK[self.introduced]


def _f(
    names: str | tuple[str, ...],
    offset: int,
    scalar_type: str,
    introduced: PacketFormat = "A",
    classification: FieldClass = "known",
    unit: str = "raw",
    confidence: str = "documented",
    interpretation: str = "",
) -> PacketField:
    values = (names,) if isinstance(names, str) else names
    return PacketField(
        values,
        offset,
        scalar_type,
        len(values),
        introduced,
        classification,
        unit,
        confidence,
        interpretation,
    )


PACKET_FIELDS: tuple[PacketField, ...] = (
    _f("magic", 0x000, "i32", classification="header", unit="hex"),
    _f(("position_x", "position_y", "position_z"), 0x004, "f32", unit="m"),
    _f(("velocity_x", "velocity_y", "velocity_z"), 0x010, "f32", unit="m/s"),
    _f(
        ("orientation_x", "orientation_y", "orientation_z", "orientation_w"),
        0x01C,
        "f32",
        unit="quaternion",
    ),
    _f(
        ("angular_velocity_x", "angular_velocity_y", "angular_velocity_z"),
        0x02C,
        "f32",
        unit="rad/s",
    ),
    _f("body_height_m", 0x038, "f32", unit="m"),
    _f("engine_rpm", 0x03C, "f32", unit="rpm"),
    _f("nonce_iv1", 0x040, "u32", classification="nonce", unit="hex"),
    _f("fuel_level", 0x044, "f32", unit="L"),
    _f("fuel_capacity", 0x048, "f32", unit="L"),
    _f("speed_mps", 0x04C, "f32", unit="m/s"),
    _f("boost_raw", 0x050, "f32", unit="bar+1"),
    _f("oil_pressure", 0x054, "f32", unit="bar"),
    _f("water_temp", 0x058, "f32", unit="degC"),
    _f("oil_temp", 0x05C, "f32", unit="degC"),
    _f(("tire_temp_fl", "tire_temp_fr", "tire_temp_rl", "tire_temp_rr"), 0x060, "f32", unit="degC"),
    _f("packet_id", 0x070, "i32", unit="sequence"),
    _f("current_lap", 0x074, "i16", unit="lap"),
    _f("total_laps", 0x076, "i16", unit="laps"),
    _f("best_lap_time_ms", 0x078, "i32", unit="ms"),
    _f("last_lap_time_ms", 0x07C, "i32", unit="ms"),
    _f("day_progression_ms", 0x080, "i32", unit="ms"),
    _f("race_position", 0x084, "i16", unit="position", confidence="community"),
    _f("total_positions", 0x086, "i16", unit="cars", confidence="community"),
    _f("rpm_alert_min", 0x088, "u16", unit="rpm"),
    _f("rpm_alert_max", 0x08A, "u16", unit="rpm"),
    _f("calculated_max_speed", 0x08C, "i16", unit="km/h"),
    _f("flags_raw", 0x08E, "u16", unit="bitmask"),
    _f("gear_bits_raw", 0x090, "u8", unit="packed nibbles"),
    _f("throttle_raw", 0x091, "u8", unit="0..255"),
    _f("brake_raw", 0x092, "u8", unit="0..255"),
    _f("padding_0x093_u8", 0x093, "u8", classification="padding"),
    _f(
        ("road_plane_x", "road_plane_y", "road_plane_z", "road_plane_distance"),
        0x094,
        "f32",
    ),
    _f(
        ("wheel_rps_fl", "wheel_rps_fr", "wheel_rps_rl", "wheel_rps_rr"), 0x0A4, "f32", unit="rad/s"
    ),
    _f(
        ("tire_radius_fl", "tire_radius_fr", "tire_radius_rl", "tire_radius_rr"),
        0x0B4,
        "f32",
        unit="m",
    ),
    _f(
        ("suspension_fl_m", "suspension_fr_m", "suspension_rl_m", "suspension_rr_m"),
        0x0C4,
        "f32",
        unit="m",
    ),
    *tuple(
        _f(
            f"unknown_0x{offset:03x}_f32",
            offset,
            "f32",
            classification="unknown",
            confidence="unknown",
        )
        for offset in range(0x0D4, 0x0F4, 4)
    ),
    _f("clutch", 0x0F4, "f32", unit="ratio"),
    _f("clutch_engagement", 0x0F8, "f32", unit="ratio"),
    _f("rpm_after_clutch", 0x0FC, "f32", unit="rpm"),
    _f("transmission_top_speed", 0x100, "f32", unit="km/h reference"),
    _f(tuple(f"gear_ratio_{index}" for index in range(1, 9)), 0x104, "f32", unit="ratio"),
    _f("car_id", 0x124, "i32", unit="id"),
    _f("steering_wheel_rad", 0x128, "f32", "B", "extension", "rad"),
    _f("steering_angular_velocity", 0x12C, "f32", "B", "extension", "rad/s"),
    _f("sway", 0x130, "f32", "B", "extension", confidence="community"),
    _f("heave", 0x134, "f32", "B", "extension", confidence="community"),
    _f("surge", 0x138, "f32", "B", "extension", confidence="community"),
    _f("throttle_filtered_raw", 0x13C, "u8", "~", "extension", "0..255"),
    _f("brake_filtered_raw", 0x13D, "u8", "~", "extension", "0..255"),
    _f("unknown_0x13e_u8", 0x13E, "u8", "~", "unknown", confidence="unknown"),
    _f("unknown_0x13f_u8", 0x13F, "u8", "~", "unknown", confidence="unknown"),
    *tuple(
        _f(
            f"unknown_0x{offset:03x}_f32",
            offset,
            "f32",
            "~",
            "unknown",
            confidence="provisional",
            interpretation=f"candidate torque vector {wheel}",
        )
        for offset, wheel in zip(range(0x140, 0x150, 4), ("FL", "FR", "RL", "RR"), strict=True)
    ),
    _f("energy_recovery", 0x150, "f32", "~", "extension", confidence="community"),
    _f("unknown_0x154_f32", 0x154, "f32", "~", "unknown", confidence="unknown"),
    _f(
        ("surface_fl_char", "surface_fr_char", "surface_rl_char", "surface_rr_char"),
        0x158,
        "char",
        "C",
        "extension",
        "ASCII",
    ),
    _f("live_lap_time_ms", 0x15C, "i32", "C", "extension", "ms"),
    _f(("steer_fl_rad", "steer_fr_rad"), 0x160, "f32", "C", "extension", "rad"),
    _f("wheelbase_m", 0x168, "f32", "C", "extension", "m"),
    _f(
        (
            "car_category_char_0",
            "car_category_char_1",
            "car_category_char_2",
            "car_category_char_3",
        ),
        0x16C,
        "char",
        "C",
        "extension",
        "ASCII",
    ),
)


def fields_for(packet_format: PacketFormat) -> tuple[PacketField, ...]:
    return tuple(field for field in PACKET_FIELDS if field.applies_to(packet_format))


def validate_packet_catalog() -> None:
    """Raise when any known packet contains an unclassified or overlapping byte."""
    for packet_format, size in FORMAT_SIZES.items():
        owners: list[str | None] = [None] * size
        for field in fields_for(packet_format):
            for offset in range(field.offset, field.offset + field.size):
                if offset >= size:
                    raise AssertionError(f"{field.names[0]} extends beyond packet {packet_format}")
                if owners[offset] is not None:
                    raise AssertionError(
                        f"packet {packet_format} byte {offset:#x} is covered twice"
                    )
                owners[offset] = field.names[0]
        missing = [offset for offset, owner in enumerate(owners) if owner is None]
        if missing:
            raise AssertionError(
                f"packet {packet_format} has uncovered bytes: "
                + ", ".join(hex(offset) for offset in missing)
            )


def catalog_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for field in PACKET_FIELDS:
        base = asdict(field)
        base.pop("names")
        for index, name in enumerate(field.names):
            row = dict(base)
            row.update(name=name, offset=field.offset + index * field.scalar_size, count=1)
            rows.append(row)
    return rows


def catalog_document() -> dict[str, object]:
    """Serializable grouped catalog used for the checked-in reference artifact."""
    fields: list[dict[str, object]] = []
    for field in PACKET_FIELDS:
        row = asdict(field)
        row["names"] = list(field.names)
        fields.append(row)
    return {
        "schema_version": 1,
        "formats": FORMAT_SIZES,
        "fields": fields,
    }


validate_packet_catalog()
