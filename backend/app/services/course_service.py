from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
from parsel import Selector

from app.config import settings
from app.core.swust_client import swust_client
from app.models.course import ClassTimeSlot, CourseCategory, CourseOption


class SessionExpiredError(RuntimeError):
    """教务系统会话失效（请求被 302 重定向到 CAS 登录页，且门户首页也验证失败）。"""


class ServicePausedError(RuntimeError):
    """选课服务暂停/未开放（会话有效，但 chooseCourse 模块把请求踢回 CAS 登录页）。

    用不依赖选课模块的学生门户首页判别：门户能打开 → 会话有效 → 服务暂停，
    此时不应返回 401 导致前端误登出。
    """


# 真实选课接口映射（2026-08-28 实测，来源：Chrome DevTools Protocol 抓取五个分类列表页 JS）
# 教务系统 matrix.dean.swust.edu.cn 的 chooseCourse event 命名：
#   列表页   event=chooseCourse:{task_type}&CT={轮次}
#   教学班   event=chooseCourse:{table_api}   (POST TID/CID/seed)
#   选课     event=chooseCourse:{choose_api}  (POST CT/TID/CID/CIDX/TSK/TT/ST[/CP]/seed)
#   取消     event=chooseCourse:apiCancelTask (POST CT/TID/CID/CIDX/TSK/TT/ST/SCC/seed)
# 注意：sportTask/commonTask/programTask 选课 API 带 Choose 前缀，fixupTask/retakeTask 不带。
CATEGORY_TASK: dict[CourseCategory, dict[str, str]] = {
    # 体育项目（体育课）
    CourseCategory.PE: {"task_type": "sportTask", "table_api": "apiSportTaskTable", "choose_api": "apiChooseSportTask"},
    # 全校通选课
    CourseCategory.GENERAL: {"task_type": "commonTask", "table_api": "apiCommonTaskTable", "choose_api": "apiChooseCommonTask"},
    # 计划课程（专业限选）
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

# 表头别名 → 规范键。五个分类的教学班表头列名存在差异（如 sportTask 用"上课地点"，
# 其他分类可能是"地点"/"教室"），按别名归一化后再映射，避免字段丢失。
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "课序号": ("课序号", "序号", "教学班", "班次", "课序"),
    "教师": ("教师", "任课教师", "老师"),
    "人数": ("人数", "容量", "限选人数", "人数上限", "计划人数"),
    "席位": ("席位", "余量", "剩余席位", "剩余人数"),
    "校区": ("校区", "上课校区"),
    "周次": ("周次", "行课周次", "上课周次"),
    "上课时间": ("上课时间", "时间", "上课时间/节次"),
    "上课地点": ("上课地点", "地点", "教室", "上课教室"),
}

# 中文数字（"周四第四讲" 格式）
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(text: str) -> int | None:
    """中文数字转整数，支持 一~十九（讲次/节次范围）。"""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        ten_part, one_part = text.split("十", 1)
        tens = _CN_DIGITS.get(ten_part, 1) if ten_part else 1
        ones = _CN_DIGITS.get(one_part, 0) if one_part else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(text)

# 教务系统网络层不可达时的统一提示
NET_UNAVAILABLE_MSG = "教务系统暂时无法访问（服务可能已暂停或网络异常），请稍后再试"

# fetch_selected 依次尝试的分类（任一列表页都内嵌同一份已选清单，从小页到大页）
SELECTED_FETCH_ORDER = (
    CourseCategory.SUPPLEMENT,
    CourseCategory.RETAKE,
    CourseCategory.PE,
    CourseCategory.MAJOR_LIMITED,
    CourseCategory.GENERAL,
)


class CourseService:
    """选课数据抓取与解析服务（对接 matrix.dean.swust.edu.cn 真实接口）。"""

    _cache: dict[tuple[str, str], tuple[float, list[CourseOption]]] = {}
    _cache_ttl: float = 60.0
    # 已选课程清单缓存（列表页内嵌，key 为 session_id）
    _selected_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _ct(self, category: CourseCategory) -> int:
        return CATEGORY_CT_OVERRIDE.get(category, settings.choose_course_ct)

    @staticmethod
    def _looks_like_login_page(resp: Any) -> bool:
        """教务 session 失效时请求会被 302 到 CAS 登录页（follow_redirects 后 resp.url 变为 cas）。"""
        url = str(getattr(resp, "url", ""))
        return "authserver/login" in url or ("cas.swust.edu.cn" in url and "matrix.dean" not in url)

    async def _portal_check(self, session_id: str) -> tuple[bool, str]:
        """用学生门户首页（不依赖选课模块）探测会话状态。

        返回 (存活, 备注)："alive"=门户正常打开；"dead"=门户也被踢到 CAS；
        "error"=门户请求本身失败（超时/连接错误，系统可能整体不可用）。
        """
        try:
            portal_url = f"{settings.swust_dean_base_url}?event={settings.swust_dean_portal_event}"
            resp = await swust_client.get(session_id, portal_url)
            return (True, "alive") if not self._looks_like_login_page(resp) else (False, "dead")
        except Exception:
            return False, "error"

    async def _raise_for_course_access(self, session_id: str, resp: Any) -> None:
        """选课页被踢到 CAS 时，区分「选课模块暂停」「系统整体不可用」「会话真失效」。"""
        # matrix CFM 应用会话未初始化时会返回「应用程序出错」页（HTTP 200 但非登录页），
        # 属瞬时故障，按服务不可用（503）处理，避免前端误判为会话失效而强制登出。
        if "应用程序出错" in (getattr(resp, "text", "") or ""):
            raise ServicePausedError(NET_UNAVAILABLE_MSG)
        if not self._looks_like_login_page(resp):
            return
        alive, note = await self._portal_check(session_id)
        if alive:
            raise ServicePausedError("选课服务当前暂停或未开放，请稍后再试")
        if note == "error":
            raise ServicePausedError("教务系统暂时无法访问，请稍后再试")
        # 门户也被踢到 CAS：会话失效与系统整体维护两种情况无法进一步区分，
        # 提示语兼顾两者；前端对该 401 只提示不自动登出
        raise SessionExpiredError("教务系统会话已失效或系统维护中，请稍后重试或重新扫码登录")

    async def _course_get(self, session_id: str, url: str) -> Any:
        """请求教务选课页；若被踢回 CAS（教务 SSO 过期），用 TGC 静默续期后重试一次。

        这样多数「会话过期」无需用户重新扫码即可自愈。续期后仍被踢才交给
        _raise_for_course_access 判定为失效/暂停。
        """
        resp = await swust_client.get(session_id, url)
        if self._looks_like_login_page(resp):
            if await swust_client.refresh_dean_session(session_id):
                await swust_client.prime(session_id)
                resp = await swust_client.get(session_id, url)
        return resp

    def invalidate(self, session_id: str) -> None:
        """选课/退课提交后清除该 session 的全部缓存，下次抓取拿到最新状态。"""
        for key in [k for k in self._cache if k[0] == session_id]:
            self._cache.pop(key, None)
        self._selected_cache.pop(session_id, None)

    async def fetch_category(
        self, session_id: str, category: CourseCategory, force: bool = False, basic: bool = False
    ) -> list[CourseOption]:
        """抓取分类课程。

        basic=True 时只解析列表页（课程级信息：名称/学分/锁定/已选，约 1 秒返回），
        供前端先渲染再异步补齐教学班详情；basic 与 full 结果分开缓存。
        """
        # 短期缓存：60 秒内同一 session+分类直接返回缓存（force=True 跳过）
        cache_key = (session_id, f"{category.value}:{'basic' if basic else 'full'}")
        if not force:
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached[0] < self._cache_ttl:
                return cached[1]

        task = CATEGORY_TASK[category]
        ct = self._ct(category)
        list_url = f"{settings.swust_dean_base_url}?event=chooseCourse:{task['task_type']}&CT={ct}"
        # 先预热 matrix 应用会话（否则 chooseCourse 事件返回「应用程序出错」页）
        await swust_client.prime(session_id)
        # 列表页偶发超时（会话锁排队/网络抖动），重试一次
        resp: httpx.Response | None = None
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self._course_get(session_id, list_url)
                break
            except httpx.HTTPError:
                # 教务在网络层拒绝/超时（服务暂停时常见），按服务不可用处理而非 500
                last_err = ServicePausedError("%s" % NET_UNAVAILABLE_MSG)
                if attempt == 0:
                    await asyncio.sleep(0.8)
        if resp is None:
            raise last_err if last_err is not None else RuntimeError("列表页请求失败")
        await self._raise_for_course_access(session_id, resp)
        tid = self._extract_tid(resp.text)
        # 已选课程清单内嵌在每个列表页中，顺带解析并缓存（退课参数来源）
        if "Choosen" in resp.text:
            self._selected_cache[session_id] = (time.time(), self._parse_choosen_table(resp.text))
        courses = self._parse_course_list(resp.text, category, ct)

        if basic:
            # 列表页信息即可直接返回：已选/锁定状态已知，其余教学班字段待 full 阶段补齐
            for c in courses:
                if not c.raw.get("locked") and not c.raw.get("checked"):
                    c.raw["状态"] = ""
            self._cache[cache_key] = (time.time(), courses)
            return courses

        # 并行抓取教学班详情（并发数可通过 FETCH_CONCURRENCY 调整，避免教务系统限流）
        sem = asyncio.Semaphore(settings.fetch_concurrency)

        async def fetch_one(course: CourseOption) -> list[CourseOption]:
            # 锁定课程无教学班入口（trigger 被 .stat.locked 取代），跳过详情抓取
            if course.raw.get("locked"):
                return [course]
            async with sem:
                for attempt in range(settings.fetch_max_attempts):
                    try:
                        parsed = await self._fetch_class_details(
                            session_id, category, course.course_id, tid,
                            course.name, course.credit, bool(course.raw.get("checked")),
                        )
                        # 解析结果为空通常意味着响应异常（限流页/登录页/错误页），重试
                        if parsed:
                            return parsed
                    except SessionExpiredError:
                        raise
                    except Exception:
                        pass
                    if attempt < settings.fetch_max_attempts - 1:
                        await asyncio.sleep(settings.fetch_retry_delay)
            # 重试耗尽：保留基本信息行并标记，前端禁用其选课按钮
            course.raw["detail_failed"] = True
            course.raw["状态"] = "详情未加载"
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

    async def fetch_selected(self, session_id: str, force: bool = False) -> list[dict[str, Any]]:
        """获取已选课程清单（含退课所需 chooser_id 等参数）。

        已选清单内嵌在每个分类列表页的 div#Choosen 中，优先用缓存；
        缓存未命中时从小到大依次请求列表页解析。
        """
        cached = self._selected_cache.get(session_id)
        if cached and not force and time.time() - cached[0] < self._cache_ttl:
            return cached[1]

        # 先预热 matrix 应用会话，否则 chooseCourse 事件返回「应用程序出错」页
        await swust_client.prime(session_id)
        last_err: Exception | None = None
        for category in SELECTED_FETCH_ORDER:
            task = CATEGORY_TASK[category]
            url = f"{settings.swust_dean_base_url}?event=chooseCourse:{task['task_type']}&CT={self._ct(category)}"
            try:
                resp = await self._course_get(session_id, url)
                await self._raise_for_course_access(session_id, resp)
            except SessionExpiredError:
                raise
            except httpx.HTTPError:
                last_err = ServicePausedError("%s" % NET_UNAVAILABLE_MSG)
                continue
            except Exception as e:
                last_err = e
                continue
            if "Choosen" not in resp.text:
                # 异常页面（无已选清单容器），尝试下一个分类
                continue
            items = self._parse_choosen_table(resp.text)
            self._selected_cache[session_id] = (time.time(), items)
            return items

        if last_err is not None:
            raise last_err
        raise SessionExpiredError("无法获取已选课程清单，请重新登录")

    async def _fetch_class_details(
        self, session_id: str, category: CourseCategory, cid: str, tid: str = "",
        course_name: str = "", course_credit: float = 0.0, is_checked: bool = False,
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
            timeout=settings.fetch_detail_timeout,
        )
        await self._raise_for_course_access(session_id, resp)
        return self._parse_class_table(resp.text, category, cid, course_name, course_credit, is_checked)

    async def select(
        self, session_id: str, course_id: str, category: CourseCategory, weeks: list[int] | None = None
    ) -> dict[str, Any]:
        task = CATEGORY_TASK[category]
        ct = self._ct(category)
        # course_id 编码为 CID|CIDX|TID|TT|TSK|ST（由前端从列表回传）
        parts = course_id.split("|")
        if len(parts) < 6:
            return {"success": False, "reason": "教学班详情未加载，无法提交（请刷新列表重试）"}
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
        try:
            resp = await swust_client.post(
                session_id,
                settings.swust_dean_base_url,
                params={"event": f"chooseCourse:{task['choose_api']}"},
                data=data,
                headers=CHOOSE_HEADERS,
            )
        except httpx.HTTPError:
            raise ServicePausedError("%s" % NET_UNAVAILABLE_MSG)
        await self._raise_for_course_access(session_id, resp)
        try:
            result = resp.json()
        except Exception:
            result = {"success": False, "reason": resp.text[:200]}
        if result.get("success"):
            self.invalidate(session_id)
        return result

    async def cancel(
        self, session_id: str, course_id: str, category: CourseCategory, chooser_id: str = ""
    ) -> dict[str, Any]:
        """取消选课（退课）。五个分类统一用 apiCancelTask。

        course_id 编码: CID|CIDX|TID|TT|TSK|ST，与 chooser_id 一同来自已选课程清单
        （列表页内嵌 div#Choosen 中 removeTask 的前 7 个实参），见 fetch_selected。
        chooser_id: SCC 参数，形如 `5120246728,121387,261T`（学号+cid+termId+taskType）。
        """
        ct = self._ct(category)
        parts = course_id.split("|")
        if len(parts) < 6:
            return {"success": False, "reason": "退课参数不完整，请刷新已选课程后重试"}
        if not chooser_id:
            return {"success": False, "reason": "缺少退课记录标识（SCC），请刷新已选课程后重试"}
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
        try:
            resp = await swust_client.post(
                session_id,
                settings.swust_dean_base_url,
                params={"event": f"chooseCourse:{CANCEL_API}"},
                data=data,
                headers=CHOOSE_HEADERS,
            )
        except httpx.HTTPError:
            raise ServicePausedError("%s" % NET_UNAVAILABLE_MSG)
        await self._raise_for_course_access(session_id, resp)
        try:
            result = resp.json()
        except Exception:
            result = {"success": False, "reason": resp.text[:200]}
        if result.get("success"):
            self.invalidate(session_id)
        return result

    @staticmethod
    def _extract_tid(html: str) -> str:
        """从列表页 JS 提取学期 ID TID（形如 'TID' : '261'）。"""
        m = re.search(r"'TID'\s*:\s*'(\d+)'", html)
        return m.group(1) if m else ""

    @staticmethod
    def _parse_course_list(html: str, category: CourseCategory, ct: int) -> list[CourseOption]:
        """解析课程列表页 .courseShow。

        可选课程含 .trigger（cid 属性）；已选课程 trigger 带 checked 类；
        锁定课程无 trigger（.stat.locked 代替），从 div.courseShow 的 cid 属性取 ID 并标记置灰。
        """
        sel = Selector(text=html)
        items = sel.css(".courseShow")
        options: list[CourseOption] = []
        for item in items:
            name = item.css(".name::text").get() or ""
            cid = item.css(".trigger::attr(cid)").get() or ""
            locked = bool(item.css(".stat.locked"))
            if not cid:
                if not locked:
                    continue
                cid = item.attrib.get("cid") or ""
                if not cid:
                    continue
            credit_str = item.css(".numeric::text").get() or "0"
            try:
                credit = float(credit_str)
            except ValueError:
                credit = 0.0
            trigger_class = item.css(".trigger::attr(class)").get() or ""
            is_checked = "checked" in trigger_class
            raw: dict[str, Any] = {"cid": cid, "ct": ct, "checked": is_checked}
            if locked:
                raw["locked"] = True
                raw["状态"] = "锁定"
            options.append(
                CourseOption(
                    course_id=cid,
                    course_code="",
                    name=name.strip(),
                    category=category,
                    credit=credit,
                    raw=raw,
                )
            )
        return options

    @staticmethod
    def _canonical_headers(headers: list[str]) -> list[str]:
        """把教务表头列名归一化为规范键（未匹配到的保留原文）。"""
        out: list[str] = []
        for h in headers:
            h = (h or "").strip()
            canonical = h
            for key, aliases in HEADER_ALIASES.items():
                if h in aliases:
                    canonical = key
                    break
            out.append(canonical)
        return out

    @staticmethod
    def _parse_class_table(
        html: str, category: CourseCategory, cid: str,
        course_name: str = "", course_credit: float = 0.0, is_checked: bool = False,
    ) -> list[CourseOption]:
        """解析教学班表格 .editRows，提取选课参数与时间信息。

        表头按别名归一化（见 HEADER_ALIASES），规范键为：
          课序号/教师/人数/席位/校区/周次/上课时间/上课地点
        数据行第一个 td 是状态列（含 <span class="stat"> 图标，无文本，无表头）。
        用 xpath("string()") 提取每个 td 的全部文本（含嵌套 span）。
        """
        sel = Selector(text=html)
        rows = sel.css(".editRows")
        raw_headers = sel.css("thead td::text").getall()
        headers = CourseService._canonical_headers(raw_headers)
        options: list[CourseOption] = []
        for row in rows:
            choose_href = row.css("a[href*='chooseCourse']::attr(href)").get()
            remove_href = row.css("a[href*='removeTask']::attr(href)").get()
            stat_class = row.css("span.stat::attr(class)").get() or ""
            stat_title = row.css("span.stat::attr(title)").get() or ""

            # 用 xpath string() 提取每个 td 的所有文本（含嵌套 span 内文本）
            all_tds = [(td.xpath("string()").get() or "").strip() for td in row.css("td")]
            # 第一个 td 是状态列（无表头），跳过；剩余与 headers 对齐
            data_tds = all_tds[1:] if len(all_tds) > len(headers) else all_tds

            # 状态判断：chooseCourse 链接→可选，stat on→已选，stat peoples→已满
            if choose_href:
                status = "可选"
            elif remove_href:
                status = "已选"
            elif "on" in stat_class.split():
                status = "已选"
            elif "checked" in stat_class or "已选" in stat_title:
                status = "已选"
            else:
                status = "已满"

            info: dict[str, Any] = dict(zip(headers, data_tds))
            info["状态"] = status
            # 嵌入基础 cid，供前端与已选课程清单按 cid 关联退课参数
            info["cid"] = cid

            option = CourseOption(
                course_id=f"{cid}_{info.get('课序号', '')}",
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
            elif seat_str == "-/-" and status == "已满":
                option.selected_count = option.capacity

            # 提取选课参数
            if choose_href:
                cleaned = choose_href.replace(" ", "")
                m = re.search(r"chooseCourse\((.+?)\)", cleaned)
                if m:
                    args = [a.strip("'") for a in m.group(1).split("','")]
                    if len(args) >= 6:
                        option.course_id = "|".join(args[:6])
                        option.raw["choose_args"] = args[:6]

            # 提取退课参数 removeTask(chooserId, courseId, courseIdx, termId, taskType, taskId, hash)
            if remove_href:
                cleaned = remove_href.replace(" ", "")
                m = re.search(r"removeTask\((.+?)\)", cleaned)
                if m:
                    args = [a.strip("'") for a in m.group(1).split("','")]
                    if len(args) >= 1:
                        option.raw["chooser_id"] = args[0]
                        option.raw["cancel_args"] = args

            # 解析上课时间（如 "周一第1-2节{1-16周}"）
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
    def _parse_choosen_table(html: str) -> list[dict[str, Any]]:
        """解析列表页内嵌的已选课程清单（div#Choosen → #choosenTable → tr.editRows）。

        每行 10 列：[序号, 教学班, 任课教师, 学分, 修读方式, 课程性质, 重修, 选课轮次, 选课时间, 操作]。
        操作列两种形态（2026-08-28 实测 sportTask 列表页）：
          可退: <a title="撤销课程" class="stat delete"
                 href="javascript:removeTask('SCC','CID','CIDX','TID','TT','TSK','ST');"></a>
          锁定: <span title="该选课记录禁止修改" class="stat locked"></span>
        教学班列形如 "编译原理.-.(003)" / "大学体育5——篮球俱乐部.-.(T17)"。
        chooserId 形如 "5120246728,121387,261T"（学号+cid+termId+taskType）。
        """
        sel = Selector(text=html)
        container = sel.css("#Choosen")
        if not container:
            return []
        items: list[dict[str, Any]] = []
        for row in container.css("tr.editRows"):
            tds = [(td.xpath("string()").get() or "").strip() for td in row.css("td")]
            remove_href = row.css("a.stat.delete::attr(href)").get() or ""
            locked = bool(row.css("span.stat.locked"))

            name_raw = tds[1] if len(tds) > 1 else ""
            nm = re.match(r"(.*)\.-\.\(([^()]*)\)\s*$", name_raw)
            name, class_idx = (nm.group(1).strip(), nm.group(2)) if nm else (name_raw, "")

            item: dict[str, Any] = {
                "name": name,
                "class_name": class_idx,
                "teacher": tds[2] if len(tds) > 2 else "",
                "credit": tds[3] if len(tds) > 3 else "",
                "nature": tds[5] if len(tds) > 5 else "",
                "round": tds[7] if len(tds) > 7 else "",
                "choose_time": tds[8] if len(tds) > 8 else "",
                "locked": locked,
                "cid": "",
                "chooser_id": "",
                "course_id": "",
            }
            if remove_href:
                cleaned = remove_href.replace(" ", "")
                m = re.search(r"removeTask\((.+?)\)", cleaned)
                if m:
                    args = [a.strip("'") for a in m.group(1).split("','")]
                    if len(args) >= 7:
                        scc, c_id, cidx, tid, tt, tsk, st = args[:7]
                        item.update(
                            {
                                "cid": c_id,
                                "chooser_id": scc,
                                # 与选课 course_id 同构：CID|CIDX|TID|TT|TSK|ST
                                "course_id": "|".join([c_id, cidx, tid, tt, tsk, st]),
                            }
                        )
            items.append(item)
        return items

    @staticmethod
    def _parse_time_str(text: str) -> list[ClassTimeSlot]:
        """解析上课时间字符串，兼容实测的三种形态（同段落可混现多段）：

          1. "周一第1-2节{1-16周}"（sportTask，数字节次+花括号周次）
          2. "周四第四讲" / "周五第三讲-第四讲"（中文数字讲次，讲字可逐个重复）
          3. "周五第三-第四讲"（区间简写）
        多段用逗号/分号/空格分隔均可。按"区间优先、单次兜底"的顺序匹配，
        已被长模式覆盖的文本段不再被短模式重复解析。
        """
        slots: list[ClassTimeSlot] = []
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
        cn = "[一二两三四五六七八九十]"
        num = rf"(?:{cn}+|\d+)"

        patterns: list[tuple[re.Pattern[str], str]] = [
            (re.compile(r"周(.)第(\d+)-(\d+)节(?:\{(\d+)-(\d+)周\})?"), "node_range"),
            (re.compile(rf"周(.)第({num})(?:讲|节)-第?({num})(?:讲|节)"), "cn_range"),
            (re.compile(rf"周(.)第({num})-({num})(?:讲|节)"), "cn_range"),
            (re.compile(rf"周(.)第({num})(?:讲|节)"), "cn_single"),
        ]

        claimed: list[tuple[int, int]] = []

        def overlaps(start: int, end: int) -> bool:
            return any(start < ce and cs < end for cs, ce in claimed)

        for pattern, kind in patterns:
            for m in pattern.finditer(text):
                if overlaps(m.start(), m.end()):
                    continue
                claimed.append((m.start(), m.end()))
                day = day_map.get(m.group(1))
                if not day:
                    continue
                if kind == "node_range":
                    weeks = (
                        list(range(int(m.group(4)), int(m.group(5)) + 1))
                        if m.group(4) and m.group(5)
                        else []
                    )
                    slots.append(
                        ClassTimeSlot(
                            day_of_week=day,
                            start_node=int(m.group(2)),
                            end_node=int(m.group(3)),
                            weeks=weeks,
                        )
                    )
                else:
                    start = _cn_to_int(m.group(2))
                    if start is None:
                        continue
                    end = _cn_to_int(m.group(3)) if kind == "cn_range" else start
                    slots.append(
                        ClassTimeSlot(
                            day_of_week=day,
                            start_node=start,
                            end_node=end if end is not None else start,
                            weeks=[],
                        )
                    )
        return slots


course_service = CourseService()
