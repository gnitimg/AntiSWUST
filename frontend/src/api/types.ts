export interface ClassTimeSlot {
  day_of_week: number
  start_node: number
  end_node: number
  weeks: number[]
}

export type CourseCategoryValue =
  | 'pe'
  | 'general'
  | 'major_limited'
  | 'supplement'
  | 'retake'

export interface CourseOption {
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
  raw: Record<string, unknown>
}

export interface CourseFilter {
  name?: string | null
  teacher?: string | null
  campus?: string | null
  day_of_week?: number | null
  node?: number | null
  weeks?: number[] | null
  min_remaining?: number | null
  only_available?: boolean
}

export interface SelectCourseRequest {
  course_id: string
  category: CourseCategoryValue
  weeks?: number[] | null
}

export const CATEGORY_LABELS: Record<CourseCategoryValue, string> = {
  pe: '体育课',
  general: '全校通选课',
  major_limited: '专业限选课',
  supplement: '补选低年级课程',
  retake: '重新学习（重修）',
}

export const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
