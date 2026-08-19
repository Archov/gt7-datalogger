"""Process-local decoder counters mirrored into the disposable metrics database."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DecoderDiagnostics:
    decode_errors: int = 0
    unsupported_lengths: int = 0
    latest_diagnostic: str | None = None


_state = DecoderDiagnostics()


def record_decode_error(message: str) -> None:
    _state.decode_errors += 1
    _state.latest_diagnostic = message


def record_unsupported_length(length: int, source: str = "parser") -> None:
    _state.unsupported_lengths += 1
    _state.latest_diagnostic = f"{source}: unsupported packet length {length}"


def decoder_diagnostics() -> DecoderDiagnostics:
    return DecoderDiagnostics(
        decode_errors=_state.decode_errors,
        unsupported_lengths=_state.unsupported_lengths,
        latest_diagnostic=_state.latest_diagnostic,
    )
