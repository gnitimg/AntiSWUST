import { request } from "@/http/axios"

/** 二维码信息 */
export interface QRCodeResp {
  session_id: string
  /** 微信 uuid，即轮询 ticket */
  ticket: string
  /** base64 图片 */
  image_base64: string
  /** 秒级 Unix 时间戳 */
  expire_at: number
}

export interface StatusResp {
  status: "waiting" | "scanned" | "success" | "expired" | "network_error" | string
  session_id: string
  user: Record<string, unknown>
  /** 失败原因详情（network_error 时后端透传） */
  detail?: string
}

/** 获取微信扫码登录二维码 */
export function getQrcodeApi() {
  return request<QRCodeResp>({
    url: "/login/qrcode",
    method: "get"
  })
}

/** 串行轮询扫码状态（后端代理微信长轮询，单次可 hold 30s+） */
export function pollStatusApi(sessionId: string, ticket: string) {
  return request<StatusResp>({
    url: "/login/status",
    method: "get",
    params: { session_id: sessionId, ticket }
  })
}

/** 校验会话有效性 */
export function checkSessionApi() {
  return request<{ session_id: string; user: Record<string, unknown> }>({
    url: "/login/check",
    method: "get"
  })
}

/** 登出 */
export function logoutApi(sessionId: string) {
  return request<{ ok: boolean }>({
    url: "/login/logout",
    method: "post",
    params: { session_id: sessionId }
  })
}
