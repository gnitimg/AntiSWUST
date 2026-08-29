import type { AxiosInstance, AxiosRequestConfig } from "axios"
import { getToken } from "@@/utils/local-storage"
import axios from "axios"
import { get } from "lodash-es"
import { useUserStore } from "@/pinia/stores/user"

/** 创建请求实例（AntiSWUST 后端返回裸 JSON，无 code 包装；401 由 HTTP 状态码表达） */
function createInstance() {
  const instance = axios.create()
  // 请求拦截器：注入 session_id（后端以 query 参数传递登录态）
  instance.interceptors.request.use((config) => {
    const token = getToken()
    if (token) {
      config.params = { session_id: token, ...(config.params || {}) }
    }
    return config
  }, error => Promise.reject(error))
  // 响应拦截器：直接返回 data；401 时登出并跳转登录页
  instance.interceptors.response.use(
    response => response.data,
    (error) => {
      const status = get(error, "response.status")
      const detail = get(error, "response.data.detail")
      if (status === 401) {
        // 会话失效：清除登录态并回到登录页（登录页自身接口除外）
        const url = get(error, "config.url") || ""
        if (!url.includes("/login/")) {
          useUserStore().logout()
        }
        error.message = detail || "登录态已失效，请重新扫码登录"
      } else {
        error.message = detail || error.message || "网络请求失败"
      }
      return Promise.reject(error)
    }
  )
  return instance
}

/** 创建请求方法 */
function createRequest(instance: AxiosInstance) {
  return <T>(config: AxiosRequestConfig): Promise<T> => {
    const defaultConfig: AxiosRequestConfig = {
      baseURL: import.meta.env.VITE_BASE_URL,
      // 选课数据抓取/登录长轮询耗时较长，放宽超时
      timeout: 65000
    }
    return instance({ ...defaultConfig, ...config })
  }
}

/** 用于请求的实例 */
const instance = createInstance()

/** 用于请求的方法 */
export const request = createRequest(instance)
