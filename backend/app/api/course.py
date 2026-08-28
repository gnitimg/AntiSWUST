from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.cookie_store import cookie_store
from app.models.course import CancelCourseRequest, CourseCategory, CourseFilter, SelectCourseRequest
from app.services.course_service import course_service
from app.services.filter_service import filter_service

router = APIRouter(prefix="/api/course", tags=["course"])


def _require(session_id: str) -> None:
    if not cookie_store.is_valid(session_id):
        raise HTTPException(status_code=401, detail="session expired or invalid")


@router.get("/categories")
async def categories() -> dict:
    return {c.value: c.label for c in CourseCategory}


@router.get("/list")
async def list_courses(session_id: str, category: CourseCategory | None = None) -> dict:
    _require(session_id)
    if category is not None:
        items = await course_service.fetch_category(session_id, category)
        return {category.value: [i.model_dump() for i in items]}
    grouped = await course_service.fetch_all(session_id)
    return {cat.value: [i.model_dump() for i in items] for cat, items in grouped.items()}


@router.post("/filter")
async def filter_courses(session_id: str, category: CourseCategory, flt: CourseFilter) -> dict:
    _require(session_id)
    items = await course_service.fetch_category(session_id, category)
    matched = filter_service.apply(items, flt)
    return {"category": category.value, "total": len(matched), "items": [i.model_dump() for i in matched]}


@router.post("/select")
async def select_course(session_id: str, req: SelectCourseRequest) -> dict:
    _require(session_id)
    return await course_service.select(session_id, req.course_id, req.category, req.weeks)


@router.post("/cancel")
async def cancel_course(session_id: str, req: CancelCourseRequest) -> dict:
    _require(session_id)
    return await course_service.cancel(session_id, req.course_id, req.category, req.chooser_id)
