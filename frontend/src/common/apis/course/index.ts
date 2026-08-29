import { request } from "@/http/axios"
import type { CourseCategoryValue, CourseOption, SelectedCourse } from "./type"

/** 课程分类标签 */
export function getCategoriesApi() {
  return request<Record<string, string>>({
    url: "/course/categories",
    method: "get"
  })
}

/**
 * 抓取分类课程列表
 * @param basic true 时只解析列表页（秒级返回，无教师/时间等详情），详情随后用全量请求补齐
 */
export function listCoursesApi(category: CourseCategoryValue, options: { basic?: boolean; force?: boolean } = {}) {
  return request<Record<string, CourseOption[]>>({
    url: "/course/list",
    method: "get",
    params: { category, basic: options.basic || undefined, force: options.force || undefined }
  })
}

/** 已选课程清单（含退课参数 chooser_id 等） */
export function getSelectedApi(force = false) {
  return request<{ items: SelectedCourse[] }>({
    url: "/course/selected",
    method: "get",
    params: { force: force || undefined }
  })
}

/** 提交选课 */
export function selectCourseApi(courseId: string, category: CourseCategoryValue) {
  return request<{ success?: boolean; reason?: string }>({
    url: "/course/select",
    method: "post",
    data: { course_id: courseId, category }
  })
}

/** 退课（course_id 与 chooser_id 均来自已选课程清单） */
export function cancelCourseApi(courseId: string, category: CourseCategoryValue, chooserId: string) {
  return request<{ success?: boolean; reason?: string }>({
    url: "/course/cancel",
    method: "post",
    data: { course_id: courseId, category, chooser_id: chooserId }
  })
}
