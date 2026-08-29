<script lang="ts" setup>
import { listCoursesApi } from "@@/apis/course"
import { CATEGORY_LABELS, type CourseCategoryValue, type CourseOption } from "@@/apis/course/type"
import { listSnipeTasksApi, startSnipeApi, stopAllSnipeApi, stopSnipeApi, type SnipeTask } from "@@/apis/snipe"

defineOptions({ name: "Snipe" })

/** 任务列表轮询间隔 */
const POLL_MS = 2000

const tasks = ref<SnipeTask[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

/** 抢课默认设置（持久化，选课页"抢课"弹窗共用同一份） */
const settings = reactive({
  interval: Number(localStorage.getItem("snipe-interval")) || 1,
  duration: Number(localStorage.getItem("snipe-duration")) || 600
})

watch(settings, (s) => {
  localStorage.setItem("snipe-interval", String(s.interval))
  localStorage.setItem("snipe-duration", String(s.duration))
})

const runningCount = computed(() => tasks.value.filter(t => t.status === "running").length)

async function refreshTasks() {
  try {
    tasks.value = (await listSnipeTasksApi()).items
  } catch {
    /* 后端未启动时静默 */
  }
}

async function onStop(taskId: string) {
  await stopSnipeApi(taskId)
  await refreshTasks()
}

async function onStopAll() {
  await stopAllSnipeApi()
  await refreshTasks()
}

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false })
}

function elapsed(task: SnipeTask) {
  const end = task.finished_at ?? Date.now() / 1000
  const sec = Math.max(0, Math.round(end - task.created_at))
  const min = Math.floor(sec / 60)
  return min > 0 ? `${min}分${sec % 60}秒` : `${sec}秒`
}

const statusMeta: Record<string, { label: string, type: "primary" | "success" | "info" | "warning" | "danger" }> = {
  running: { label: "抢课中", type: "primary" },
  success: { label: "已抢到", type: "success" },
  stopped: { label: "已停止", type: "info" },
  expired: { label: "已到时", type: "warning" },
  error: { label: "出错", type: "danger" }
}

// #region 新增抢课任务
const pickDialog = reactive({
  visible: false,
  category: "general" as CourseCategoryValue,
  keyword: "",
  items: [] as CourseOption[],
  loading: false
})

async function openPick() {
  pickDialog.visible = true
  await loadPickCourses()
}

async function loadPickCourses() {
  pickDialog.loading = true
  try {
    const resp = await listCoursesApi(pickDialog.category)
    pickDialog.items = resp[pickDialog.category] ?? []
  } catch (e: any) {
    ElMessage.error(e?.message || "课程加载失败")
  } finally {
    pickDialog.loading = false
  }
}

const pickFiltered = computed(() =>
  pickDialog.items.filter((c: CourseOption) => {
    if (pickDialog.keyword && !c.name.includes(pickDialog.keyword.trim())) return false
    const status = (c.raw?.["状态"] as string) || ""
    // 锁定/已选的课程没有抢的意义
    return status !== "锁定" && status !== "已选"
  })
)

async function onPick(row: CourseOption) {
  const status = (row.raw?.["状态"] as string) || ""
  if (status === "已满" && !(row.course_id || "").includes("|")) {
    ElMessage.warning("该行教学班详情未加载，请稍后重试")
    return
  }
  try {
    await startSnipeApi({
      category: pickDialog.category,
      course_id: row.course_id,
      cid: String(row.raw?.cid ?? ""),
      class_name: row.class_name || String(row.raw?.["课序号"] ?? ""),
      name: row.name,
      interval: settings.interval,
      duration: settings.duration
    })
    ElMessage.success(`已开始抢《${row.name}》`)
    await refreshTasks()
  } catch (e: any) {
    ElMessage.error(e?.message || "启动抢课失败")
  }
}
// #endregion

onMounted(() => {
  refreshTasks()
  pollTimer = setInterval(refreshTasks, POLL_MS)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="app-container">
    <el-card shadow="never" class="mb-3">
      <template #header>
        <div class="card-header">
          <span class="title">抢课设置</span>
        </div>
      </template>
      <el-form inline>
        <el-form-item label="请求间隔">
          <el-input-number v-model="settings.interval" :min="0.5" :max="60" :step="0.5" :precision="1" />
          <span class="ml-2 text-sm text-gray-400">秒（下限 0.5s）</span>
        </el-form-item>
        <el-form-item label="持续时间">
          <el-input-number v-model="settings.duration" :min="0" :max="86400" :step="60" />
          <span class="ml-2 text-sm text-gray-400">秒（0 = 不限时，抢到为止）</span>
        </el-form-item>
        <el-form-item>
          <el-button type="warning" @click="openPick">
            新增抢课任务
          </el-button>
          <el-button :disabled="!runningCount" @click="onStopAll">
            全部停止（{{ runningCount }}）
          </el-button>
        </el-form-item>
      </el-form>
      <el-alert
        title="抢课以设定频率自动提交选课请求；抢到后该课程任务自动熔断。教务系统对同一会话近似串行处理，任务过多会互相排队，建议同时抢 2-4 门。"
        type="info"
        show-icon
        :closable="false"
      />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">抢课任务（{{ tasks.length }}）</span>
          <el-button @click="refreshTasks">
            刷新
          </el-button>
        </div>
      </template>
      <el-empty v-if="!tasks.length" description="暂无任务：在课程列表点「抢课」，或点击上方「新增抢课任务」" />
      <el-table v-else :data="tasks" row-key="id" border stripe>
        <el-table-column label="课程" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="教学班" prop="class_name" width="75" align="center" />
        <el-table-column label="分类" width="110" align="center">
          <template #default="{ row }">
            {{ CATEGORY_LABELS[row.category as CourseCategoryValue] ?? row.category }}
          </template>
        </el-table-column>
        <el-table-column label="间隔/时长" width="110" align="center">
          <template #default="{ row }">
            {{ row.interval }}s / {{ row.duration === 0 ? "不限" : `${row.duration}s` }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status as string]?.type ?? 'info'">
              {{ statusMeta[row.status as string]?.label ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="尝试次数" prop="attempts" width="90" align="center" />
        <el-table-column label="最近结果" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.last_error || row.last_reason || "-" }}
          </template>
        </el-table-column>
        <el-table-column label="已运行" width="100" align="center">
          <template #default="{ row }">
            {{ elapsed(row as SnipeTask) }}
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="95" align="center">
          <template #default="{ row }">
            {{ fmtTime((row as SnipeTask).created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'running'" link type="danger" size="small" @click="onStop((row as SnipeTask).id)">
              停止
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 选课弹窗 -->
    <el-dialog v-model="pickDialog.visible" title="选择要抢的课程" width="760px">
      <el-form inline class="mb-2">
        <el-form-item label="分类">
          <el-select v-model="pickDialog.category" style="width: 160px" @change="loadPickCourses">
            <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input v-model="pickDialog.keyword" clearable placeholder="课程名关键字" style="width: 200px" />
        </el-form-item>
        <el-button :loading="pickDialog.loading" @click="loadPickCourses">
          刷新
        </el-button>
      </el-form>
      <el-table v-loading="pickDialog.loading" :data="pickFiltered" height="420" border stripe>
        <el-table-column label="课程" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="教师" min-width="90">
          <template #default="{ row }">
            {{ row.teacher || "-" }}
          </template>
        </el-table-column>
        <el-table-column label="教学班" prop="class_name" width="75" align="center" />
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="(row.raw?.['状态'] as string) === '已满'" type="danger">
              已满
            </el-tag>
            <el-tag v-else type="success">
              {{ row.raw?.["状态"] || "可选" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="余量" width="90" align="center">
          <template #default="{ row }">
            {{ row.capacity ? `${row.capacity - row.selected_count}/${row.capacity}` : "-" }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="warning" size="small" @click="onPick(row as CourseOption)">
              抢
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header .title {
  font-size: 16px;
  font-weight: 600;
}
</style>
