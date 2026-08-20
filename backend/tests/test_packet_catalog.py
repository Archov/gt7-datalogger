"""Byte coverage and lossless native-field decoding for the protocol registry."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from app.telemetry.packet import build_packet, parse_packet
from app.telemetry.packet_catalog import (
    FORMAT_SIZES,
    catalog_document,
    catalog_rows,
    validate_packet_catalog,
)


def test_every_known_packet_byte_is_classified_exactly_once() -> None:
    validate_packet_catalog()
    rows = catalog_rows()
    assert {row["introduced"] for row in rows} == {"A", "B", "~", "C"}
    assert {row["name"] for row in rows} >= {
        "unknown_0x0d4_f32",
        "unknown_0x154_f32",
        "padding_0x093_u8",
        "surface_fl_char",
        "car_category_char_3",
    }


def test_checked_in_catalog_matches_registry() -> None:
    path = Path(__file__).parents[2] / "docs" / "reference" / "packet-field-catalog.json"
    assert json.loads(path.read_text(encoding="utf-8")) == catalog_document()


@pytest.mark.parametrize("packet_format,size", FORMAT_SIZES.items())
def test_packet_length_is_detected_exactly(packet_format: str, size: int) -> None:
    packet = parse_packet(build_packet(fmt=packet_format))
    assert packet.packet_format == packet_format
    assert packet.packet_size == size


def test_unknown_fields_and_all_flag_bits_retain_exact_native_values() -> None:
    payload = bytearray(build_packet(fmt="C"))
    struct.pack_into("<f", payload, 0x0D4, 123.25)
    struct.pack_into("<f", payload, 0x140, -17.5)
    struct.pack_into("<f", payload, 0x154, 81.125)
    struct.pack_into("<H", payload, 0x08E, 0xA55A)
    payload[0x093] = 0x7E
    payload[0x13E] = 0x91
    payload[0x13F] = 0x42

    packet = parse_packet(bytes(payload))
    assert packet.native_fields["unknown_0x0d4_f32"] == 123.25
    assert packet.native_fields["unknown_0x140_f32"] == -17.5
    assert packet.native_fields["unknown_0x154_f32"] == 81.125
    assert packet.native_fields["padding_0x093_u8"] == 0x7E
    assert packet.native_fields["unknown_0x13e_u8"] == 0x91
    assert packet.native_fields["unknown_0x13f_u8"] == 0x42
    assert packet.flags_raw == 0xA55A
    assert packet.flag_bits == tuple(bool(0xA55A & (1 << bit)) for bit in range(16))


@pytest.mark.parametrize("size", [0, 295, 297, 315, 317, 343, 345, 367, 369, 512])
def test_unknown_or_extended_lengths_are_never_truncated(size: int) -> None:
    with pytest.raises(ValueError, match="unsupported packet size"):
        parse_packet(bytes(size))
