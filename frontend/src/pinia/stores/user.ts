import { checkSessionApi, logoutApi } from "@@/apis/login"
import { setToken as _setToken, getToken, removeToken } from "@@/utils/local-storage"
import { pinia } from "@/pinia"
import { resetRouter, router } from "@/router"
import { useSettingsStore } from "./settings"
import { useTagsViewStore } from "./tags-view"

export const useUserStore = defineStore("user", () => {
  const token = ref<string>(getToken() || "")

  /** 当前登录学生（name / student_id） */
  const userInfo = ref<Record<string, string>>({})

  const username = ref<string>("")

  /** 本系统无角色权限区分，恒为空数组（保留以兼容模板权限指令/守卫） */
  const roles = ref<string[]>([])

  const permissions = ref<string[]>([])

  const isGotUserInfo = ref<boolean>(false)

  const tagsViewStore = useTagsViewStore()

  const settingsStore = useSettingsStore()

  const setToken = (value: string) => {
    _setToken(value)
    token.value = value
  }

  /** 校验会话并拉取用户信息（后端 /api/login/check） */
  const getInfo = async () => {
    try {
      const data = await checkSessionApi()
      userInfo.value = (data.user || {}) as Record<string, string>
      username.value = userInfo.value.name || userInfo.value.student_id || "已登录"
    } catch (error) {
      // 会话失效：checkSessionApi 已 reject（401 → axios 拦截器登出逻辑）
      throw error
    }
    isGotUserInfo.value = true
  }

  /** 登出（通知后端删除会话文件） */
  const logout = async () => {
    if (token.value) {
      try {
        await logoutApi(token.value)
      } catch {
        /* 后端不可达也照常登出 */
      }
    }
    resetToken()
    resetRouter()
    resetTagsView()
    router.replace("/login")
  }

  const resetToken = () => {
    removeToken()
    token.value = ""
    userInfo.value = {}
    username.value = ""
    roles.value = []
    permissions.value = []
    isGotUserInfo.value = false
  }

  const resetTagsView = () => {
    if (!settingsStore.cacheTagsView) {
      tagsViewStore.delAllVisitedViews()
      tagsViewStore.delAllCachedViews()
    }
  }

  return { token, userInfo, username, roles, permissions, isGotUserInfo, setToken, getInfo, logout, resetToken }
})

/**
 * @description 在 SPA 应用中可用于在 pinia 实例被激活前使用 store
 * @description 在 SSR 应用中可用于在 setup 外使用 store
 */
export function useUserStoreOutside() {
  return useUserStore(pinia)
}
