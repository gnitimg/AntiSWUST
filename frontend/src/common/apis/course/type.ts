export type CourseCategoryValue = "pe" | "general" | "major_limited" | "supplement" | "retake"

export interface ClassTimeSlot {
  day_of_week: number
  start_node: number
  end_node: number
  weeks: number[]
}

export interface CourseOption {
  /** 可选行为 CID|CIDX|TID|TT|TSK|ST 编码；锁定/详情未加载行为课程 cid */
  course_id: string
  course_code: string
  name: string
  category: CourseCategoryValue
  teacher: string
  campus: string
  class_name: string
  capacity: number
  selected_count: number
  credit: number
  time_slots: ClassTimeSlot[]
  weeks_available: number[]
  /** 教务表头原样字段（规范键）+ 状态/cid/locked/detail_failed 等标记 */
  raw: Record<string, any>
}

export interface SelectedCourse {
  name: string
  class_name: string
  teacher: string
  credit: string
  nature: string
  round: string
  choose_time: string
  /** true = 选课记录被教务锁定（禁止修改），不可退 */
  locked: boolean
  cid: string
  /** 选课记录标识（removeTask 第 1 参，即退课 SCC 参数） */
  chooser_id: string
  /** 退课参数编码 CID|CIDX|TID|TT|TSK|ST */
  course_id: string
}

export const CATEGORY_LABELS: Record<CourseCategoryValue, string> = {
  pe: "体育项目",
  general: "全校通选课",
  major_limited: "计划课程",
  supplement: "补选低年级课程",
  retake: "重新学习（重修）"
}

export const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
