<script lang="ts" setup>
import { cancelCourseApi } from "@@/apis/course"
import type { SelectedCourse } from "@@/apis/course/type"
import { useCourseStore } from "@/pinia/stores/course"

defineOptions({ name: "MyCourses" })

const courseStore = useCourseStore()
const cancelling = ref(false)

async function refresh() {
  await courseStore.loadSelected(true)
}

function onCancel(row: SelectedCourse) {
  if (row.locked) {
    ElMessage.warning("该选课记录被教务系统锁定（禁止修改），无法退课")
    return
  }
  if (!row.chooser_id || !row.course_id) {
    ElMessage.error("未获取到退课参数，请刷新重试")
    return
  }
  ElMessageBox.confirm(
    `将退选《${row.name}》${row.class_name ? `-${row.class_name}` : ""}${row.teacher ? `（${row.teacher}）` : ""}`,
    "确认退课",
    { type: "error", confirmButtonText: "退课" }
  )
    .then(async () => {
      // category 仅用于确定 CT 轮次（退课接口五类统一），传任意已有分类即可
      const resp = await cancelCourseApi(row.course_id, "general", row.chooser_id)
      if (resp.success) {
        ElMessage.success("退课成功")
        await refresh()
      } else {
        ElMessage.error(`退课失败：${resp.reason || "未知原因"}`)
      }
    })
    .catch(() => {})
}

onMounted(() => {
  courseStore.loadSelected()
})
</script>

<template>
  <div class="app-container">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">我的选课（{{ courseStore.selected.length }}）</span>
          <el-button :loading="courseStore.selectedLoading" @click="refresh">
            刷新
          </el-button>
        </div>
      </template>

      <el-alert
        title="标注「已锁定」的记录来自往期轮次，教务系统禁止修改；只有「可退」状态的课程能退课"
        type="info"
        show-icon
        :closable="false"
        class="mb-3"
      />

      <el-table v-loading="courseStore.selectedLoading" :data="courseStore.selected" row-key="course_id" border stripe>
        <el-table-column label="课程" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="教学班" prop="class_name" width="80" align="center" />
        <el-table-column label="教师" prop="teacher" width="100" />
        <el-table-column label="学分" prop="credit" width="60" align="center" />
        <el-table-column label="课程性质" prop="nature" width="90" align="center" />
        <el-table-column label="选课轮次" prop="round" width="90" align="center" />
        <el-table-column label="选课时间" prop="choose_time" width="150" align="center" />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.locked" type="info">已锁定</el-tag>
            <el-tag v-else type="success">可退</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" size="small" :disabled="row.locked || !row.chooser_id" @click="onCancel(row as SelectedCourse)">
              退课
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
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
