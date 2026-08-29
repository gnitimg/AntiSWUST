from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.course import CourseCategory, CourseOption
from app.services.course_service import SessionExpiredError, _cn_to_int, course_service

# 预置选课：用户提前导入/录入意向课程（CSV 或手动，主要体育项目），选课开始后
# 自动在真实课程列表中匹配（课程名+教师+课序号+校区+时间），并按优先级提交选课。
# 条目持久化 backend/data/preset_courses.json；运行任务存内存（后端重启清空）。

# 运行循环默认间隔（秒）：每轮要全量抓取分类列表+详情，较重，不宜过快
DEFAULT_RUN_INTERVAL = 5.0
MIN_RUN_INTERVAL = 2.0


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()


# CSV 列名别名 → 规范字段（表头可缺省，缺省时按 课程名,教师,课序号,校区,时间 兜底）
CSV_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("课程名", "名称", "课程名称", "课程"),
    "teacher": ("教师", "任课教师", "老师"),
    "class_name": ("课序号", "教学班", "班次", "序号"),
    "campus": ("校区", "上课校区"),
    "day": ("星期", "星期几", "上课星期"),
    "node": ("节次", "讲次", "上课节次"),
    "time": ("时间", "上课时间"),
}

_DAY_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


def parse_day(value: str | None) -> int | None:
    """'周一'/'星期一'/'1' → 1-7。"""
    if not value:
        return None
    v = str(value).strip()
    if v.isdigit():
        n = int(v)
        return n if 1 <= n <= 7 else None
    m = re.search(r"[周星]期?([一二三四五六日天])", v)
    if m:
        return _DAY_MAP.get(m.group(1))
    for ch, n in _DAY_MAP.items():
        if ch in v:
            return n
    return None


def parse_node(value: str | None) -> int | None:
    """'第3节'/'第四讲'/'3-4节'/'第三讲-第四讲' → 起始节次。"""
    if not value:
        return None
    m = re.search(r"第?([0-9一二两三四五六七八九十]+)", str(value))
    if not m:
        return None
    return _cn_to_int(m.group(1))


def _header_key(header: str) -> str | None:
    h = re.sub(r"\s+", "", header or "")
    for key, aliases in CSV_ALIASES.items():
        if h in aliases:
            return key
    return None


class PresetService:
    """预置课程条目存储 + CSV 导入 + 匹配 + 自动选课运行器。"""

    def __init__(self) -> None:
        self._path: Path = settings.cookie_store_dir.parent / "preset_courses.json"
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._runs: dict[str, dict[str, Any]] = {}
        self._run_loops: dict[str, asyncio.Task] = {}
        self._load()

    # ---------- 条目存储 ----------

    def _load(self) -> None:
        try:
            self._entries = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            self._entries = []

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass

    def list_entries(self) -> list[dict[str, Any]]:
        return sorted(self._entries, key=lambda e: e.get("priority", 999))

    def _next_priority(self) -> int:
        return (max((e.get("priority", 0) for e in self._entries), default=0)) + 1

    def add_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = dict(entry)
        entry["id"] = uuid.uuid4().hex[:12]
        with self._lock:
            entry["priority"] = int(entry.get("priority") or self._next_priority())
            self._entries.append(entry)
            self._save()
        return entry

    def update_entry(self, entry_id: str, patch: dict[str, Any]) -> bool:
        with self._lock:
            for e in self._entries:
                if e["id"] == entry_id:
                    for k in ("category", "name", "teacher", "class_name", "campus",
                              "day_of_week", "node", "priority", "enabled"):
                        if k in patch and patch[k] is not None:
                            e[k] = patch[k]
                    self._save()
                    return True
        return False

    def delete_entry(self, entry_id: str) -> bool:
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            changed = len(self._entries) < before
            if changed:
                self._save()
            return changed

    # ---------- CSV 导入 ----------

    def import_csv(self, content: str, category: CourseCategory) -> list[dict[str, Any]]:
        """解析 CSV 文本并保存为新条目。表头按别名识别、列序无关；无表头时按
        「课程名,教师,课序号,校区,时间」顺序兜底。星期/节次可单独成列，也可从时间列解析。
        """
        content = content.strip().lstrip("\ufeff")
        if not content:
            return []
        try:
            dialect = csv.Sniffer().sniff(content[:2048], delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        rows = [
            r for r in csv.reader(io.StringIO(content), dialect)
            if any((c or "").strip() for c in r)
        ]
        if not rows:
            return []

        header_row_idx = 0
        mapped = [_header_key(c) for c in rows[0]]
        if any(mapped):
            header_keys: list[str | None] = mapped
            header_row_idx = 1
        else:
            header_keys = ["name", "teacher", "class_name", "campus", "time"]

        created: list[dict[str, Any]] = []
        for row in rows[header_row_idx:]:
            fields: dict[str, str] = {}
            for i, cell in enumerate(row):
                if i >= len(header_keys):
                    break
                key = header_keys[i]
                if key and (cell or "").strip():
                    fields[key] = cell.strip()
            name = fields.get("name", "")
            if not name:
                continue
            day = parse_day(fields.get("day"))
            node = parse_node(fields.get("node"))
            if day is None or node is None:
                slots = course_service._parse_time_str(fields.get("time", ""))
                if slots:
                    day = day if day is not None else slots[0].day_of_week
                    node = node if node is not None else slots[0].start_node
            created.append(self.add_entry({
                "category": category,
                "name": name,
                "teacher": fields.get("teacher", ""),
                "class_name": fields.get("class_name", ""),
                "campus": fields.get("campus", ""),
                "day_of_week": day,
                "node": node,
                "enabled": True,
            }))
        return created

    # ---------- 匹配 ----------

    @staticmethod
    def match(preset: dict[str, Any], options: list[CourseOption]) -> CourseOption | None:
        """在真实课程列表中匹配预置条目：课程名双向包含（忽略空白/大小写），
        其余已填字段（教师/课序号/校区/星期/节次）必须全部命中；多个候选优先有余量的。
        """
        name = _norm(preset.get("name"))
        if not name:
            return None
        candidates: list[CourseOption] = []
        for o in options:
            on = _norm(o.name)
            if not on or not (name in on or on in name):
                continue
            if preset.get("teacher") and _norm(preset["teacher"]) not in _norm(o.teacher):
                continue
            if preset.get("class_name"):
                cn, ocn = _norm(preset["class_name"]), _norm(o.class_name)
                if cn != ocn and cn not in ocn:
                    continue
            if preset.get("campus") and _norm(preset["campus"]) not in _norm(o.campus):
                continue
            if preset.get("day_of_week") and not any(
                s.day_of_week == preset["day_of_week"] for s in (o.time_slots or [])
            ):
                continue
            if preset.get("node") and not any(
                s.start_node <= preset["node"] <= s.end_node for s in (o.time_slots or [])
            ):
                continue
            candidates.append(o)
        if not candidates:
            return None
        candidates.sort(key=lambda o: 0 if o.capacity - o.selected_count > 0 else 1)
        return candidates[0]

    # ---------- 自动选课运行器 ----------

    def start_run(
        self,
        session_id: str,
        start_at: float | None = None,
        retry: bool = True,
        interval: float = DEFAULT_RUN_INTERVAL,
        stop_same_category: bool = True,
    ) -> dict[str, Any]:
        """启动一次预置选课运行（同会话旧运行自动停止）。

        start_at: 选课开放时间（epoch 秒），未到则处于 waiting 状态到点自动开跑。
        retry:    本轮未匹配/提交失败的条目是否持续重试。
        stop_same_category: 某分类成功一条后，跳过该分类剩余条目（体育通常只能选一门）。
        """
        self.stop_run(session_id)
        entries = [e for e in self.list_entries() if e.get("enabled")]
        run: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "session_id": session_id,
            "status": "waiting" if start_at and start_at > time.time() else "running",
            "begin_at": start_at,
            "retry": retry,
            "interval": max(MIN_RUN_INTERVAL, float(interval)),
            "stop_same_category": stop_same_category,
            "created_at": time.time(),
            "finished_at": None,
            "error": "",
            "cycles": 0,
            "results": {
                e["id"]: {
                    "preset_id": e["id"],
                    "name": e["name"],
                    "category": e.get("category", CourseCategory.PE.value),
                    # pending/unmatched/submitted/success/skipped/failed
                    "status": "pending",
                    "message": "",
                    "matched": "",
                    "attempts": 0,
                }
                for e in entries
            },
        }
        self._runs[run["id"]] = run
        self._run_loops[run["id"]] = asyncio.create_task(self._run_loop(run))
        print(f"[preset] 启动预置选课 {run['id']}: {len(entries)} 条, start_at={start_at}, retry={retry}", flush=True)
        return run

    def stop_run(self, session_id: str) -> bool:
        stopped = False
        for run in list(self._runs.values()):
            if run["session_id"] != session_id:
                continue
            if run["status"] in ("waiting", "running"):
                run["status"] = "stopped"
                run["finished_at"] = run["finished_at"] or time.time()
                loop = self._run_loops.pop(run["id"], None)
                if loop is not None:
                    loop.cancel()
                stopped = True
                print(f"[preset] 停止预置选课 {run['id']}", flush=True)
        return stopped

    def get_run(self, session_id: str) -> dict[str, Any] | None:
        runs = [r for r in self._runs.values() if r["session_id"] == session_id]
        if not runs:
            return None
        runs.sort(key=lambda r: r["created_at"], reverse=True)
        return runs[0]

    async def _run_loop(self, run: dict[str, Any]) -> None:
        try:
            # 等待选课开始时间
            if run["begin_at"]:
                while run["status"] == "waiting" and time.time() < run["begin_at"]:
                    await asyncio.sleep(0.5)
            if run["status"] != "running":
                return

            while run["status"] == "running":
                run["cycles"] += 1
                # 抓取本次需要的分类（全量，含教学班详情，用于匹配与提交参数）
                options_by_cat: dict[CourseCategory, list[CourseOption]] = {}
                cats = {
                    CourseCategory(r["category"])
                    for r in run["results"].values()
                    if r["status"] in ("pending", "unmatched", "submitted", "failed")
                }
                try:
                    for cat in cats:
                        options_by_cat[cat] = await course_service.fetch_category(
                            run["session_id"], cat, force=True
                        )
                    run["error"] = ""
                except SessionExpiredError:
                    run["error"] = "教务会话已失效，请重新登录"
                    run["status"] = "error"
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    run["error"] = f"抓取课程失败: {type(e).__name__}: {e}"
                    if not run["retry"]:
                        break
                    await asyncio.sleep(run["interval"])
                    continue

                await self._cycle(run, options_by_cat)

                remaining = [
                    r for r in run["results"].values()
                    if r["status"] in ("pending", "unmatched", "submitted", "failed")
                ]
                if not remaining or not run["retry"]:
                    break
                await asyncio.sleep(run["interval"])

            if run["status"] == "running":
                run["status"] = "finished"
        except asyncio.CancelledError:
            if run["status"] == "running":
                run["status"] = "stopped"
        except Exception as e:
            run["status"] = "error"
            run["error"] = f"{type(e).__name__}: {e}"
        finally:
            self._run_loops.pop(run["id"], None)
            run["finished_at"] = run["finished_at"] or time.time()

    async def _cycle(
        self,
        run: dict[str, Any],
        options_by_cat: dict[CourseCategory, list[CourseOption]],
    ) -> None:
        """按优先级遍历预置条目：匹配 → 提交。一次循环一个条目串行提交，避免并发踩会话锁。"""
        succeeded_cats = {
            CourseCategory(r["category"])
            for r in run["results"].values()
            if r["status"] == "success"
        }
        entries = sorted(
            (e for e in self.list_entries() if e["id"] in run["results"] and e.get("enabled")),
            key=lambda e: e.get("priority", 999),
        )
        for entry in entries:
            if run["status"] != "running":
                return
            result = run["results"][entry["id"]]
            if result["status"] in ("success", "skipped"):
                continue
            cat = CourseCategory(entry.get("category", CourseCategory.PE.value))
            if run["stop_same_category"] and cat in succeeded_cats:
                result["status"] = "skipped"
                result["message"] = "同类课程已选中，跳过"
                continue

            matched = PresetService.match(entry, options_by_cat.get(cat, []))
            if matched is None:
                result["status"] = "unmatched"
                result["message"] = "未在当前课程列表中匹配到"
                continue
            result["matched"] = f"{matched.name} {matched.class_name}".strip()

            if matched.raw.get("状态") == "已选":
                result["status"] = "success"
                result["message"] = "该课程已在选课记录中"
                succeeded_cats.add(cat)
                continue
            if not (matched.course_id or "").count("|"):
                result["status"] = "failed"
                result["message"] = "匹配到课程但选课参数未加载，下轮重试"
                continue

            result["attempts"] += 1
            try:
                resp = await course_service.select(run["session_id"], matched.course_id, cat)
            except SessionExpiredError as e:
                result["status"] = "failed"
                result["message"] = str(e)
                run["error"] = str(e)
                run["status"] = "error"
                return
            except Exception as e:
                result["status"] = "failed"
                result["message"] = f"{type(e).__name__}: {e}"
                continue

            reason = str(resp.get("reason") or resp.get("message") or "")
            if resp.get("success") or any(
                p in reason for p in ("重复选课", "已选中", "已经选择", "已选过", "请勿重复")
            ):
                result["status"] = "success"
                result["message"] = reason or "选课成功"
                succeeded_cats.add(cat)
                course_service.invalidate(run["session_id"])
                print(f"[preset] {run['id']} 成功: {entry['name']} -> {result['matched']}", flush=True)
            else:
                # 提交失败（如已满）：retry 模式下下轮继续尝试
                result["status"] = "submitted"
                result["message"] = reason or "提交未成功"
                print(f"[preset] {run['id']} 未成功: {entry['name']} {reason}", flush=True)


preset_service = PresetService()
