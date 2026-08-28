import { defineStore } from 'pinia'
import { ref } from 'vue'
import { filterCourses, getCategories, listCourses } from '@/api/course'
import type { CourseCategoryValue, CourseFilter, CourseOption } from '@/api/types'

export const useCourseStore = defineStore('course', () => {
  const categories = ref<Record<string, string>>({})
  const grouped = ref<Record<string, CourseOption[]>>({})
  const loading = ref(false)
  const filterResult = ref<CourseOption[]>([])
  const filterTotal = ref(0)

  async function loadCategories() {
    categories.value = await getCategories()
  }

  async function loadAll() {
    loading.value = true
    try {
      grouped.value = await listCourses()
    } finally {
      loading.value = false
    }
  }

  async function loadCategory(category: CourseCategoryValue) {
    loading.value = true
    try {
      const resp = await listCourses(category)
      grouped.value = { ...grouped.value, ...resp }
    } finally {
      loading.value = false
    }
  }

  async function doFilter(category: CourseCategoryValue, flt: CourseFilter) {
    loading.value = true
    try {
      const resp = await filterCourses(category, flt)
      filterResult.value = resp.items
      filterTotal.value = resp.total
    } finally {
      loading.value = false
    }
  }

  return { categories, grouped, loading, filterResult, filterTotal, loadCategories, loadAll, loadCategory, doFilter }
})
