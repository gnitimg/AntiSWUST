<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { CourseFilter } from '@/api/types'
import { WEEKDAY_LABELS } from '@/api/types'

const props = defineProps<{ modelValue: CourseFilter }>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: CourseFilter): void
  (e: 'search'): void
  (e: 'reset'): void
}>()

const form = reactive<CourseFilter>({
  name: props.modelValue.name ?? null,
  teacher: props.modelValue.teacher ?? null,
  campus: props.modelValue.campus ?? null,
  day_of_week: props.modelValue.day_of_week ?? null,
  node: props.modelValue.node ?? null,
  weeks: props.modelValue.weeks ?? null,
  min_remaining: props.modelValue.min_remaining ?? null,
  only_available: props.modelValue.only_available ?? false,
})

const weekOptions = Array.from({ length: 25 }, (_, i) => ({ label: `第${i + 1}周`, value: i + 1 }))
const nodeOptions = Array.from({ length: 13 }, (_, i) => ({ label: `第${i + 1}节`, value: i + 1 }))

function sync() {
  emit('update:modelValue', { ...form })
}

function onSearch() {
  sync()
  emit('search')
}

function onReset() {
  form.name = null
  form.teacher = null
  form.campus = null
  form.day_of_week = null
  form.node = null
  form.weeks = null
  form.min_remaining = null
  form.only_available = false
  sync()
  emit('reset')
}

watch(
  () => props.modelValue,
  (v) => {
    Object.assign(form, v)
  },
)
</script>

<template>
  <a-form layout="inline" :model="form">
    <a-form-item label="课程名">
      <a-input v-model:value="form.name" allow-clear placeholder="如 篮球" @change="sync" />
    </a-form-item>
    <a-form-item label="老师">
      <a-input v-model:value="form.teacher" allow-clear placeholder="如 A老师" @change="sync" />
    </a-form-item>
    <a-form-item label="校区">
      <a-input v-model:value="form.campus" allow-clear placeholder="如 新区" @change="sync" />
    </a-form-item>
    <a-form-item label="星期">
      <a-select
        v-model:value="form.day_of_week"
        allow-clear
        placeholder="不限"
        style="width: 100px"
        :options="WEEKDAY_LABELS.map((l, i) => ({ label: l, value: i + 1 }))"
        @change="sync"
      />
    </a-form-item>
    <a-form-item label="节次">
      <a-select
        v-model:value="form.node"
        allow-clear
        placeholder="不限"
        style="width: 100px"
        :options="nodeOptions"
        @change="sync"
      />
    </a-form-item>
    <a-form-item label="周次">
      <a-select
        v-model:value="form.weeks"
        mode="multiple"
        allow-clear
        placeholder="勾选期望周数"
        style="min-width: 180px"
        :options="weekOptions"
        @change="sync"
      />
    </a-form-item>
    <a-form-item label="仅看有余量">
      <a-switch v-model:checked="form.only_available" @change="sync" />
    </a-form-item>
    <a-form-item>
      <a-space>
        <a-button type="primary" @click="onSearch">筛选</a-button>
        <a-button @click="onReset">重置</a-button>
      </a-space>
    </a-form-item>
  </a-form>
</template>
