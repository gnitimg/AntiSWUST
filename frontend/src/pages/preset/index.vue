<script lang="ts" setup>
import type { UploadFile } from "element-plus"
import { listCoursesApi } from "@@/apis/course"
import { CATEGORY_LABELS, WEEKDAY_LABELS, type CourseCategoryValue, type CourseOption } from "@@/apis/course/type"
import {
  createPresetApi,
  deletePresetApi,
  getPresetRunApi,
  importPresetsApi,
  listPresetsApi,
  startPresetRunApi,
  stopPresetRunApi,
  updatePresetApi,
  type PresetEntry,
  type PresetRun
} from "@@/apis/preset"

defineOptions({ name: "PresetCourses" })

const entries = ref<PresetEntry[]>([])
const loading = ref(false)

/** 运行状态（2s 轮询） */
const run = ref<PresetRun | null>(null)
let runTimer: ReturnType<typeof setInterval> | null = null

// #region 条目 CRUD
async function loadEntries() {
  loading.value = true
  try {
    entries.value = (await listPresetsApi()).items
  } finally {
    loading.value = false
  }
}

async function onToggleEnabled(entry: PresetEntry) {
  await updatePresetApi(entry.id, { ...entry, enabled: entry.enabled })
}

async function onDelete(entry: PresetEntry) {
  await deletePresetApi(entry.id)
  await loadEntries()
}

// #region 手动录入 / 编辑
const editDialog = reactive({
  visible: false,
  mode: "create" as "create" | "edit",
  form: {
    id: "",
    category: "pe" as CourseCategoryValue,
    name: "",
    teacher: "",
    class_name: "",
    campus: "",
    day_of_week: undefined as number | undefined,
    node: undefined as number | undefined,
    enabled: true
  }
})

function openCreate() {
  editDialog.mode = "create"
  Object.assign(editDialog.form, {
    id: "", category: "pe", name: "", teacher: "", class_name: "", campus: "",
    day_of_week: undefined, node: undefined, enabled: true
  })
  editDialog.visible = true
}

function openEdit(entry: PresetEntry) {
  editDialog.mode = "edit"
  Object.assign(editDialog.form, { ...entry, day_of_week: entry.day_of_week ?? undefined, node: entry.node ?? undefined })
  editDialog.visible = true
}

async function submitEdit() {
  const f = editDialog.form
  if (!f.name.trim()) {
    ElMessage.warning("课程名必填")
    return
  }
  const payload = {
    category: f.category,
    name: f.name.trim(),
    teacher: f.teacher.trim(),
    class_name: f.class_name.trim(),
    campus: f.campus.trim(),
    day_of_week: f.day_of_week ?? null,
    node: f.node ?? null,
    enabled: f.enabled
  }
  if (editDialog.mode === "create") {
    await createPresetApi(payload)
    ElMessage.success("已添加预置课程")
  } else {
    await updatePresetApi(f.id, payload)
    ElMessage.success("已保存")
  }
  editDialog.visible = false
  await loadEntries()
}
// #endregion

// #region CSV 导入（UTF-8 失败自动回退 GBK，兼容 Excel 导出）
const importDialog = reactive({
  visible: false,
  category: "pe" as CourseCategoryValue,
  text: "",
  importing: false
})

function openImport() {
  importDialog.text = ""
  importDialog.visible = true
}

function onFileChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  raw.arrayBuffer().then((buf) => {
    let text = new TextDecoder("utf-8").decode(buf)
    if (text.includes("\uFFFD")) {
      try {
        text = new TextDecoder("gbk").decode(buf)
      } catch {
        /* 保留 utf-8 结果 */
      }
    }
    importDialog.text = text
  })
}

async function submitImport() {
  if (!importDialog.text.trim()) {
    ElMessage.warning("请先上传 CSV 文件或粘贴内容")
    return
  }
  importDialog.importing = true
  try {
    const resp = await importPresetsApi(importDialog.text, importDialog.category)
    ElMessage.success(`已导入 ${resp.imported} 条预置课程`)
    importDialog.visible = false
    await loadEntries()
  } catch (e: any) {
    ElMessage.error(e?.message || "导入失败")
  } finally {
    importDialog.importing = false
  }
}
// #endregion

// #region 匹配预览（对照真实课程列表）
const preview = reactive({
  visible: false,
  loading: false,
  category: "pe" as CourseCategoryValue,
  rows: [] as { entry: PresetEntry, matched: string, status: "matched" | "none" }[]
})

async function openPreview() {
  preview.visible = true
  preview.loading = true
  preview.rows = []
  try {
    const cats = [...new Set(entries.value.filter(e => e.enabled).map(e => e.category))]
    for (const cat of cats) {
      const resp = await listCoursesApi(cat)
      const options: CourseOption[] = resp[cat] ?? []
      for (const entry of entries.value.filter(e => e.enabled && e.category === cat)) {
        const matched = matchPreview(entry, options)
        preview.rows.push({
          entry,
          matched: matched ? `${matched.name} ${matched.class_name}（${matched.teacher || "未知教师"}）` : "",
          status: matched ? "matched" : "none"
        })
      }
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "匹配预览失败（需要已登录）")
  } finally {
    preview.loading = false
  }
}

/** 与后端 PresetService.match 同规则的简化版（仅预览展示） */
function matchPreview(entry: PresetEntry, options: CourseOption[]): CourseOption | null {
  const norm = (s?: string) => (s || "").replace(/\s+/g, "").toLowerCase()
  const name = norm(entry.name)
  const cands = options.filter((o) => {
    const on = norm(o.name)
    if (!on || !(name.includes(on) || on.includes(name))) return false
    if (entry.teacher && !norm(o.teacher).includes(norm(entry.teacher))) return false
    if (entry.class_name) {
      const a = norm(entry.class_name)
      const b = norm(o.class_name)
      if (a !== b && !b.includes(a)) return false
    }
    if (entry.campus && !norm(o.campus).includes(norm(entry.campus))) return false
    if (entry.day_of_week && !o.time_slots?.some(s => s.day_of_week === entry.day_of_week)) return false
    if (entry.node && !o.time_slots?.some(s => s.start_node <= entry.node! && entry.node! <= s.end_node)) return false
    return true
  })
  cands.sort((a, b) => (b.capacity - b.selected_count) - (a.capacity - a.selected_count))
  return cands[0] ?? null
}
// #endregion

// #region 自动选课运行
const runForm = reactive({
  useStartTime: false,
  startTime: "" as string,
  retry: true,
  interval: 5,
  stop_same_category: true
})

async function onStartRun() {
  if (!entries.value.some(e => e.enabled)) {
    ElMessage.warning("请先添加并启用预置课程")
    return
  }
  let startAt: number | undefined
  if (runForm.useStartTime && runForm.startTime) {
    startAt = new Date(runForm.startTime).getTime() / 1000
    if (startAt <= Date.now() / 1000) {
      ElMessage.warning("开始时间已过，将立即开始")
      startAt = undefined
    }
  }
  await startPresetRunApi({
    start_at: startAt,
    retry: runForm.retry,
    interval: runForm.interval,
    stop_same_category: runForm.stop_same_category
  })
  ElMessage.success(runForm.useStartTime && startAt ? "已设定，到点自动开始" : "预置选课已开始")
  await refreshRun()
}

async function onStopRun() {
  await stopPresetRunApi()
  await refreshRun()
}

async function refreshRun() {
  try {
    run.value = (await getPresetRunApi()).run
  } catch {
    /* 未登录时忽略 */
  }
}

const statusMeta: Record<string, { label: string, type: "primary" | "success" | "info" | "warning" | "danger" }> = {
  waiting: { label: "等待开始", type: "warning" },
  running: { label: "运行中", type: "primary" },
  finished: { label: "已结束", type: "success" },
  stopped: { label: "已停止", type: "info" },
  error: { label: "出错", type: "danger" }
}

const resultMeta: Record<string, { label: string, type: "primary" | "success" | "info" | "warning" | "danger" }> = {
  pending: { label: "待运行", type: "info" },
  unmatched: { label: "未匹配", type: "warning" },
  submitted: { label: "未成功", type: "warning" },
  success: { label: "已选中", type: "success" },
  skipped: { label: "跳过", type: "info" },
  failed: { label: "失败", type: "danger" }
}

function fmtTime(ts?: number | null) {
  return ts ? new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false }) : "-"
}

/** el-alert 的 type 不接受 danger，需要映射为 error */
const runAlertType = computed(() => {
  const t = run.value ? statusMeta[run.value.status]?.type : undefined
  return t === "danger" ? "error" : t ?? "info"
})
// #endregion

onMounted(() => {
  loadEntries()
  refreshRun()
  runTimer = setInterval(refreshRun, 2000)
})

onBeforeUnmount(() => {
  if (runTimer) clearInterval(runTimer)
})
</script>


<template>
  <div class="app-container">
    <el-card shadow="never" class="mb-3">
      <template #header>
        <div class="card-header">
          <span class="title">预置课程（{{ entries.length }}）</span>
          <el-space>
            <el-button type="primary" @click="openCreate">
              手动添加
            </el-button>
            <el-button @click="openImport">
              导入 CSV
            </el-button>
            <el-button :loading="preview.loading" @click="openPreview">
              匹配预览
            </el-button>
          </el-space>
        </div>
      </template>

      <el-alert
        title="提前录入/导入选课意向（体育项目等），开始选课后系统自动匹配真实课程并按优先级（数字小者先）提交；提交失败且开启重试时将自动重试"
        type="info"
        show-icon
        :closable="false"
        class="mb-3"
      />

      <el-empty v-if="!entries.length && !loading" description="暂无预置课程：手动添加或导入教务提前公布的课程 CSV" />
      <el-table v-else v-loading="loading" :data="entries" row-key="id" border stripe size="default">
        <el-table-column label="优先级" prop="priority" width="75" align="center" />
        <el-table-column label="分类" width="120" align="center">
          <template #default="{ row }">
            {{ CATEGORY_LABELS[row.category as CourseCategoryValue] ?? row.category }}
          </template>
        </el-table-column>
        <el-table-column label="课程名" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="教师" prop="teacher" width="100" />
        <el-table-column label="课序号" prop="class_name" width="80" align="center" />
        <el-table-column label="校区" prop="campus" width="90" align="center" />
        <el-table-column label="星期" width="80" align="center">
          <template #default="{ row }">
            {{ row.day_of_week ? WEEKDAY_LABELS[row.day_of_week - 1] : "-" }}
          </template>
        </el-table-column>
        <el-table-column label="节次" prop="node" width="70" align="center">
          <template #default="{ row }">
            {{ row.node ? `第${row.node}节` : "-" }}
          </template>
        </el-table-column>
        <el-table-column label="启用" width="75" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="onToggleEnabled(row as PresetEntry)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row as PresetEntry)">
              编辑
            </el-button>
            <el-button link type="danger" size="small" @click="onDelete(row as PresetEntry)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">自动选课</span>
          <el-space>
            <el-button
              v-if="run && (run.status === 'waiting' || run.status === 'running')"
              type="danger"
              @click="onStopRun"
            >
              停止
            </el-button>
            <el-button v-else type="warning" @click="onStartRun">
              开始预置选课
            </el-button>
          </el-space>
        </div>
      </template>

      <el-form inline>
        <el-form-item label="定时开始">
          <el-switch v-model="runForm.useStartTime" />
        </el-form-item>
        <el-form-item v-if="runForm.useStartTime">
          <el-date-picker v-model="runForm.startTime" type="datetime" placeholder="选课开放时间" format="YYYY-MM-DD HH:mm:ss" />
        </el-form-item>
        <el-form-item label="失败重试">
          <el-switch v-model="runForm.retry" />
        </el-form-item>
        <el-form-item v-if="runForm.retry" label="重试间隔">
          <el-input-number v-model="runForm.interval" :min="2" :max="120" :step="1" />
          <span class="ml-2 text-sm text-gray-400">秒</span>
        </el-form-item>
        <el-form-item label="同类只选一门">
          <el-switch v-model="runForm.stop_same_category" />
        </el-form-item>
      </el-form>

      <template v-if="run">
        <el-alert
          :title="`运行状态：${statusMeta[run.status]?.label ?? run.status}（第 ${run.cycles} 轮）${run.error ? ' · ' + run.error : ''}`"
          :type="runAlertType"
          show-icon
          :closable="false"
          class="mb-3"
        />
        <el-table :data="Object.values(run.results)" row-key="preset_id" border size="small">
          <el-table-column label="课程" prop="name" min-width="180" show-overflow-tooltip />
          <el-table-column label="分类" width="110" align="center">
            <template #default="{ row }">
              {{ CATEGORY_LABELS[row.category as CourseCategoryValue] ?? row.category }}
            </template>
          </el-table-column>
          <el-table-column label="匹配到" prop="matched" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="resultMeta[row.status as string]?.type ?? 'info'">
                {{ resultMeta[row.status as string]?.label ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" prop="message" min-width="150" show-overflow-tooltip />
          <el-table-column label="尝试" prop="attempts" width="60" align="center" />
        </el-table>
      </template>
      <el-empty v-else description="尚未启动：设置参数后点击「开始预置选课」" :image-size="80" />
    </el-card>

    <!-- 手动添加/编辑 -->
    <el-dialog v-model="editDialog.visible" :title="editDialog.mode === 'create' ? '添加预置课程' : '编辑预置课程'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="分类">
          <el-select v-model="editDialog.form.category" style="width: 100%">
            <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="课程名" required>
          <el-input v-model="editDialog.form.name" placeholder="如 篮球俱乐部 / 大学体育5——篮球俱乐部" />
        </el-form-item>
        <el-form-item label="教师">
          <el-input v-model="editDialog.form.teacher" placeholder="留空则不限" />
        </el-form-item>
        <el-form-item label="课序号">
          <el-input v-model="editDialog.form.class_name" placeholder="如 T17，留空则不限" />
        </el-form-item>
        <el-form-item label="校区">
          <el-input v-model="editDialog.form.campus" placeholder="留空则不限" />
        </el-form-item>
        <el-form-item label="星期">
          <el-select v-model="editDialog.form.day_of_week" clearable placeholder="不限" style="width: 100%">
            <el-option v-for="(label, i) in WEEKDAY_LABELS" :key="label" :label="label" :value="i + 1" />
          </el-select>
        </el-form-item>
        <el-form-item label="节次">
          <el-input-number v-model="editDialog.form.node" :min="1" :max="15" placeholder="不限" style="width: 100%" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editDialog.form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog.visible = false">
          取消
        </el-button>
        <el-button type="primary" @click="submitEdit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- CSV 导入 -->
    <el-dialog v-model="importDialog.visible" title="导入 CSV 课程清单" width="600px">
      <el-form label-width="80px">
        <el-form-item label="所属分类">
          <el-select v-model="importDialog.category" style="width: 100%">
            <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="CSV 文件">
          <el-upload :auto-upload="false" :show-file-list="false" accept=".csv,.txt" :on-change="onFileChange">
            <el-button>
              选择文件
            </el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="内容预览">
          <el-input v-model="importDialog.text" type="textarea" :rows="8" placeholder="也可直接粘贴 CSV 文本，首行为表头（课程名/教师/课序号/校区/上课时间…），无表头按 课程名,教师,课序号,校区,时间 顺序解析" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialog.visible = false">
          取消
        </el-button>
        <el-button type="primary" :loading="importDialog.importing" @click="submitImport">
          导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 匹配预览 -->
    <el-dialog v-model="preview.visible" title="匹配预览（对照当前真实课程列表）" width="720px">
      <el-table v-loading="preview.loading" :data="preview.rows" height="420" border size="small">
        <el-table-column label="预置课程" prop="entry.name" min-width="160" show-overflow-tooltip />
        <el-table-column label="约束" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ [row.entry.teacher, row.entry.class_name, row.entry.campus].filter(Boolean).join(" / ") || "仅课程名" }}
          </template>
        </el-table-column>
        <el-table-column label="匹配结果" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.status === 'matched'" type="success">
              {{ row.matched }}
            </el-tag>
            <el-tag v-else type="warning">
              未匹配
            </el-tag>
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
