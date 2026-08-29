import { getSelectedApi } from "@@/apis/course"
import { deleteGroupApi, listGroupsApi, type CourseGroup } from "@@/apis/groups"
import type { CourseCategoryValue, SelectedCourse } from "@@/apis/course/type"
import { defineStore } from "pinia"

/** 选课业务共享状态：已选课程清单 + 课程组（选课页/我的选课/抢课页/课程组页共用） */
export const useCourseStore = defineStore("course", () => {
  /** 已选课程清单（含退课参数） */
  const selected = ref<SelectedCourse[]>([])

  const selectedLoading = ref(false)

  /** 按 cid 索引，供课程列表"已选"行关联退课参数 */
  const selectedMap = computed<Record<string, SelectedCourse>>(() => {
    const map: Record<string, SelectedCourse> = {}
    for (const s of selected.value) {
      if (s.cid) map[s.cid] = s
    }
    return map
  })

  /** 课程组 */
  const groups = ref<CourseGroup[]>([])

  async function loadSelected(force = false) {
    selectedLoading.value = true
    try {
      const resp = await getSelectedApi(force)
      selected.value = resp.items
    } catch {
      selected.value = []
    } finally {
      selectedLoading.value = false
    }
  }

  async function loadGroups() {
    try {
      groups.value = (await listGroupsApi()).items
    } catch {
      groups.value = []
    }
  }

  async function removeGroup(groupId: string) {
    await deleteGroupApi(groupId)
    await loadGroups()
  }

  /** 当前分类在该课程组中的 cid 集合（用于筛选） */
  function groupCids(groupId: string): string[] {
    return (groups.value.find(g => g.id === groupId)?.courses ?? []).map(c => c.cid)
  }

  return { selected, selectedLoading, selectedMap, groups, loadSelected, loadGroups, removeGroup, groupCids }
})
