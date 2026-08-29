from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.cookie_store import cookie_store
from app.models.course import CancelCourseRequest, CourseCategory, CourseFilter, SelectCourseRequest
from app.services.course_service import ServicePausedError, SessionExpiredError, course_service
from app.services.filter_service import filter_service

router = APIRouter(prefix="/api/course", tags=["course"])


def _require(session_id: str) -> None:
    if not cookie_store.is_valid(session_id):
        raise HTTPException(status_code=401, detail="session expired or invalid")


def _guard(expired_detail: str = "教务系统会话已失效，请重新登录") -> None:
    """把 SessionExpiredError 转成 401（前端拦截器会清 session 并跳登录页）。"""

    def _raise(e: SessionExpiredError) -> None:
        raise HTTPException(status_code=401, detail=str(e) or expired_detail)

    return None


@router.get("/categories")
async def categories() -> dict:
    return {c.value: c.label for c in CourseCategory}


@router.get("/list")
async def list_courses(
    session_id: str, category: CourseCategory | None = None, force: bool = False, basic: bool = False
) -> dict:
    _require(session_id)
    try:
        if category is not None:
            items = await course_service.fetch_category(session_id, category, force=force, basic=basic)
            return {category.value: [i.model_dump() for i in items]}
        grouped = await course_service.fetch_all(session_id)
        return {cat.value: [i.model_dump() for i in items] for cat, items in grouped.items()}
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ServicePausedError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/selected")
async def selected_courses(session_id: str, force: bool = False) -> dict:
    """已选课程清单（含退课所需 chooser_id 等参数）。"""
    _require(session_id)
    try:
        items = await course_service.fetch_selected(session_id, force=force)
        return {"items": items}
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ServicePausedError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/filter")
async def filter_courses(session_id: str, category: CourseCategory, flt: CourseFilter) -> dict:
    _require(session_id)
    try:
        items = await course_service.fetch_category(session_id, category)
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ServicePausedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    matched = filter_service.apply(items, flt)
    return {"category": category.value, "total": len(matched), "items": [i.model_dump() for i in matched]}


@router.post("/select")
async def select_course(session_id: str, req: SelectCourseRequest) -> dict:
    _require(session_id)
    try:
        return await course_service.select(session_id, req.course_id, req.category, req.weeks)
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ServicePausedError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/cancel")
async def cancel_course(session_id: str, req: CancelCourseRequest) -> dict:
    _require(session_id)
    try:
        return await course_service.cancel(session_id, req.course_id, req.category, req.chooser_id)
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ServicePausedError as e:
        raise HTTPException(status_code=503, detail=str(e))
