from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.group_service import group_service

router = APIRouter(prefix="/api/groups", tags=["groups"])


class CreateGroupRequest(BaseModel):
    name: str


class RenameGroupRequest(BaseModel):
    name: str


class AddCourseRequest(BaseModel):
    cid: str
    name: str = ""
    category: str = "general"


@router.get("")
async def list_groups() -> dict:
    return {"items": group_service.list_groups()}


@router.post("")
async def create_group(req: CreateGroupRequest) -> dict:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="课程组名称不能为空")
    return {"group": group_service.create(name)}


@router.put("/{group_id}")
async def rename_group(group_id: str, req: RenameGroupRequest) -> dict:
    if not group_service.rename(group_id, req.name):
        raise HTTPException(status_code=404, detail="课程组不存在")
    return {"ok": True}


@router.delete("/{group_id}")
async def delete_group(group_id: str) -> dict:
    if not group_service.delete(group_id):
        raise HTTPException(status_code=404, detail="课程组不存在")
    return {"ok": True}


@router.post("/{group_id}/courses")
async def add_group_course(group_id: str, req: AddCourseRequest) -> dict:
    if not group_service.add_course(group_id, req.cid.strip(), req.name, req.category):
        raise HTTPException(status_code=404, detail="课程组不存在或课程 ID 为空")
    return {"ok": True}


@router.delete("/{group_id}/courses/{cid}")
async def remove_group_course(group_id: str, cid: str) -> dict:
    if not group_service.remove_course(group_id, cid):
        raise HTTPException(status_code=404, detail="课程组或课程不存在")
    return {"ok": True}
