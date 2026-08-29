<script lang="ts" setup>
import { listCoursesApi } from "@@/apis/course"
import { CATEGORY_LABELS, type CourseCategoryValue, type CourseOption } from "@@/apis/course/type"
import { addGroupCourseApi, createGroupApi, removeGroupCourseApi, renameGroupApi } from "@@/apis/groups"
import { useCourseStore } from "@/pinia/stores/course"

defineOptions({ name: "CourseGroups" })

const courseStore = useCourseStore()

/** 新建课程组 */
const createDialog = reactive({ visible: false, name: "" })

async function onCreate() {
  const name = createDialog.name.trim()
  if (!name) {
    ElMessage.warning("请输入课程组名称")
    return
  }
  await createGroupApi(name)
  createDialog.visible = false
  createDialog.name = ""
  await courseStore.loadGroups()
  ElMessage.success("课程组已创建")
}

async function onRename(group: { id: string, name: string }) {
  const { value } = await ElMessageBox.prompt("新的课程组名称", "重命名", {
    inputValue: group.name,
    inputPattern: /\S+/,
    inputErrorMessage: "名称不能为空"
  })
  await renameGroupApi(group.id, value.trim())
  await courseStore.loadGroups()
}

async function onDelete(group: { id: string, name: string, courses: unknown[] }) {
  try {
    await ElMessageBox.confirm(`删除课程组「${group.name}」（含 ${group.courses.length} 门课程）？`, "确认删除", { type: "warning" })
  } catch {
    return
  }
  await courseStore.removeGroup(group.id)
  ElMessage.success("已删除")
}

async function onRemoveCourse(groupId: string, cid: string) {
  await removeGroupCourseApi(groupId, cid)
  await courseStore.loadGroups()
}

// #region 向组内添加课程
const addDialog = reactive({
  visible: false,
  group: null as { id: string, name: string } | null,
  category: "general" as CourseCategoryValue,
  keyword: "",
  items: [] as CourseOption[],
  loading: false
})

/** 已在组内的 cid，表格中禁用重复添加 */
const addedCids = computed(() =>
  new Set(courseStore.groups.find(g => g.id === addDialog.group?.id)?.courses.map(c => c.cid) ?? [])
)

async function openAdd(group: { id: string, name: string }) {
  addDialog.group = group
  addDialog.visible = true
  await loadAddCourses()
}

async function loadAddCourses() {
  addDialog.loading = true
  try {
    const resp = await listCoursesApi(addDialog.category)
    addDialog.items = resp[addDialog.category] ?? []
  } catch (e: any) {
    ElMessage.error(e?.message || "课程加载失败")
  } finally {
    addDialog.loading = false
  }
}

const addFiltered = computed(() =>
  addDialog.items.filter((c: CourseOption) => !addDialog.keyword || c.name.includes(addDialog.keyword.trim()))
)

async function onAdd(row: CourseOption) {
  if (!addDialog.group) return
  await addGroupCourseApi(addDialog.group.id, {
    cid: String(row.raw?.cid ?? ""),
    name: row.name,
    category: addDialog.category
  })
  await courseStore.loadGroups()
  ElMessage.success(`已把《${row.name}》加入「${addDialog.group.name}」`)
}
// #endregion

onMounted(() => {
  courseStore.loadGroups()
})
</script>

<template>
  <div class="app-container">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">课程组</span>
          <el-button type="primary" @click="createDialog.visible = true">
            新建课程组
          </el-button>
        </div>
      </template>
      <el-alert
        title="课程组用于把多门课程捆绑：在「所有选课」页的筛选栏选择课程组，即可只看组内课程"
        type="info"
        show-icon
        :closable="false"
        class="mb-3"
      />
      <el-empty v-if="!courseStore.groups.length" description="还没有课程组，点击右上角创建" />
      <el-collapse v-else>
        <el-collapse-item v-for="g in courseStore.groups" :key="g.id" :name="g.id">
          <template #title>
            <span class="group-title">
              {{ g.name }}
              <el-tag size="small" class="ml-2">
                {{ g.courses.length }} 门
              </el-tag>
            </span>
          </template>
          <div class="mb-2">
            <el-button size="small" @click="openAdd(g)">
              添加课程
            </el-button>
            <el-button size="small" @click="onRename(g)">
              重命名
            </el-button>
            <el-button size="small" type="danger" plain @click="onDelete(g)">
              删除课程组
            </el-button>
          </div>
          <el-table :data="g.courses" row-key="cid" size="small" border>
            <el-table-column label="课程" prop="name" min-width="200" show-overflow-tooltip />
            <el-table-column label="分类" width="130" align="center">
              <template #default="{ row }">
                {{ CATEGORY_LABELS[row.category as CourseCategoryValue] ?? row.category }}
              </template>
            </el-table-column>
            <el-table-column label="课程 ID" prop="cid" width="110" align="center" />
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }">
                <el-button link type="danger" size="small" @click="onRemoveCourse(g.id, row.cid)">
                  移除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 新建课程组 -->
    <el-dialog v-model="createDialog.visible" title="新建课程组" width="400px">
      <el-input v-model="createDialog.name" placeholder="课程组名称，如：大三上心愿单" maxlength="30" @keyup.enter="onCreate" />
      <template #footer>
        <el-button @click="createDialog.visible = false">
          取消
        </el-button>
        <el-button type="primary" @click="onCreate">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加课程 -->
    <el-dialog v-model="addDialog.visible" :title="`向「${addDialog.group?.name}」添加课程`" width="760px">
      <el-form inline class="mb-2">
        <el-form-item label="分类">
          <el-select v-model="addDialog.category" style="width: 160px" @change="loadAddCourses">
            <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input v-model="addDialog.keyword" clearable placeholder="课程名关键字" style="width: 200px" />
        </el-form-item>
        <el-button :loading="addDialog.loading" @click="loadAddCourses">
          刷新
        </el-button>
      </el-form>
      <el-table v-loading="addDialog.loading" :data="addFiltered" height="420" border stripe>
        <el-table-column label="课程" prop="name" min-width="220" show-overflow-tooltip />
        <el-table-column label="学分" prop="credit" width="60" align="center" />
        <el-table-column label="课程 ID" width="110" align="center">
          <template #default="{ row }">
            {{ row.raw?.cid }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" :disabled="addedCids.has(String(row.raw?.cid ?? ''))" @click="onAdd(row as CourseOption)">
              {{ addedCids.has(String(row.raw?.cid ?? "")) ? "已加入" : "加入" }}
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

.group-title {
  font-weight: 600;
}
</style>
