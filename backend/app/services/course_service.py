from __future__ import annotations

import re
import time
from typing import Any

from parsel import Selector

from app.config import settings
from app.core.swust_client import swust_client
from app.models.course import ClassTimeSlot, CourseCategory, CourseOption


# 真实选课接口映射（来源：YDHusky/SWUST-Tools/class_spider.py 抓包验证）
# 教务系统 matrix.dean.swust.edu.cn 的 chooseCourse event 命名：
#   列表页 event=chooseCourse:{task_type}&CT={轮次}
#   教学班 event=chooseCourse:api{TaskName}Table   (POST CID=xxx)
#   选课   event=chooseCourse:apiChoose{TaskName}  (POST 选课参数)
CATEGORY_TASK: dict[CourseCategory, dict[str, str]] = {
    # 体育课
    CourseCategory.PE: {"task_type": "sportTask", "task_name": "SportTask"},
    # 全校通选课
    CourseCategory.GENERAL: {"task_type": "commonTask", "task_name": "CommonTask"},
    # 专业限选课（计划课程内）
    CourseCategory.MAJOR_LIMITED: {"task_type": "programTask", "task_name": "PlanTask"},
    # 补选低年级课程：复用 programTask，CT 取补选轮次（需按学期调整）
    CourseCategory.SUPPLEMENT: {"task_type": "programTask", "task_name": "PlanTask"},
    # 重新学习（重修）：复用 programTask，CT 取重修轮次（需按学期调整）
    CourseCategory.RETAKE: {"task_type": "programTask", "task_name": "PlanTask"},
}

# 补选/重修的 CT 轮次占位（实际需按学期选课通知调整）
CATEGORY_CT_OVERRIDE: dict[CourseCategory, int] = {
    CourseCategory.SUPPLEMENT: 3,
    CourseCategory.RETAKE: 4,
}

CHOOSE_HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
}


class CourseService:
    """选课数据抓取与解析服务（对接 matrix.dean.swust.edu.cn 真实接口）。"""

    def _ct(self, category: CourseCategory) -> int:
        return CATEGORY_CT_OVERRIDE.get(category, settings.choose_course_ct)

    async def fetch_category(self, session_id: str, category: CourseCategory) -> list[CourseOption]:
        task = CATEGORY_TASK[category]
        ct = self._ct(category)
        list_url = f"{settings.swust_dean_base_url}?event=chooseCourse:{task['task_type']}&CT={ct}"
        resp = await swust_client.get(session_id, list_url)
        courses = self._parse_course_list(resp.text, category, ct)
        # 并发抓取每个课程的教学班详情
        results: list[CourseOption] = []
        for course in courses:
            try:
                classes = await self._fetch_class_details(session_id, category, course.course_id)
                results.extend(classes)
            except Exception:
                results.append(course)
        return results

    async def fetch_all(self, session_id: str) -> dict[CourseCategory, list[CourseOption]]:
        result: dict[CourseCategory, list[CourseOption]] = {}
        for category in CourseCategory:
            try:
                result[category] = await self.fetch_category(session_id, category)
            except Exception:
                result[category] = []
        return result

    async def _fetch_class_details(
        self, session_id: str, category: CourseCategory, cid: str
    ) -> list[CourseOption]:
        task = CATEGORY_TASK[category]
        url = settings.swust_dean_base_url
        resp = await swust_client.post(
            session_id,
            url,
            params={"event": f"chooseCourse:api{task['task_name']}Table"},
            data={"CID": cid},
            headers=CHOOSE_HEADERS,
        )
        return self._parse_class_table(resp.text, category, cid)

    async def select(
        self, session_id: str, course_id: str, category: CourseCategory, weeks: list[int] | None = None
    ) -> dict[str, Any]:
        task = CATEGORY_TASK[category]
        ct = self._ct(category)
        # course_id 编码为 CID|CIDX|TID|TT|TSK|ST（由前端从列表回传）
        parts = course_id.split("|")
        if len(parts) < 6:
            return {"success": False, "message": "course_id 编码不合法"}
        cid, cidx, tid, tt, tsk, st = parts[:6]
        data: dict[str, Any] = {
            "CT": str(ct),
            "TID": tid,
            "CID": cid,
            "CIDX": cidx,
            "TSK": tsk,
            "TT": tt,
            "ST": st,
            "seed": int(time.time() * 1000),
        }
        if category == CourseCategory.MAJOR_LIMITED:
            data["CP"] = 2
        resp = await swust_client.post(
            session_id,
            settings.swust_dean_base_url,
            params={"event": f"chooseCourse:apiChoose{task['task_name']}"},
            data=data,
            headers=CHOOSE_HEADERS,
        )
        try:
            return resp.json()
        except Exception:
            return {"success": False, "message": resp.text[:200]}

    @staticmethod
    def _parse_course_list(html: str, category: CourseCategory, ct: int) -> list[CourseOption]:
        """解析课程列表页 .courseShow。"""
        sel = Selector(text=html)
        items = sel.css(".courseShow")
        options: list[CourseOption] = []
        for item in items:
            name = item.css(".name::text").get() or ""
            cid = item.css(".trigger::attr(cid)").get() or ""
            if not cid:
                continue
            options.append(
                CourseOption(
                    course_id=cid,
                    course_code="",
                    name=name.strip(),
                    category=category,
                    raw={"cid": cid, "ct": ct},
                )
            )
        return options

    @staticmethod
    def _parse_class_table(html: str, category: CourseCategory, cid: str) -> list[CourseOption]:
        """解析教学班表格 .editRows，提取选课参数与时间信息。"""
        sel = Selector(text=html)
        rows = sel.css(".editRows")
        headers = sel.css("thead td::text").getall()
        headers.insert(0, "状态")
        options: list[CourseOption] = []
        for row in rows:
            href = row.css("a::attr(href)").get()
            tds = [t.strip() for t in row.css("td::text").getall()]
            status = "已满" if not href else "空余"
            info = dict(zip(headers, [status] + tds))

            option = CourseOption(
                course_id=cid,
                course_code="",
                name=info.get("课程名称", ""),
                category=category,
                teacher=info.get("教师", ""),
                campus=info.get("校区", ""),
                class_name=info.get("教学班", ""),
                capacity=int(info.get("容量", 0) or 0),
                selected_count=int(info.get("已选", 0) or 0),
                credit=float(info.get("学分", 0) or 0),
                raw=info,
            )

            if href:
                cleaned = href.replace(" ", "")
                # chooseCourse('CID','CIDX','TID','TT','TSK','ST')
                m = re.search(r"chooseCourse\((.+)\)", cleaned)
                if m:
                    args = [a.strip("'") for a in m.group(1).split("','")]
                    if len(args) >= 6:
                        # 编码为 CID|CIDX|TID|TT|TSK|ST 供选课接口使用
                        option.course_id = "|".join(args[:6])
                        option.raw["choose_args"] = args[:6]

            # 尝试解析时间（如 "周一第1-2节{1-16周}"）
            time_str = info.get("时间", "")
            option.time_slots = CourseService._parse_time_str(time_str)
            if option.time_slots:
                option.weeks_available = sorted(
                    set(w for s in option.time_slots for w in s.weeks)
                )
            options.append(option)
        return options

    @staticmethod
    def _parse_time_str(text: str) -> list[ClassTimeSlot]:
        """解析形如 '周一第1-2节{1-16周}' 的时间字符串。"""
        slots: list[ClassTimeSlot] = []
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
        for m in re.finditer(r"周(.)第(\d+)-(\d+)节\{(\d+)-(\d+)周\}", text):
            day = day_map.get(m.group(1))
            if not day:
                continue
            slots.append(
                ClassTimeSlot(
                    day_of_week=day,
                    start_node=int(m.group(2)),
                    end_node=int(m.group(3)),
                    weeks=list(range(int(m.group(4)), int(m.group(5)) + 1)),
                )
            )
        return slots


course_service = CourseService()
