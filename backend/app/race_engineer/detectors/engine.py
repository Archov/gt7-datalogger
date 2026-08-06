"""Engine-health callouts: water/oil temperature and oil pressure."""

from __future__ import annotations

from app.models import TelemetryPacket
from app.race_engineer.detectors.base import Detector, Sustained
from app.race_engineer.formatter import spoken_temperature
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext
from app.race_engineer.thresholds import (
    OIL_PRESSURE_CLEAR,
    OIL_PRESSURE_MIN,
    OIL_PRESSURE_MIN_RPM,
    OIL_TEMP_CRITICAL,
    OIL_TEMP_CRITICAL_CLEAR,
    OIL_TEMP_WARN,
    OIL_TEMP_WARN_CLEAR,
    PRESSURE_PERSISTENCE_S,
    TEMP_PERSISTENCE_S,
    WATER_CRITICAL,
    WATER_CRITICAL_CLEAR,
    WATER_WARN,
    WATER_WARN_CLEAR,
)


class EngineDetector(Detector):
    """Temperatures and pressure, each latched with hysteresis.

    The escalation from "high" to "critical" shares one dedupe key per
    quantity, so the critical call bypasses the warning's cooldown instead of
    waiting out a 20 s timer while the engine cooks.
    """

    def __init__(self) -> None:
        self._water_warn = Sustained(WATER_WARN, WATER_WARN_CLEAR, TEMP_PERSISTENCE_S)
        self._water_crit = Sustained(WATER_CRITICAL, WATER_CRITICAL_CLEAR, TEMP_PERSISTENCE_S)
        self._oil_warn = Sustained(OIL_TEMP_WARN, OIL_TEMP_WARN_CLEAR, TEMP_PERSISTENCE_S)
        self._oil_crit = Sustained(OIL_TEMP_CRITICAL, OIL_TEMP_CRITICAL_CLEAR, TEMP_PERSISTENCE_S)
        self._pressure = Sustained(
            OIL_PRESSURE_MIN, OIL_PRESSURE_CLEAR, PRESSURE_PERSISTENCE_S, above=False
        )

    def reset(self, ctx: EngineerContext) -> None:
        for s in (self._water_warn, self._water_crit, self._oil_warn, self._oil_crit,
                  self._pressure):
            s.reset()

    def on_packet(self, p: TelemetryPacket, ctx: EngineerContext) -> list[CalloutRequest]:
        if not p.is_on_track or p.is_paused:
            # Menus and replays keep streaming stale values; a paused game
            # would otherwise accumulate persistence time for free.
            self.reset(ctx)
            return []
        out: list[CalloutRequest] = []
        out += self._temperature(
            "water", p.water_temp, self._water_warn, self._water_crit, ctx
        )
        out += self._temperature("oil", p.oil_temp, self._oil_warn, self._oil_crit, ctx)
        out += self._oil_pressure(p, ctx)
        return out

    def _temperature(
        self,
        which: str,
        value: float,
        warn: Sustained,
        critical: Sustained,
        ctx: EngineerContext,
    ) -> list[CalloutRequest]:
        hot = critical.update(value, ctx.now)
        high = warn.update(value, ctx.now)
        if not hot and not high:
            return []
        level = "critical" if hot else "high"
        label = "Water temperature" if which == "water" else "Oil temperature"
        return [
            CalloutRequest(
                event_type=f"{which}_temp_{'critical' if hot else 'high'}",
                text=f"{label} {level}.",
                message_key=f"engine.{which}_temp_{level}",
                message_args={"celsius": round(value)},
                dedupe_key=f"{which}_temp:{ctx.session_seq}",
                metadata={"celsius": round(value, 1), "spoken": spoken_temperature(value)},
                severity=2 if hot else 1,
            )
        ]

    def _oil_pressure(
        self, p: TelemetryPacket, ctx: EngineerContext
    ) -> list[CalloutRequest]:
        # Pressure is only meaningful with the engine turning under load; at
        # idle (or stopped in the pits) a low reading is normal.
        if p.engine_rpm < OIL_PRESSURE_MIN_RPM or p.oil_pressure < 0:
            self._pressure.reset()
            return []
        if not self._pressure.update(p.oil_pressure, ctx.now):
            return []
        return [
            CalloutRequest(
                event_type="oil_pressure_low",
                text="Oil pressure low.",
                message_key="engine.oil_pressure_low",
                message_args={"bar": round(p.oil_pressure, 1)},
                dedupe_key=f"oil_pressure:{ctx.session_seq}",
                metadata={"bar": round(p.oil_pressure, 2), "rpm": round(p.engine_rpm)},
            )
        ]
