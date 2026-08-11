# Raw telemetry archive (`.gt7r`)

Raw archives preserve the complete decrypted GT7 packet payload before the typed parser
selects fields. They are the lossless source for future parser discoveries. SQLite lap
samples remain the efficient interpreted form used by the UI and analysis, while the LLM
JSON remains a curated analytical export; neither contains the raw packet stream.

Archival is enabled by default. Live sessions append to
`data/raw/session-<id>.gt7r`; a clean session boundary or application shutdown produces
`session-<id>.gt7r.zip`. A crash leaves the uncompressed file intact and readable through
its final complete record. Session deletion removes its associated archive.

Only payloads that pass GT7 Salsa20 decryption and magic validation are archived. The
stored bytes are exactly those supplied to `parse_packet`, including reserved bytes and
bytes beyond the newest packet layout understood by this release. An unfamiliar size is
not truncated or rejected merely for being unfamiliar.

## Version 1 binary layout

All integers are little-endian. Sizes declared in headers include the header itself.

File header (`<8sHHQ`, currently 20 bytes):

| Field | Type | Meaning |
| --- | --- | --- |
| magic | 8 bytes | `GT7RAW\0\0` |
| version | `uint16` | container version, currently 1 |
| header size | `uint16` | total file-header bytes |
| creation Unix ns | `uint64` | wall clock sampled with the first payload |

Each record begins with `<4sHHQQIiiBBHI` (currently 44 bytes):

| Field | Type | Meaning |
| --- | --- | --- |
| magic | 4 bytes | `PKT1` |
| header size | `uint16` | total record-header bytes |
| flags | `uint16` | reserved, currently zero |
| monotonic offset ns | `uint64` | time since the first archived payload |
| order | `uint64` | receiver order supplied by the source |
| payload length | `uint32` | following payload bytes |
| packet ID | `int32` | parsed GT7 packet counter, or `-1` |
| lap number | `int32` | parsed race lap, or `-1` |
| source | `uint8` | 1 UDP, 2 simulator |
| packet format | `uint8` | 0 unknown, 1 A, 2 B, 3 `~`, 4 C |
| reserved | `uint16` | zero |
| CRC32 | `uint32` | checksum of the payload |
| payload | variable | exact decrypted telemetry payload |

Readers honor both header-size fields: they read the known v1 prefix and skip declared
extensions. A version they do not support is rejected instead of guessed. Payload lengths
are limited to 1 MiB while reading so corrupt files cannot request unbounded allocation.

Approximate absolute receive time is `creation_unix_ns + monotonic_offset_ns`. Relative
timing uses the monotonic clock and is therefore unaffected by wall-clock adjustments
during a session; the absolute result is intentionally approximate.

At 60 packets/second, framing plus current payloads uses approximately 70 MiB/hour for
Packet A and 85 MiB/hour for Packet C before ZIP compression.

## Reading and replaying

```python
from pathlib import Path

from app.telemetry.packet import parse_packet
from app.telemetry.raw_archive import RawArchiveReader

for record in RawArchiveReader(Path("data/raw/session-8.gt7r.zip")):
    packet = parse_packet(record.payload)
    print(record.order, record.approximate_unix_ns, packet.packet_id)
```

`replay_archive(path, callback, preserve_timing=True)` provides an async transport-free
replay path and can scale delays with its `speed` argument.

The normal reader stops before a truncated final header or payload and then reports
`truncated_tail = True`. Strict mode raises `TruncatedArchiveError`. Bad magic, CRC,
unsupported versions, and unreasonable lengths always raise an archive error. Earlier
complete records are never fabricated or changed.

Disable new-session archival with `GT7_RAW_ARCHIVE=false` or **Admin → Raw packet
archive**. Runtime changes apply at the next session boundary, so an existing archive is
not made deliberately ragged.
