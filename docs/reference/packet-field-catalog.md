# Packet field catalog

The authoritative catalog is the declarative registry in
`backend/app/telemetry/packet_catalog.py`. Parser decoding, byte-coverage assertions, the
normalized lap schema, per-lap provenance, and export tooling all consume it. The
runtime `channel_catalog` table is its queryable generated form and includes one row for
each scalar component. The checked-in machine-readable snapshot is
[`packet-field-catalog.json`](packet-field-catalog.json); regenerate it with
`python scripts/export_packet_catalog.py` from the `backend` directory.

GT7 has no official public telemetry specification. Known meanings are cross-checked
against community implementations, while uncertain values remain named by byte offset.
An interpretation marked `provisional` is not a replacement for the native value.
See the [MacManley parser](https://github.com/MacManley/gt7-udp) and
[zetetos parser](https://github.com/zetetos/gt-telemetry) for the community references.

## Formats and exact lengths

| Format | Bytes | Added range |
| --- | ---: | --- |
| A | 296 (`0x128`) | Base packet `0x000`–`0x127` |
| B | 316 (`0x13c`) | Steering and motion `0x128`–`0x13b` |
| `~` | 344 (`0x158`) | Filtered inputs, unknowns, energy `0x13c`–`0x157` |
| C | 368 (`0x170`) | Surfaces, timer, front steer, wheelbase, category `0x158`–`0x16f` |

Only these exact lengths are accepted. Every byte is classified exactly once as header,
known, unknown, padding, nonce, or extension. A longer datagram is unsupported—not a C
packet with an ignored tail.

## Offset map

| Range | Native contents |
| --- | --- |
| `0x000`–`0x03f` | magic, XYZ position/velocity, quaternion, XYZ angular velocity, body height, RPM |
| `0x040`–`0x08f` | nonce, fuel, m/s speed, raw boost, pressure/temperatures, packet/race/lap state, RPM thresholds, flags |
| `0x090`–`0x0d3` | packed gears, raw inputs, padding `0x093`, road plane, wheel angular speeds, tire radii, suspension meters |
| `0x0d4`–`0x0f3` | eight authoritative unknown float32 values |
| `0x0f4`–`0x127` | clutch values, transmission setup, eight gear ratios, car ID |
| `0x128`–`0x13b` | B steering wheel angle/velocity and sway, heave, surge |
| `0x13c`–`0x157` | `~` filtered raw inputs, unknown bytes, four unknown float32 candidates, energy recovery, `unknown_0x154_f32` |
| `0x158`–`0x16f` | C per-wheel surface chars, live lap timer, two front steering angles, wheelbase, four raw category chars |

Native floats are unpacked as float32 and inserted without decimal rounding. Native
integers and characters retain their storage type. The database also preserves the raw
and transformed sides of speed, throttle/brake, boost, suspension, wheel slip, surfaces,
packed gears, and all 16 flag bits. Unavailable extension values are SQL `NULL`.
