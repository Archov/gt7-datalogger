"""CRUD for named overlay/dashboard layouts (v2 grid configs).

Server-side validation is deliberately light — a shape check and a size cap.
The client normalizes layout JSON on read (normalizeLayout), so the server
only has to keep obviously broken or oversized blobs out of the table.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.service import TelemetryService

router = APIRouter(prefix="/api/layouts")

MAX_CONFIG_BYTES = 64 * 1024


def svc(request: Request) -> TelemetryService:
    service: TelemetryService = request.app.state.service
    return service


class LayoutPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["overlay", "dash"] = "overlay"
    config: dict[str, Any]


class LayoutPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: dict[str, Any] | None = None


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != 2:
        raise HTTPException(400, "layout config must have version 2")
    if len(json.dumps(config, separators=(",", ":"))) > MAX_CONFIG_BYTES:
        raise HTTPException(400, "layout config too large")


@router.get("")
async def list_layouts(request: Request) -> list[dict[str, Any]]:
    return await svc(request).repo.list_layouts()


@router.get("/{ref}")
async def get_layout(request: Request, ref: str) -> dict[str, Any]:
    layout = await svc(request).repo.get_layout(ref)
    if layout is None:
        raise HTTPException(404, "layout not found")
    return layout


@router.post("")
async def create_layout(request: Request, payload: LayoutPayload) -> dict[str, Any]:
    _validate_config(payload.config)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "layout name cannot be blank")
    repo = svc(request).repo
    if await repo.get_layout_by_name(name) is not None:
        raise HTTPException(409, f'a layout named "{name}" already exists')
    return await repo.create_layout(name, payload.kind, payload.config)


@router.put("/{layout_id}")
async def update_layout(
    request: Request, layout_id: int, patch: LayoutPatch
) -> dict[str, Any]:
    repo = svc(request).repo
    name = patch.name.strip() if patch.name is not None else None
    if name is not None:
        if not name:
            raise HTTPException(400, "layout name cannot be blank")
        existing = await repo.get_layout_by_name(name)
        if existing is not None and existing["id"] != layout_id:
            raise HTTPException(409, f'a layout named "{name}" already exists')
    if patch.config is not None:
        _validate_config(patch.config)
    updated = await repo.update_layout(layout_id, name=name, config=patch.config)
    if updated is None:
        raise HTTPException(404, "layout not found")
    return updated


@router.delete("/{layout_id}")
async def delete_layout(request: Request, layout_id: int) -> dict[str, str]:
    await svc(request).repo.delete_layout(layout_id)
    return {"status": "deleted"}
