<script setup lang="ts">
import { ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'
import { selectCourse } from '@/api/course'
import type { CourseCategoryValue, CourseOption } from '@/api/types'
import { CATEGORY_LABELS, WEEKDAY_LABELS } from '@/api/types'

const props = defineProps<{ items: CourseOption[]; category: CourseCategoryValue; loading: boolean }>()

const selectedWeeks = ref<Record<string, number[]>>({})

function slotText(option: CourseOption): string {
  if (!option.time_slots?.length) return '-'
  return option.time_slots
    .map((s) => `${WEEKDAY_LABELS[s.day_of_week - 1] ?? ''} 第${s.start_node}-${s.end_node}节 周${s.weeks.join(',')}`)
    .join('；')
}

const columns: TableColumnsType = [
  { title: '课程', dataIndex: 'name', key: 'name', width: 160, fixed: 'left' },
  { title: '代码', dataIndex: 'course_code', key: 'course_code', width: 110 },
  { title: '教师', dataIndex: 'teacher', key: 'teacher', width: 100 },
  { title: '校区', dataIndex: 'campus', key: 'campus', width: 80 },
  { title: '教学班', dataIndex: 'class_name', key: 'class_name', width: 120 },
  { title: '学分', dataIndex: 'credit', key: 'credit', width: 70 },
  { title: '时间', key: 'time', customRender: ({ record }) => slotText(record as CourseOption), width: 260 },
  {
    title: '余量/容量',
    key: 'remain',
    width: 100,
    customRender: ({ record }) => {
      const r = record as CourseOption
      return `${r.capacity - r.selected_count}/${r.capacity}`
    },
  },
  { title: '期望周次', key: 'weeks', width: 200, fixed: 'right' },
  { title: '操作', key: 'action', width: 100, fixed: 'right' },
]

function onConfirm(option: CourseOption) {
  const weeks = selectedWeeks.value[option.course_id] ?? []
  Modal.confirm({
    title: '确认选课',
    content: `将选择《${option.name}》-${option.teacher}（${CATEGORY_LABELS[props.category]}）${weeks.length ? `，周次：${weeks.join(',')}` : ''}`,
    onOk: async () => {
      try {
        await selectCourse({ course_id: option.course_id, category: props.category, weeks: weeks.length ? weeks : null })
        message.success('选课请求已提交')
      } catch {
        message.error('选课失败，请重试')
      }
    },
  })
}
</script>

<template>
  <a-table
    :columns="columns"
    :data-source="props.items"
    :loading="props.loading"
    row-key="course_id"
    :scroll="{ x: 1300 }"
    :pagination="{ pageSize: 20, showSizeChanger: true }"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'weeks'">
        <a-select
          v-model:value="selectedWeeks[(record as CourseOption).course_id]"
          mode="multiple"
          allow-clear
          placeholder="勾选周次"
          style="min-width: 160px"
          :options="Array.from({ length: 25 }, (_, i) => ({ label: `第${i + 1}周`, value: i + 1 }))"
        />
      </template>
      <template v-else-if="column.key === 'action'">
        <a-button type="link" size="small" @click="onConfirm(record as CourseOption)">选课</a-button>
      </template>
    </template>
  </a-table>
</template>
