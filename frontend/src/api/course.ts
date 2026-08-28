import request from './request'
import type { CourseCategoryValue, CourseFilter, CourseOption, SelectCourseRequest } from './types'

export const getCategories = () =>
  request.get<unknown, Record<string, string>>('/course/categories')

export const listCourses = (category?: CourseCategoryValue) =>
  request.get<unknown, Record<string, CourseOption[]>>('/course/list', { params: { category } })

export const filterCourses = (category: CourseCategoryValue, flt: CourseFilter) =>
  request.post<unknown, { category: string; total: number; items: CourseOption[] }>(
    '/course/filter',
    flt,
    { params: { category } },
  )

export const selectCourse = (req: SelectCourseRequest) =>
  request.post<unknown, Record<string, unknown>>('/course/select', req)
