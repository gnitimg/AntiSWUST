from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from parsel import Selector

from app.config import settings
from app.core.swust_client import swust_client
from app.models.course import ClassTimeSlot, CourseCategory, CourseOption


# 真实选课接口映射（2026-08-28 实测，来源：Chrome DevTools Protocol 抓取五个分类列表页 JS）
# 教务系统 matrix.dean.swust.edu.cn 的 chooseCourse event 命名：
#   列表页   event=chooseCourse:{task_type}&CT={轮次}
#   教学班   event=chooseCourse:{table_api}   (POST TID/CID/seed)
#   选课     event=chooseCourse:{choose_api}  (POST CT/TID/CID/CIDX/TSK/TT/ST[/CP]/seed)
#   取消     event=chooseCourse:apiCancelTask (POST CT/TID/CID/CIDX/TSK/TT/ST/SCC/seed)
# 注意：sportTask/commonTask/programTask 选课 API 带 Choose 前缀，fixupTask/retakeTask 不带。
CATEGORY_TASK: dict[CourseCategory, dict[str, str]] = {
    # 体育课
    CourseCategory.PE: {"task_type": "sportTask", "table_api": "apiSportTaskTable", "choose_api": "apiChooseSportTask"},
    # 全校通选课
    CourseCategory.GENERAL: {"task_type": "commonTask", "table_api": "apiCommonTaskTable", "choose_api": "apiChooseCommonTask"},
    # 专业限选课（计划课程）
    CourseCategory.MAJOR_LIMITED: {"task_type": "programTask", "table_api": "apiPlanTaskTable", "choose_api": "apiChoosePlanTask"},
    # 补选低年级课程
    CourseCategory.SUPPLEMENT: {"task_type": "fixupTask", "table_api": "apiFixupPlanTaskTable", "choose_api": "apiFixupPlanTask"},
    # 重新学习（重修）
    CourseCategory.RETAKE: {"task_type": "retakeTask", "table_api": "apiRetakePlanTaskTable", "choose_api": "apiRetakePlanTask"},
}

# 取消选课 API（五个分类统一）
CANCEL_API = "apiCancelTask"

# 补选/重修的 CT 轮次占位（实际需按学期选课通知调整；2026-08-28 实测均为 2）
CATEGORY_CT_OVERRIDE: dict[CourseCategory, int] = {
    CourseCategory.SUPPLEMENT: 2,
    CourseCategory.RETAKE: 2,
}

CHOOSE_HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
}


class CourseService:
    """选课数据抓取与解析服务（对接 matrix.dean.swust.edu.cn 真实接口）。"""

    _cache: dict[tuple[str, str], tuple[float, list[CourseOption]]] = {}
    _cache_ttl: float = 60.0

    def _ct(self, category: CourseCategory) -> int:
        return CATEGORY_CT_OVERRIDE.get(category, settings.choose_course_ct)

    async def fetch_category(self, session_id: str, category: CourseCategory) -> list[CourseOption]:
        # 短期缓存：60 秒内同一 session+分类直接返回缓存
        cache_key = (session_id, category.value)
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < self._cache_ttl:
            return cached[1]

        task = CATEGORY_TASK[category]
        ct = self._ct(category)
        list_url = f"{settings.swust_dean_base_url}?event=chooseCourse:{task['task_type']}&CT={ct}"
        resp = await swust_client.get(session_id, list_url)
        tid = self._extract_tid(resp.text)
        courses = self._parse_course_list(resp.text, category, ct)
        # 并行抓取教学班详情（限制 40 并发）
        sem = asyncio.Semaphore(40)

        async def fetch_one(course: CourseOption) -> list[CourseOption]:
            async with sem:
                try:
                    return await self._fetch_class_details(
                        session_id, category, course.course_id, tid, course.name, course.credit
                    )
                except Exception:
                    return [course]

        gathered = await asyncio.gather(*(fetch_one(c) for c in courses))
        results: list[CourseOption] = []
        for classes in gathered:
            results.extend(classes)
        self._cache[cache_key] = (time.time(), results)
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
        self, session_id: str, category: CourseCategory, cid: str, tid: str = "",
        course_name: str = "", course_credit: float = 0.0,
    ) -> list[CourseOption]:
        task = CATEGORY_TASK[category]
        url = settings.swust_dean_base_url
        data: dict[str, Any] = {"CID": cid, "seed": int(time.time() * 1000)}
        if tid:
            data["TID"] = tid
        resp = await swust_client.post(
            session_id,
            url,
            params={"event": f"chooseCourse:{task['table_api']}"},
            data=data,
            headers=CHOOSE_HEADERS,
        )
        return self._parse_class_table(resp.text, category, cid, course_name, course_credit)

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
        # fixupTask/retakeTask 需 CP（课程性质，从 course_id 编码第 7 段或 prop 取）
        if category in (CourseCategory.SUPPLEMENT, CourseCategory.RETAKE) and len(parts) >= 7:
            data["CP"] = parts[6]
        resp = await swust_client.post(
            session_id,
            settings.swust_dean_base_url,
            params={"event": f"chooseCourse:{task['choose_api']}"},
            data=data,
            headers=CHOOSE_HEADERS,
        )
        try:
            return resp.json()
        except Exception:
            return {"success": False, "message": resp.text[:200]}

    async def cancel(
        self, session_id: str, course_id: str, category: CourseCategory, chooser_id: str = ""
    ) -> dict[str, Any]:
        """取消选课（退课）。五个分类统一用 apiCancelTask。

        course_id 编码: CID|CIDX|TID|TT|TSK|ST（同 select）
        chooser_id: SCC 参数，来自已选课程表的 removeTask 调用第 1 个参数（学号+cid+termId+taskType 拼接）
        """
        ct = self._ct(category)
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
            "SCC": chooser_id,
            "seed": int(time.time() * 1000),
        }
        resp = await swust_client.post(
            session_id,
            settings.swust_dean_base_url,
            params={"event": f"chooseCourse:{CANCEL_API}"},
            data=data,
            headers=CHOOSE_HEADERS,
        )
        try:
            return resp.json()
        except Exception:
            return {"success": False, "message": resp.text[:200]}

    @staticmethod
    def _extract_tid(html: str) -> str:
        """从列表页 JS 提取学期 ID TID（形如 'TID' : '261'）。"""
        m = re.search(r"'TID'\s*:\s*'(\d+)'", html)
        return m.group(1) if m else ""

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
            credit_str = item.css(".numeric::text").get() or "0"
            try:
                credit = float(credit_str)
            except ValueError:
                credit = 0.0
            options.append(
                CourseOption(
                    course_id=cid,
                    course_code="",
                    name=name.strip(),
                    category=category,
                    credit=credit,
                    raw={"cid": cid, "ct": ct},
                )
            )
        return options

    @staticmethod
    def _parse_class_table(
        html: str, category: CourseCategory, cid: str,
        course_name: str = "", course_credit: float = 0.0,
    ) -> list[CourseOption]:
        """解析教学班表格 .editRows，提取选课参数与时间信息。

        表头结构（实测 sportTask）：
          thead td: [课序号, 教师, 人数, 席位, 校区, 周次, 上课时间, 上课地点]
          数据行第一个 td 是状态列（含 <span class="stat"> 图标，无文本，无表头）
        用 xpath("string()") 提取每个 td 的全部文本（含嵌套 span）。
        """
        sel = Selector(text=html)
        rows = sel.css(".editRows")
        headers = sel.css("thead td::text").getall()
        options: list[CourseOption] = []
        for row in rows:
            href = row.css("a::attr(href)").get()
            # 用 xpath string() 提取每个 td 的所有文本（含嵌套 span 内文本）
            all_tds = [td.xpath("string()").get().strip() for td in row.css("td")]
            # 第一个 td 是状态列（无表头），跳过；剩余与 headers 对齐
            data_tds = all_tds[1:] if len(all_tds) > len(headers) else all_tds
            status = "已满" if not href else "可选"
            info: dict[str, Any] = dict(zip(headers, data_tds))
            info["状态"] = status

            option = CourseOption(
                course_id=cid,
                course_code=info.get("课序号", ""),
                name=course_name,
                category=category,
                teacher=info.get("教师", ""),
                campus=info.get("校区", ""),
                class_name=info.get("课序号", ""),
                capacity=int(info.get("人数", 0) or 0),
                selected_count=0,
                credit=course_credit,
                raw=info,
            )

            # 解析席位："-/-" 表示已满，数字表示剩余量
            seat_str = info.get("席位", "")
            if seat_str and seat_str != "-/-":
                try:
                    remaining = int(seat_str)
                    option.selected_count = max(0, option.capacity - remaining)
                except ValueError:
                    pass
            elif seat_str == "-/-":
                option.selected_count = option.capacity

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

            # 解析上课时间（如 "周一第二讲"）
            time_str = info.get("上课时间", "")
            option.time_slots = CourseService._parse_time_str(time_str)
            if option.time_slots:
                option.weeks_available = sorted(
                    set(w for s in option.time_slots for w in s.weeks)
                )
            # 解析周次（如 "02-15" 表示第 2-15 周）
            week_str = info.get("周次", "")
            if not option.weeks_available and week_str:
                wm = re.match(r"(\d+)-(\d+)", week_str)
                if wm:
                    option.weeks_available = list(range(int(wm.group(1)), int(wm.group(2)) + 1))
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
