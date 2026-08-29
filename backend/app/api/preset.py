from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.cookie_store import cookie_store
from app.models.course import CourseCategory
from app.services.preset_service import preset_service

router = APIRouter(prefix="/api/preset", tags=["preset"])


def _require(session_id: str) -> None:
    if not cookie_store.is_valid(session_id):
        raise HTTPException(status_code=401, detail="session expired or invalid")


class PresetEntryIn(BaseModel):
    category: CourseCategory = CourseCategory.PE
    name: str
    teacher: str = ""
    class_name: str = ""
    campus: str = ""
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    node: int | None = Field(default=None, ge=1)
    priority: int | None = None
    enabled: bool = True


class ImportRequest(BaseModel):
    content: str
    category: CourseCategory = CourseCategory.PE


class RunStartRequest(BaseModel):
    """start_at 为选课开放时间（epoch 秒），不填则立即开始。"""

    start_at: float | None = None
    retry: bool = True
    interval: float = 5.0
    stop_same_category: bool = True


@router.get("")
async def list_presets() -> dict:
    return {"items": preset_service.list_entries()}


@router.post("")
async def create_preset(entry: PresetEntryIn) -> dict:
    if not entry.name.strip():
        raise HTTPException(status_code=400, detail="课程名不能为空")
    return {"entry": preset_service.add_entry(entry.model_dump())}


@router.put("/{entry_id}")
async def update_preset(entry_id: str, entry: PresetEntryIn) -> dict:
    if not preset_service.update_entry(entry_id, entry.model_dump()):
        raise HTTPException(status_code=404, detail="预置条目不存在")
    return {"ok": True}


@router.delete("/{entry_id}")
async def delete_preset(entry_id: str) -> dict:
    if not preset_service.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="预置条目不存在")
    return {"ok": True}


@router.post("/import")
async def import_presets(req: ImportRequest) -> dict:
    created = preset_service.import_csv(req.content, req.category)
    return {"imported": len(created), "items": created}


@router.post("/run/start")
async def start_preset_run(session_id: str, req: RunStartRequest) -> dict:
    _require(session_id)
    run = preset_service.start_run(
        session_id,
        start_at=req.start_at,
        retry=req.retry,
        interval=req.interval,
        stop_same_category=req.stop_same_category,
    )
    return {"run": run}


@router.post("/run/stop")
async def stop_preset_run(session_id: str) -> dict:
    _require(session_id)
    return {"ok": preset_service.stop_run(session_id)}


@router.get("/run")
async def get_preset_run(session_id: str) -> dict:
    _require(session_id)
    return {"run": preset_service.get_run(session_id)}
