<script lang="ts" setup>
import type { CourseOption } from "@@/apis/course/type"
import { cancelCourseApi, listCoursesApi, selectCourseApi } from "@@/apis/course"
import { CATEGORY_LABELS, WEEKDAY_LABELS, type CourseCategoryValue } from "@@/apis/course/type"
import { addGroupCourseApi } from "@@/apis/groups"
import { useCourseStore } from "@/pinia/stores/course"

defineOptions({ name: "CoursePage" })

const route = useRoute()
const router = useRouter()
const courseStore = useCourseStore()

/** 当前分类（由路由 meta 指定） */
const category = computed(() => (route.meta.category as CourseCategoryValue) || "pe")
const categoryName = computed(() => CATEGORY_LABELS[category.value])

/** basic 阶段：仅列表页解析（秒出）；full 阶段：含教学班详情 */
const items = ref<CourseOption[]>([])
const stage = ref<"idle" | "basic" | "basic-done" | "full" | "error">("idle")
const fullError = ref("")
const refreshing = ref(false)

/** 筛选条件（前端实时过滤，无需点按钮） */
const filter = reactive({
  name: "",
  teacher: "",
  campus: "",
  day_of_week: undefined as number | undefined,
  node: undefined as number | undefined,
  only_available: false,
  groupId: ""
})

/** 默认抢课参数（localStorage 持久化，抢课弹窗读取） */
const snipeDefaults = reactive({
  interval: Number(localStorage.getItem("snipe-interval")) || 1,
  duration: Number(localStorage.getItem("snipe-duration")) || 600
})

const filteredItems = computed(() => {
  return items.value.filter((c: CourseOption) => {
    if (filter.only_available && c.capacity - c.selected_count <= 0) return false
    if (filter.name && !c.name.includes(filter.name.trim())) return false
    if (filter.teacher && !c.teacher.includes(filter.teacher.trim())) return false
    if (filter.campus && !c.campus.includes(filter.campus.trim())) return false
    if (filter.day_of_week !== undefined) {
      if (!c.time_slots?.some((s: { day_of_week: number }) => s.day_of_week === filter.day_of_week)) return false
    }
    if (filter.node !== undefined) {
      if (!c.time_slots?.some((s: { start_node: number, end_node: number }) => s.start_node <= filter.node! && filter.node! <= s.end_node)) return false
    }
    if (filter.groupId) {
      const cids = courseStore.groupCids(filter.groupId)
      if (cids.length && !cids.includes(String(c.raw?.cid ?? ""))) return false
    }
    return true
  })
})

function statusOf(row: any) {
  return (row.raw?.status as string) || (row.raw?.["状态"] as string) || ""
}

function cellOf(row: any, key: string) {
  return (row.raw?.[key] as string) || "-"
}

function slotText(row: any) {
  if (row.time_slots?.length) {
    return row.time_slots.map((s: { day_of_week: number, start_node: number, end_node: number }) => `${WEEKDAY_LABELS[s.day_of_week - 1] ?? ""}第${s.start_node}-${s.end_node}节`).join("；")
  }
  return cellOf(row, "上课时间")
}

function remainText(row: any) {
  if (!row.capacity) return "-"
  return `${row.capacity - row.selected_count}/${row.capacity}`
}

/** 阶段一：列表页秒出（课程级信息，含锁定/已选标记） */
async function loadBasic() {
  stage.value = "basic"
  try {
    const resp = await listCoursesApi(category.value, { basic: true })
    items.value = resp[category.value] ?? []
    stage.value = "basic-done"
  } catch {
    stage.value = "error"
  }
}

/** 阶段二：并行抓取教学班详情（教师/时间/地点/余量/选课参数） */
async function loadFull(force = false) {
  try {
    const resp = await listCoursesApi(category.value, { force })
    items.value = resp[category.value] ?? []
    stage.value = "full"
    fullError.value = ""
  } catch (e: any) {
    fullError.value = e?.message || "详情加载失败"
  }
}

async function refresh() {
  refreshing.value = true
  try {
    await Promise.all([loadFull(true), courseStore.loadSelected(true)])
  } finally {
    refreshing.value = false
  }
}

/** 切换分类时重新加载 */
watch(category, () => {
  items.value = []
  stage.value = "idle"
  loadBasic().then(() => loadFull())
})

onMounted(() => {
  loadBasic().then(() => loadFull())
  if (!courseStore.selected.length) courseStore.loadSelected()
  if (!courseStore.groups.length) courseStore.loadGroups()
})

// #region 选课 / 退课
async function onSelect(row: CourseOption) {
  const teacher = row.teacher || cellOf(row, "教师")
  try {
    await ElMessageBox.confirm(`将选择《${row.name}》${teacher ? `-${teacher}` : ""}（${categoryName.value}）`, "确认选课", { type: "warning" })
  } catch {
    return
  }
  const resp = await selectCourseApi(row.course_id, category.value)
  if (resp.success) {
    row.raw["状态"] = "已选"
    ElMessage.success("选课成功")
    courseStore.loadSelected(true)
  } else {
    ElMessage.error(`选课失败：${resp.reason || "未知原因"}`)
  }
}

/** 退课参数必须来自已选课程清单（按 cid 关联） */
function onCancel(row: CourseOption) {
  const cid = String(row.raw?.cid ?? "")
  const sel = courseStore.selectedMap[cid]
  if (!sel || !sel.chooser_id || !sel.course_id) {
    ElMessage.error("未获取到该记录的退课参数，请点击\"刷新\"重新加载已选清单")
    return
  }
  if (sel.locked) {
    ElMessage.warning("该选课记录被教务系统锁定（禁止修改），无法退课")
    return
  }
  ElMessageBox.confirm(`将退选《${sel.name}》${sel.class_name ? `-${sel.class_name}` : ""}${sel.teacher ? `（${sel.teacher}）` : ""}`, "确认退课", { type: "error", confirmButtonText: "退课" })
    .then(async () => {
      const resp = await cancelCourseApi(sel.course_id, category.value, sel.chooser_id)
      if (resp.success) {
        row.raw["状态"] = "可选"
        ElMessage.success("退课成功")
        courseStore.loadSelected(true)
      } else {
        ElMessage.error(`退课失败：${resp.reason || "未知原因"}`)
      }
    })
    .catch(() => {})
}
// #endregion

// #region 抢课
const snipeDialog = reactive({ visible: false, row: null as CourseOption | null })
const snipeForm = reactive({ interval: 1, duration: 600 })

function onSnipe(row: CourseOption) {
  snipeDialog.row = row
  snipeForm.interval = snipeDefaults.interval
  snipeForm.duration = snipeDefaults.duration
  snipeDialog.visible = true
}

async function confirmSnipe() {
  const row = snipeDialog.row
  if (!row) return
  if (snipeForm.interval < 0.5) {
    ElMessage.warning("请求间隔不能低于 0.5 秒")
    return
  }
  // 保存为默认设置
  snipeDefaults.interval = snipeForm.interval
  snipeDefaults.duration = snipeForm.duration
  localStorage.setItem("snipe-interval", String(snipeForm.interval))
  localStorage.setItem("snipe-duration", String(snipeForm.duration))
  const { startSnipeApi } = await import("@@/apis/snipe")
  try {
    await startSnipeApi({
      category: category.value,
      course_id: row.course_id,
      cid: String(row.raw?.cid ?? ""),
      class_name: row.class_name || String(row.raw?.["课序号"] ?? ""),
      name: row.name,
      interval: snipeForm.interval,
      duration: snipeForm.duration
    })
    ElMessage.success(`已开始抢《${row.name}》，可在 实验功能 → 抢课 查看进度`)
    snipeDialog.visible = false
  } catch (e: any) {
    ElMessage.error(e?.message || "启动抢课失败")
  }
}
// #endregion

// #region 加入课程组
async function onAddToGroup(groupId: string, row: CourseOption) {
  try {
    await addGroupCourseApi(groupId, {
      cid: String(row.raw?.cid ?? ""),
      name: row.name,
      category: category.value
    })
    await courseStore.loadGroups()
    ElMessage.success(`已加入课程组「${courseStore.groups.find(g => g.id === groupId)?.name ?? ""}」`)
  } catch (e: any) {
    ElMessage.error(e?.message || "加入课程组失败")
  }
}
// #endregion
</script>

<template>
  <div class="app-container">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">{{ categoryName }}</span>
          <el-space>
            <el-tag v-if="stage === 'full'" type="success" effect="plain">详情已加载</el-tag>
            <el-tag v-else-if="stage === 'basic-done'" type="warning" effect="plain">列表已加载，详情加载中…</el-tag>
            <el-button :loading="refreshing" @click="refresh">
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <el-alert v-if="stage === 'basic-done'" title="课程列表已就绪，教学班详情（教师/时间/余量）正在后台加载" type="info" show-icon :closable="false" class="mb-3" />
      <el-alert v-if="fullError" :title="`教学班详情加载失败：${fullError}（可点击刷新重试）`" type="error" show-icon :closable="false" class="mb-3" />

      <!-- 筛选栏 -->
      <el-form inline class="mb-3">
        <el-form-item label="课程名">
          <el-input v-model="filter.name" clearable placeholder="如 篮球" style="width: 130px" />
        </el-form-item>
        <el-form-item label="老师">
          <el-input v-model="filter.teacher" clearable placeholder="如 A老师" style="width: 120px" />
        </el-form-item>
        <el-form-item label="校区">
          <el-input v-model="filter.campus" clearable placeholder="如 新区" style="width: 100px" />
        </el-form-item>
        <el-form-item label="星期">
          <el-select v-model="filter.day_of_week" clearable placeholder="不限" style="width: 90px">
            <el-option v-for="(label, i) in WEEKDAY_LABELS" :key="label" :label="label" :value="i + 1" />
          </el-select>
        </el-form-item>
        <el-form-item label="节次">
          <el-select v-model="filter.node" clearable placeholder="不限" style="width: 90px">
            <el-option v-for="i in 13" :key="i" :label="`第${i}节`" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="课程组">
          <el-select v-model="filter.groupId" clearable placeholder="不限" style="width: 140px">
            <el-option v-for="g in courseStore.groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="仅看有余量">
          <el-switch v-model="filter.only_available" />
        </el-form-item>
      </el-form>

      <el-table
        v-loading="stage === 'basic'"
        :data="filteredItems"
        row-key="course_id"
        border
        stripe
        size="default"
      >
        <el-table-column label="课程" prop="name" min-width="180" fixed="left" show-overflow-tooltip />
        <el-table-column label="教师" min-width="90">
          <template #default="{ row }">
            {{ row.teacher || cellOf(row, "教师") }}
          </template>
        </el-table-column>
        <el-table-column label="校区" min-width="80">
          <template #default="{ row }">
            {{ row.campus || cellOf(row, "校区") }}
          </template>
        </el-table-column>
        <el-table-column label="教学班" min-width="70">
          <template #default="{ row }">
            {{ row.class_name || cellOf(row, "课序号") }}
          </template>
        </el-table-column>
        <el-table-column label="学分" prop="credit" width="60" />
        <el-table-column label="时间" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ slotText(row) }}
          </template>
        </el-table-column>
        <el-table-column label="地点" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">
            {{ cellOf(row, "上课地点") }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="95" align="center">
          <template #default="{ row }">
            <el-tag v-if="statusOf(row) === '锁定'" type="info">锁定</el-tag>
            <el-tag v-else-if="statusOf(row) === '已选'" type="success">已选</el-tag>
            <el-tag v-else-if="statusOf(row) === '已满'" type="danger">已满</el-tag>
            <el-tag v-else-if="statusOf(row) === '详情未加载'" type="warning">详情未加载</el-tag>
            <el-tag v-else-if="!statusOf(row)" type="info" effect="plain">加载中…</el-tag>
            <el-tag v-else>可选</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="余量/容量" width="95" align="center">
          <template #default="{ row }">
            {{ remainText(row) }}
          </template>
        </el-table-column>
        <el-table-column label="行课周次" width="90" align="center">
          <template #default="{ row }">
            {{ cellOf(row, "周次") }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="statusOf(row) === '已选'"
              link
              type="danger"
              size="small"
              @click="onCancel(row as CourseOption)"
            >
              退课
            </el-button>
            <el-tooltip
              v-else
              :content="statusOf(row) === '锁定' ? '该课程已锁定，不可选' : statusOf(row) === '已满' ? '该教学班已满，可尝试抢课' : !(row.course_id || '').includes('|') ? '教学班详情未加载，请刷新' : ''"
              :disabled="statusOf(row) === '可选'"
              placement="top"
            >
              <span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="statusOf(row) === '锁定' || statusOf(row) === '详情未加载' || !(row.course_id || '').includes('|')"
                  @click="onSelect(row as CourseOption)"
                >
                  选课
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip content="以设定频率自动重试选课，抢到自动停止" placement="top">
              <el-button link type="warning" size="small" :disabled="statusOf(row) === '锁定' || statusOf(row) === '已选'" @click="onSnipe(row as CourseOption)">
                抢课
              </el-button>
            </el-tooltip>
            <el-dropdown trigger="click" @command="(gid: string) => onAddToGroup(gid, row as CourseOption)">
              <el-button link type="info" size="small">
                加入组<el-icon class="el-icon--right"><arrow-down /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="!courseStore.groups.length" disabled>
                    暂无课程组，请先到 实验功能→课程组 创建
                  </el-dropdown-item>
                  <el-dropdown-item v-for="g in courseStore.groups" :key="g.id" :command="g.id">
                    {{ g.name }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 抢课参数弹窗 -->
    <el-dialog v-model="snipeDialog.visible" title="启动抢课" width="440px">
      <el-form label-width="90px">
        <el-form-item label="课程">
          <span>{{ snipeDialog.row?.name }} {{ snipeDialog.row?.class_name || "" }}</span>
        </el-form-item>
        <el-form-item label="请求间隔">
          <el-input-number v-model="snipeForm.interval" :min="0.5" :step="0.5" :precision="1" />
          <span class="ml-2 text-sm text-gray-400">秒（下限 0.5s，请勿过低以免触发教务限流）</span>
        </el-form-item>
        <el-form-item label="持续时间">
          <el-input-number v-model="snipeForm.duration" :min="0" :step="60" />
          <span class="ml-2 text-sm text-gray-400">秒（0 = 不限时，直到抢到）</span>
        </el-form-item>
        <el-alert title="抢到后该课程任务自动熔断停止；多门课可同时抢。请在 实验功能→抢课 页查看进度。" type="info" show-icon :closable="false" />
      </el-form>
      <template #footer>
        <el-button @click="snipeDialog.visible = false">取消</el-button>
        <el-button type="warning" @click="confirmSnipe">开始抢课</el-button>
      </template>
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
