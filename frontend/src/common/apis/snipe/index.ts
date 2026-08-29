import { request } from "@/http/axios"
import type { CourseCategoryValue } from "@/common/apis/course/type"

export type SnipeStatus = "running" | "success" | "stopped" | "expired" | "error"

export interface SnipeTask {
  id: string
  category: CourseCategoryValue
  cid: string
  class_name: string
  name: string
  /** 请求间隔（秒），下限 0.5 */
  interval: number
  /** 持续时长（秒），0 = 不限 */
  duration: number
  status: SnipeStatus
  attempts: number
  last_reason: string
  last_error: string
  created_at: number
  finished_at: number | null
}

/** 启动抢课任务（同课程旧任务自动停止） */
export function startSnipeApi(data: {
  category: CourseCategoryValue
  course_id: string
  cid?: string
  class_name?: string
  name?: string
  /** 请求间隔秒数，后端强制下限 0.5 */
  interval: number
  /** 持续秒数，0 = 不限时 */
  duration: number
}) {
  return request<{ task: SnipeTask }>({
    url: "/snipe/start",
    method: "post",
    data
  })
}

/** 任务列表 */
export function listSnipeTasksApi() {
  return request<{ items: SnipeTask[] }>({
    url: "/snipe/tasks",
    method: "get"
  })
}

/** 停止单个任务 */
export function stopSnipeApi(taskId: string) {
  return request<{ ok: boolean }>({
    url: "/snipe/stop",
    method: "post",
    data: { task_id: taskId }
  })
}

/** 停止全部任务 */
export function stopAllSnipeApi() {
  return request<{ ok: boolean }>({
    url: "/snipe/stop_all",
    method: "post"
  })
}
