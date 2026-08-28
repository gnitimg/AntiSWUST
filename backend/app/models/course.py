from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CourseCategory(str, Enum):
    PE = "pe"
    GENERAL = "general"
    MAJOR_LIMITED = "major_limited"
    SUPPLEMENT = "supplement"
    RETAKE = "retake"

    @property
    def label(self) -> str:
        return {
            CourseCategory.PE: "体育课",
            CourseCategory.GENERAL: "全校通选课",
            CourseCategory.MAJOR_LIMITED: "专业限选课",
            CourseCategory.SUPPLEMENT: "补选低年级课程",
            CourseCategory.RETAKE: "重新学习（重修）",
        }[self]


class ClassTimeSlot(BaseModel):
    day_of_week: int = Field(..., ge=1, le=7, description="星期几 1-7")
    start_node: int = Field(..., ge=1, description="起始节次")
    end_node: int = Field(..., ge=1, description="结束节次")
    weeks: list[int] = Field(default_factory=list, description="上课周次列表")


class CourseOption(BaseModel):
    """一个可选课程条目（一个老师/一个班/一组时间）。"""
    course_id: str
    course_code: str = ""
    name: str
    category: CourseCategory
    teacher: str = ""
    campus: str = ""
    class_name: str = ""
    capacity: int = 0
    selected_count: int = 0
    credit: float = 0.0
    time_slots: list[ClassTimeSlot] = Field(default_factory=list)
    weeks_available: list[int] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.selected_count)


class CourseFilter(BaseModel):
    """多维筛选条件。所有字段为可选，留空表示不限制。"""
    name: str | None = None
    teacher: str | None = None
    campus: str | None = None
    day_of_week: int | None = None
    node: int | None = None
    weeks: list[int] | None = None
    min_remaining: int | None = None
    only_available: bool = True


class SelectCourseRequest(BaseModel):
    course_id: str
    category: CourseCategory
    weeks: list[int] | None = None


class CancelCourseRequest(BaseModel):
    course_id: str
    category: CourseCategory
    chooser_id: str = ""
