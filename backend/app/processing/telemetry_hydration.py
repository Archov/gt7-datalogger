"""Durable, session-scoped hydration of normalized telemetry from raw archives."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from app.processing.laps import SAMPLE_COLUMNS
from app.processing.orientation import ORIENTATION_CHANNELS
from app.processing.telemetry_resolution import (
    persisted_session_view,
    resolve_session_telemetry,
)
from app.storage.repository import Repository

log = logging.getLogger(__name__)

HYDRATION_SCHEMA_VERSION = 1
HydrationMode = Literal["stale_only", "retry_incomplete", "force_all"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def archive_fingerprint(data_root: Path, metadata: object) -> str:
    """Stable fingerprint including archive metadata and current file identity."""
    value = metadata if isinstance(metadata, dict) else {}
    relevant = {
        key: value.get(key)
        for key in (
            "path",
            "version",
            "status",
            "complete",
            "packet_count",
            "payload_bytes",
            "stored_bytes",
            "finalized_at",
        )
    }
    relative = relevant.get("path")
    if isinstance(relative, str) and relative:
        root = data_root.resolve()
        candidate = (root / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            stat = candidate.stat()
            relevant["file_size"] = stat.st_size
            relevant["file_mtime_ns"] = stat.st_mtime_ns
        else:
            relevant["file_missing"] = True
    raw = json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_current(metadata: object, fingerprint: str) -> bool:
    return (
        isinstance(metadata, dict)
        and metadata.get("version") == HYDRATION_SCHEMA_VERSION
        and metadata.get("archive_fingerprint") == fingerprint
    )


def _missing_requested(bundle: dict[str, Any], requested: set[str]) -> bool:
    view = persisted_session_view(bundle, requested)
    provenance = cast(dict[int, dict[str, list[str]]], view["channel_provenance"])
    return any(state["unavailable"] for state in provenance.values())


def _selected_view(
    bundle: dict[str, Any], lap_ids: set[int], requested: set[str]
) -> dict[str, Any]:
    selected = dict(bundle)
    selected["laps"] = [lap for lap in bundle.get("laps") or [] if int(lap["id"]) in lap_ids]
    return persisted_session_view(selected, requested)


def _replay_all_channels(
    bundle: dict[str, Any], data_root: Path, force_replay: bool
) -> dict[str, Any]:
    """Run the parser/LapProcessor replay in a worker-owned event loop."""
    coroutine = (
        resolve_session_telemetry(bundle, set(SAMPLE_COLUMNS), data_root, force_replay=True)
        if force_replay
        else resolve_session_telemetry(bundle, set(SAMPLE_COLUMNS), data_root)
    )
    return asyncio.run(coroutine)


class TelemetryHydrationManager:
    """Coordinates durable on-demand hydration and the Admin bulk job."""

    def __init__(self, repo: Repository, data_root: Path) -> None:
        self.repo = repo
        self.data_root = data_root
        self._locks: dict[int, asyncio.Lock] = {}
        self._job: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._job_status: dict[str, Any] = self._idle_status()

    @staticmethod
    def _idle_status() -> dict[str, Any]:
        return {
            "state": "idle",
            "mode": None,
            "total_sessions": 0,
            "processed_sessions": 0,
            "hydrated_sessions": 0,
            "complete_sessions": 0,
            "partial_sessions": 0,
            "failed_sessions": 0,
            "skipped_sessions": 0,
            "current_session_id": None,
            "started_at": None,
            "finished_at": None,
            "latest_diagnostic": None,
        }

    @property
    def running(self) -> bool:
        return self._job is not None and not self._job.done()

    def status(self) -> dict[str, Any]:
        return dict(self._job_status)

    async def resolve(self, bundle: dict[str, Any], requested_channels: set[str]) -> dict[str, Any]:
        """Hydrate once when needed, then return a persisted-only view."""
        requested = set(requested_channels).intersection(SAMPLE_COLUMNS)
        lap_ids = {int(lap["id"]) for lap in bundle.get("laps") or []}
        if not requested or not _missing_requested(bundle, requested):
            return persisted_session_view(bundle, requested)
        session_id = int((bundle.get("session") or {})["id"])
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            current = await self.repo.get_session_analysis_data(session_id)
            if current is None:
                return persisted_session_view(bundle, requested)
            if not _missing_requested(current, requested):
                return _selected_view(current, lap_ids, requested)
            fingerprint = archive_fingerprint(self.data_root, current.get("raw_archive_meta"))
            if _is_current(current.get("telemetry_hydration_meta"), fingerprint):
                return _selected_view(current, lap_ids, requested)
            await self._hydrate_locked(current, fingerprint)
            refreshed = await self.repo.get_session_analysis_data(session_id)
            return _selected_view(refreshed or current, lap_ids, requested)

    async def _hydrate_locked(
        self,
        bundle: dict[str, Any],
        fingerprint: str,
        *,
        force_replay: bool = False,
    ) -> dict[str, Any]:
        session_id = int((bundle.get("session") or {})["id"])
        resolved = await asyncio.to_thread(
            _replay_all_channels, bundle, self.data_root, force_replay
        )
        report = cast(dict[str, Any], resolved.get("_telemetry_resolution") or {})
        outcome = str(report.get("status") or "failed")
        if outcome == "not_needed":
            outcome = "complete"
        updates: dict[int, dict[str, list[float]]] = {}
        expected: dict[int, tuple[int, int, int, list[float]]] = {}
        original_by_id = {int(lap["id"]): lap for lap in bundle.get("laps") or []}
        provenance = cast(dict[int, dict[str, list[str]]], resolved.get("channel_provenance") or {})
        for lap in resolved.get("laps") or []:
            lap_id = int(lap["id"])
            original = original_by_id.get(lap_id)
            if original is None:
                continue
            samples = cast(dict[str, list[float]], lap.get("samples") or {})
            recovered = provenance.get(lap_id, {}).get("archive_replay", [])
            if recovered:
                updates[lap_id] = {
                    channel: list(samples[channel]) for channel in recovered if channel in samples
                }
            original_samples = cast(dict[str, list[float]], original.get("samples") or {})
            expected[lap_id] = (
                int(lap["car_id"]),
                int(lap["number"]),
                int(lap["time_ms"]),
                list(original_samples.get("t") or []),
            )
        diagnostic = report.get("error")
        metadata: dict[str, object] = {
            "version": HYDRATION_SCHEMA_VERSION,
            "archive_fingerprint": fingerprint,
            "status": outcome if outcome in {"complete", "partial"} else "failed",
            "attempted_at": _now(),
            "completed_at": _now(),
            "lap_count": len(bundle.get("laps") or []),
            "matched_lap_count": len(report.get("matched_lap_ids") or []),
            "skipped_lap_count": len(report.get("skipped_lap_ids") or []),
            "recovered_channel_count": int(report.get("recovered_channel_count") or 0),
            "diagnostic": str(diagnostic)[:240] if diagnostic else None,
        }
        replace = set(ORIENTATION_CHANNELS) | {"surface"}
        committed, changed = await self.repo.persist_session_hydration(
            session_id,
            updates,
            expected,
            metadata,
            replace_channels=replace,
        )
        if not committed:
            return {"status": "failed", "diagnostic": "session_changed_during_hydration"}
        return {"status": metadata["status"], "changed_channels": changed}

    async def start_job(self, mode: HydrationMode) -> dict[str, Any]:
        if self.running:
            raise RuntimeError("archive hydration is already running")
        self._stop_requested = False
        self._job_status = self._idle_status()
        self._job_status.update(state="running", mode=mode, started_at=_now())
        self._job = asyncio.create_task(self._run_job(mode), name="archive-hydration")
        return self.status()

    async def _run_job(self, mode: HydrationMode) -> None:
        try:
            archives = sorted(await self.repo.list_session_archive_metadata())
            self._job_status["total_sessions"] = len(archives)
            for session_id, archive_meta in archives:
                if self._stop_requested:
                    self._job_status["state"] = "cancelled"
                    break
                self._job_status["current_session_id"] = session_id
                try:
                    bundle = await self.repo.get_session_analysis_data(session_id)
                    if bundle is None:
                        result = {"status": "skipped", "diagnostic": "session_missing"}
                    elif (
                        archive_meta.get("status") != "complete"
                        or archive_meta.get("complete") is not True
                    ):
                        result = {"status": "skipped", "diagnostic": "archive_incomplete"}
                    else:
                        fingerprint = archive_fingerprint(self.data_root, archive_meta)
                        current_meta = bundle.get("telemetry_hydration_meta")
                        current = _is_current(current_meta, fingerprint)
                        current_status = (
                            current_meta.get("status") if isinstance(current_meta, dict) else None
                        )
                        process = (
                            mode == "force_all"
                            or not current
                            or (mode == "retry_incomplete" and current_status != "complete")
                        )
                        if not process:
                            result = {"status": "skipped", "diagnostic": "already_current"}
                        else:
                            lock = self._locks.setdefault(session_id, asyncio.Lock())
                            async with lock:
                                latest = await self.repo.get_session_analysis_data(session_id)
                                result = (
                                    await self._hydrate_locked(
                                        latest, fingerprint, force_replay=True
                                    )
                                    if latest is not None
                                    else {"status": "skipped", "diagnostic": "session_missing"}
                                )
                    status = str(result.get("status"))
                except Exception as exc:  # noqa: BLE001 - one archive must not stop the job
                    log.exception("archive hydration failed for session %s", session_id)
                    status = "failed"
                    result = {"diagnostic": type(exc).__name__}
                self._job_status["processed_sessions"] += 1
                if status in {"complete", "partial"}:
                    self._job_status["hydrated_sessions"] += 1
                key = {
                    "complete": "complete_sessions",
                    "partial": "partial_sessions",
                    "failed": "failed_sessions",
                    "skipped": "skipped_sessions",
                }.get(status, "failed_sessions")
                self._job_status[key] += 1
                self._job_status["latest_diagnostic"] = result.get("diagnostic")
                await asyncio.sleep(0)
            else:
                self._job_status["state"] = "completed"
        except asyncio.CancelledError:
            self._job_status["state"] = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - expose a stable job-level failure
            log.exception("archive hydration job failed")
            self._job_status["state"] = "failed"
            self._job_status["latest_diagnostic"] = type(exc).__name__
        finally:
            self._job_status["current_session_id"] = None
            self._job_status["finished_at"] = _now()

    async def stop(self) -> None:
        self._stop_requested = True
        task = self._job
        if task is not None and not task.done():
            # A to_thread replay cannot be force-cancelled. Let the current
            # session finish, then stop before the next one so archive deletion
            # and engine disposal never race an open worker-side reader.
            await asyncio.gather(task, return_exceptions=True)
