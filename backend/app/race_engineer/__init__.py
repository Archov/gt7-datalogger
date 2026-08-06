"""Race Engineer: telemetry conditions turned into spoken callouts.

Detection and every rule about *whether* something is worth saying live here,
on the backend, so behavior is identical on every client and deployment. The
browser only receives validated events and speaks them (see
frontend/src/lib/speech.ts) — the server never needs an audio device.
"""

from app.race_engineer.manager import RaceEngineerManager
from app.race_engineer.models import (
    CATEGORIES,
    DEFAULT_VERBOSITY,
    SPECS,
    VERBOSITY_MODES,
    VoiceCallout,
    parse_categories,
)

__all__ = [
    "CATEGORIES",
    "DEFAULT_VERBOSITY",
    "SPECS",
    "VERBOSITY_MODES",
    "RaceEngineerManager",
    "VoiceCallout",
    "parse_categories",
]
