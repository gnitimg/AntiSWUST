import { request } from "@/http/axios"
import type { CourseCategoryValue } from "@/common/apis/course/type"

export interface GroupCourse {
  cid: string
  name: string
  category: CourseCategoryValue
}

export interface CourseGroup {
  id: string
  name: string
  courses: GroupCourse[]
}

export function listGroupsApi() {
  return request<{ items: CourseGroup[] }>({
    url: "/groups",
    method: "get"
  })
}

export function createGroupApi(name: string) {
  return request<{ group: CourseGroup }>({
    url: "/groups",
    method: "post",
    data: { name }
  })
}

export function renameGroupApi(groupId: string, name: string) {
  return request<{ ok: boolean }>({
    url: `/groups/${groupId}`,
    method: "put",
    data: { name }
  })
}

export function deleteGroupApi(groupId: string) {
  return request<{ ok: boolean }>({
    url: `/groups/${groupId}`,
    method: "delete"
  })
}

export function addGroupCourseApi(groupId: string, course: GroupCourse) {
  return request<{ ok: boolean }>({
    url: `/groups/${groupId}/courses`,
    method: "post",
    data: course
  })
}

export function removeGroupCourseApi(groupId: string, cid: string) {
  return request<{ ok: boolean }>({
    url: `/groups/${groupId}/courses/${cid}`,
    method: "delete"
  })
}
