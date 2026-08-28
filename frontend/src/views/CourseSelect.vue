<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import CourseFilter from '@/components/CourseFilter.vue'
import CourseList from '@/components/CourseList.vue'
import { useAuthStore } from '@/stores/auth'
import { useCourseStore } from '@/stores/course'
import type { CourseCategoryValue, CourseFilter as FilterModel, CourseOption } from '@/api/types'
import { CATEGORY_LABELS } from '@/api/types'

const router = useRouter()
const auth = useAuthStore()
const courseStore = useCourseStore()

const activeCategory = ref<CourseCategoryValue>('pe')
const flt = ref<FilterModel>({ only_available: false })
const hasFiltered = ref(false)

const categoryTabs = computed(() =>
  (Object.keys(CATEGORY_LABELS) as CourseCategoryValue[]).map((k) => ({ key: k, label: CATEGORY_LABELS[k] })),
)

const displayItems = computed<CourseOption[]>(() => {
  let items: CourseOption[]
  if (hasFiltered.value) {
    items = courseStore.filterResult
  } else {
    items = courseStore.grouped[activeCategory.value] ?? []
  }
  // 前端实时筛选（无需点击按钮）
  const f = flt.value
  return items.filter((c) => {
    if (f.only_available && c.capacity - c.selected_count <= 0) return false
    if (f.name && f.name.trim() && !c.name.includes(f.name.trim())) return false
    if (f.teacher && f.teacher.trim() && !c.teacher.includes(f.teacher.trim())) return false
    if (f.campus && f.campus.trim() && !c.campus.includes(f.campus.trim())) return false
    return true
  })
})

async function onSearch() {
  hasFiltered.value = true
  await courseStore.doFilter(activeCategory.value, flt.value)
  message.success(`筛选完成，共 ${courseStore.filterTotal} 条`)
}

function onReset() {
  hasFiltered.value = false
}

async function loadCurrent() {
  hasFiltered.value = false
  await courseStore.loadCategory(activeCategory.value)
}

watch(activeCategory, loadCurrent)

onMounted(async () => {
  await courseStore.loadCategories()
  await loadCurrent()
})

async function onLogout() {
  await auth.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <a-layout style="min-height: 100vh">
    <a-layout-header style="display: flex; align-items: center; justify-content: space-between">
      <div style="color: #fff; font-size: 18px">AntiSWUST 教务辅助系统 · 选课</div>
      <a-space>
        <span style="color: #fff">{{ auth.user?.name || auth.user?.student_id || '已登录' }}</span>
        <a-button size="small" @click="onLogout">退出</a-button>
      </a-space>
    </a-layout-header>
    <a-layout-content style="padding: 16px">
      <a-card :bordered="false">
        <a-tabs v-model:active-key="activeCategory" type="card">
          <a-tab-pane v-for="tab in categoryTabs" :key="tab.key" :tab="tab.label" />
        </a-tabs>
        <CourseFilter v-model="flt" @search="onSearch" @reset="onReset" />
        <div style="margin: 12px 0">
          <a-alert
            v-if="hasFiltered"
            type="success"
            :message="`符合筛选条件共 ${courseStore.filterTotal} 条`"
            show-icon
          />
          <a-alert v-else type="info" message="当前为全部可选课程，设置条件后点击筛选" show-icon />
        </div>
        <CourseList :items="displayItems" :category="activeCategory" :loading="courseStore.loading" />
      </a-card>
    </a-layout-content>
  </a-layout>
</template>
