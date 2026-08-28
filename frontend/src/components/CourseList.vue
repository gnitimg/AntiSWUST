<script setup lang="ts">
import { Modal, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'
import { selectCourse } from '@/api/course'
import type { CourseCategoryValue, CourseOption } from '@/api/types'
import { CATEGORY_LABELS, WEEKDAY_LABELS } from '@/api/types'

const props = defineProps<{ items: CourseOption[]; category: CourseCategoryValue; loading: boolean }>()

function slotText(option: CourseOption): string {
  if (option.time_slots?.length) {
    return option.time_slots
      .map((s) => `${WEEKDAY_LABELS[s.day_of_week - 1] ?? ''} 第${s.start_node}-${s.end_node}节 周${s.weeks.join(',')}`)
      .join('；')
  }
  return (option.raw as Record<string, string>)?.['上课时间'] || '-'
}

const columns: TableColumnsType = [
  { title: '课程', dataIndex: 'name', key: 'name', width: 160, fixed: 'left' },
  { title: '代码', dataIndex: 'course_code', key: 'course_code', width: 80 },
  { title: '教师', dataIndex: 'teacher', key: 'teacher', width: 100 },
  { title: '校区', dataIndex: 'campus', key: 'campus', width: 70 },
  { title: '教学班', dataIndex: 'class_name', key: 'class_name', width: 80 },
  { title: '学分', dataIndex: 'credit', key: 'credit', width: 60 },
  { title: '时间', key: 'time', customRender: ({ record }) => slotText(record as CourseOption), width: 120 },
  { title: '地点', key: 'location', customRender: ({ record }) => (record as CourseOption).raw['上课地点'] as string || '-', width: 100 },
  { title: '状态', key: 'status', customRender: ({ record }) => (record as CourseOption).raw['状态'] as string || '-', width: 70 },
  {
    title: '余量/容量',
    key: 'remain',
    width: 90,
    customRender: ({ record }) => {
      const r = record as CourseOption
      return `${r.capacity - r.selected_count}/${r.capacity}`
    },
  },
  { title: '行课周次', key: 'weeks', customRender: ({ record }) => {
    const r = record as CourseOption
    const rawWeeks = (r.raw as Record<string, string>)?.['周次']
    return rawWeeks || (r.weeks_available?.length ? `${r.weeks_available[0]}-${r.weeks_available[r.weeks_available.length-1]}` : '-')
  }, width: 100, fixed: 'right' },
  { title: '操作', key: 'action', width: 80, fixed: 'right' },
]

function onConfirm(option: CourseOption) {
  Modal.confirm({
    title: '确认选课',
    content: `将选择《${option.name}》-${option.teacher}（${CATEGORY_LABELS[props.category]}）`,
    onOk: async () => {
      try {
        await selectCourse({ course_id: option.course_id, category: props.category, weeks: null })
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
      <template v-if="column.key === 'action'">
        <a-button
          type="link"
          size="small"
          :disabled="!(record as CourseOption).course_id.includes('|')"
          @click="onConfirm(record as CourseOption)"
        >选课</a-button>
      </template>
    </template>
  </a-table>
</template>
