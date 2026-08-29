from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.cookie_store import cookie_store
from app.models.course import CourseCategory
from app.services.snipe_service import snipe_manager

router = APIRouter(prefix="/api/snipe", tags=["snipe"])


def _require(session_id: str) -> None:
    if not cookie_store.is_valid(session_id):
        raise HTTPException(status_code=401, detail="session expired or invalid")


class StartSnipeRequest(BaseModel):
    category: CourseCategory
    course_id: str
    cid: str = ""
    class_name: str = ""
    name: str = ""
    interval: float = 1.0
    duration: float = 600.0


class StopSnipeRequest(BaseModel):
    task_id: str


@router.post("/start")
async def start_snipe(session_id: str, req: StartSnipeRequest) -> dict:
    _require(session_id)
    task = snipe_manager.start(
        session_id=session_id,
        category=req.category,
        course_id=req.course_id,
        cid=req.cid,
        class_name=req.class_name,
        name=req.name,
        interval=req.interval,
        duration=req.duration,
    )
    return {"task": task.to_dict()}


@router.get("/tasks")
async def snipe_tasks(session_id: str) -> dict:
    _require(session_id)
    return {"items": snipe_manager.list_tasks(session_id)}


@router.post("/stop")
async def stop_snipe(session_id: str, req: StopSnipeRequest) -> dict:
    _require(session_id)
    ok = snipe_manager.stop(req.task_id)
    return {"ok": ok}


@router.post("/stop_all")
async def stop_all_snipe(session_id: str) -> dict:
    _require(session_id)
    count = snipe_manager.stop_all(session_id)
    return {"ok": True, "stopped": count}
