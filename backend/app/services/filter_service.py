from __future__ import annotations

from app.models.course import CourseFilter, CourseOption


class FilterService:
    """课程多维筛选服务。"""

    def apply(self, items: list[CourseOption], flt: CourseFilter) -> list[CourseOption]:
        result: list[CourseOption] = []
        for item in items:
            if not self._match(item, flt):
                continue
            result.append(item)
        return result

    def _match(self, item: CourseOption, flt: CourseFilter) -> bool:
        if flt.only_available and item.remaining <= 0:
            return False
        if flt.min_remaining is not None and item.remaining < flt.min_remaining:
            return False
        if flt.name and flt.name.strip() and flt.name.strip() not in item.name:
            return False
        if flt.teacher and flt.teacher.strip() and flt.teacher.strip() not in item.teacher:
            return False
        if flt.campus and flt.campus.strip() and flt.campus.strip() not in item.campus:
            return False
        if flt.day_of_week is not None:
            if not any(slot.day_of_week == flt.day_of_week for slot in item.time_slots):
                return False
        if flt.node is not None:
            if not any(slot.start_node <= flt.node <= slot.end_node for slot in item.time_slots):
                return False
        if flt.weeks:
            if not any(set(flt.weeks) & set(slot.weeks) for slot in item.time_slots):
                return False
        return True


filter_service = FilterService()
