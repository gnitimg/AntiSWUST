from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.course import CourseCategory

# 课程组持久化文件（backend/data/course_groups.json，gitignore 覆盖 backend/data/）


def _safe_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()[:30]


class GroupService:
    """课程组：把多门课程捆绑，便于在筛选栏按组快速过滤。

    存储结构：[{"id", "name", "courses": [{"cid", "name", "category"}]}]
    全局共享（单用户场景），跨会话持久化。
    """

    def __init__(self) -> None:
        self._path: Path = settings.cookie_store_dir.parent / "course_groups.json"
        self._lock = threading.Lock()
        self._groups: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            self._groups = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            self._groups = []

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._groups, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass

    def list_groups(self) -> list[dict[str, Any]]:
        return [g.copy() for g in self._groups]

    def _find(self, group_id: str) -> dict[str, Any] | None:
        return next((g for g in self._groups if g["id"] == group_id), None)

    def create(self, name: str) -> dict[str, Any]:
        group = {"id": uuid.uuid4().hex[:12], "name": _safe_name(name), "courses": []}
        with self._lock:
            self._groups.append(group)
            self._save()
        return group.copy()

    def rename(self, group_id: str, name: str) -> bool:
        with self._lock:
            group = self._find(group_id)
            if group is None:
                return False
            group["name"] = _safe_name(name)
            self._save()
            return True

    def delete(self, group_id: str) -> bool:
        with self._lock:
            before = len(self._groups)
            self._groups = [g for g in self._groups if g["id"] != group_id]
            changed = len(self._groups) < before
            if changed:
                self._save()
            return changed

    def add_course(self, group_id: str, cid: str, name: str, category: str | CourseCategory) -> bool:
        try:
            cat = category.value if isinstance(category, CourseCategory) else CourseCategory(category)
        except ValueError:
            cat = CourseCategory.GENERAL
        with self._lock:
            group = self._find(group_id)
            if group is None or not cid:
                return False
            if any(c["cid"] == cid for c in group["courses"]):
                return True  # 已存在视为成功
            group["courses"].append({"cid": cid, "name": _safe_name(name) or cid, "category": cat.value})
            self._save()
            return True

    def remove_course(self, group_id: str, cid: str) -> bool:
        with self._lock:
            group = self._find(group_id)
            if group is None:
                return False
            before = len(group["courses"])
            group["courses"] = [c for c in group["courses"] if c["cid"] != cid]
            changed = len(group["courses"]) < before
            if changed:
                self._save()
            return changed


group_service = GroupService()
