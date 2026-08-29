from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.course import CourseCategory
from app.services.course_service import SessionExpiredError, course_service

# 请求间隔下限（秒）：教务系统是老 CFM 应用，过高频率会触发限流/会话锁排队
MIN_INTERVAL = 0.5

# 抢课参数自动刷新间隔（秒）：ST 哈希随页面渲染变化，周期性重抓教学班详情换新参数
PARAM_REFRESH_INTERVAL = 300.0

# 命中这些关键词视为"已在课内"，同样熔断（重复选课不可能成功）
ALREADY_SELECTED_PATTERNS = ("重复选课", "已选中", "已经选择", "已选过", "请勿重复")

# 命中这些关键词视为致命错误，立即停止（继续重试无意义）
FATAL_PATTERNS = ("编码不合法", "参数不完整", "会话已失效", "禁止修改")


@dataclass
class SnipeTask:
    """一个课程的抢课任务（对应一个 asyncio 循环）。"""

    id: str
    session_id: str
    category: CourseCategory
    course_id: str  # 编码 CID|CIDX|TID|TT|TSK|ST，可被参数刷新更新
    cid: str
    class_name: str
    name: str
    interval: float
    duration: float  # 秒，<=0 表示不限时
    status: str = "running"  # running / success / stopped / expired / error
    attempts: int = 0
    last_reason: str = ""
    last_error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "cid": self.cid,
            "class_name": self.class_name,
            "name": self.name,
            "interval": self.interval,
            "duration": self.duration,
            "status": self.status,
            "attempts": self.attempts,
            "last_reason": self.last_reason,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class SnipeManager:
    """抢课任务管理器。

    - 每个任务独立 asyncio 循环，按 interval 提交选课请求
    - 提交成功（success）或命中"已选"关键词 → 熔断该课程剩余任务（status=success）
    - interval 强制下限 MIN_INTERVAL；duration <= 0 表示不限时
    - 任务仅存内存，后端重启后清空（选课本身已提交至教务系统的结果不受影响）
    """

    def __init__(self) -> None:
        self._tasks: dict[str, SnipeTask] = {}
        self._loops: dict[str, asyncio.Task] = {}

    def start(
        self,
        session_id: str,
        category: CourseCategory,
        course_id: str,
        cid: str = "",
        class_name: str = "",
        name: str = "",
        interval: float = 1.0,
        duration: float = 600.0,
    ) -> SnipeTask:
        parts = course_id.split("|")
        cid = cid or (parts[0] if parts else "")
        # 同一课程只保留一个运行中任务：新任务顶替旧任务
        for t in list(self._tasks.values()):
            if t.session_id == session_id and t.cid == cid and t.status == "running":
                self.stop(t.id)

        task = SnipeTask(
            id=uuid.uuid4().hex[:12],
            session_id=session_id,
            category=category,
            course_id=course_id,
            cid=cid,
            class_name=class_name,
            name=name or f"课程 {cid}",
            interval=max(MIN_INTERVAL, float(interval)),
            duration=float(duration),
        )
        self._tasks[task.id] = task
        self._loops[task.id] = asyncio.create_task(self._run(task))
        print(f"[snipe] 启动任务 {task.id}: {task.name} 间隔={task.interval}s 时长={task.duration or '不限'}s", flush=True)
        return task

    def stop(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != "running":
            return False
        task.status = "stopped"
        task.finished_at = task.finished_at or time.time()
        loop = self._loops.pop(task_id, None)
        if loop is not None:
            loop.cancel()
        print(f"[snipe] 手动停止任务 {task_id}: {task.name}", flush=True)
        return True

    def stop_all(self, session_id: str | None = None) -> int:
        count = 0
        for t in list(self._tasks.values()):
            if t.status == "running" and (session_id is None or t.session_id == session_id):
                count += 1 if self.stop(t.id) else 0
        return count

    def list_tasks(self, session_id: str) -> list[dict[str, Any]]:
        tasks = [t for t in self._tasks.values() if t.session_id == session_id]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks]

    async def _run(self, task: SnipeTask) -> None:
        deadline = task.created_at + task.duration if task.duration > 0 else None
        next_refresh = time.time() + PARAM_REFRESH_INTERVAL
        try:
            while task.status == "running" and (deadline is None or time.time() < deadline):
                # 周期性刷新选课参数（ST 哈希会过期）
                if time.time() >= next_refresh:
                    await self._refresh_params(task)
                    next_refresh = time.time() + PARAM_REFRESH_INTERVAL

                try:
                    result = await course_service.select(task.session_id, task.course_id, task.category)
                except SessionExpiredError as e:
                    task.status = "error"
                    task.last_error = str(e)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    result = {}
                    task.last_error = f"{type(e).__name__}: {e}"

                task.attempts += 1
                reason = str(result.get("reason") or result.get("message") or "")
                task.last_reason = reason
                task.last_error = ""

                success = bool(result.get("success"))
                already = any(p in reason for p in ALREADY_SELECTED_PATTERNS)
                if success or already:
                    task.status = "success"
                    task.last_reason = reason or ("已选中该课程" if already else "选课成功")
                    course_service.invalidate(task.session_id)
                    print(f"[snipe] 任务 {task.id} 成功（{task.attempts} 次尝试）: {task.name} {reason}", flush=True)
                    break
                if any(p in reason for p in FATAL_PATTERNS):
                    task.status = "error"
                    task.last_error = reason
                    print(f"[snipe] 任务 {task.id} 致命错误停止: {reason}", flush=True)
                    break

                await asyncio.sleep(task.interval)

            if task.status == "running":
                task.status = "expired"
        except asyncio.CancelledError:
            task.status = task.status if task.status != "running" else "stopped"
        except Exception as e:
            task.status = "error"
            task.last_error = f"{type(e).__name__}: {e}"
        finally:
            self._loops.pop(task.id, None)
            task.finished_at = task.finished_at or time.time()

    async def _refresh_params(self, task: SnipeTask) -> None:
        """重抓该课程教学班详情，更新 course_id 里的 ST 哈希等参数。"""
        parts = task.course_id.split("|")
        if len(parts) < 6:
            return
        cid, _cidx, tid, _tt, _tsk, _st = parts[:6]
        try:
            options = await course_service._fetch_class_details(
                task.session_id, task.category, cid, tid
            )
            for opt in options:
                same_class = (
                    (task.class_name and opt.course_code == task.class_name)
                    or (not task.class_name and opt.course_id == task.course_id)
                )
                if same_class and opt.course_id.count("|") == 5:
                    if opt.course_id != task.course_id:
                        task.course_id = opt.course_id
                        print(f"[snipe] 任务 {task.id} 参数已刷新", flush=True)
                    return
        except Exception as e:
            print(f"[snipe] 任务 {task.id} 参数刷新失败（继续用旧参数）: {type(e).__name__}: {e}", flush=True)


snipe_manager = SnipeManager()
