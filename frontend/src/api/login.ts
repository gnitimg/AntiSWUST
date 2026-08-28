import request from './request'

export interface QRCodeResp {
  session_id: string
  ticket: string
  image_base64: string
  expire_at: number
}

export interface StatusResp {
  status: 'waiting' | 'scanned' | 'success' | 'expired' | 'network_error' | string
  session_id: string
  user: Record<string, unknown>
}

export const getQrcode = () => request.get<unknown, QRCodeResp>('/login/qrcode')
export const pollStatus = (sessionId: string, ticket: string) =>
  request.get<unknown, StatusResp>('/login/status', { params: { session_id: sessionId, ticket } })
export const checkSession = (sessionId: string) =>
  request.get<unknown, { session_id: string; user: Record<string, unknown> }>('/login/check', {
    params: { session_id: sessionId },
  })
export const logout = (sessionId: string) =>
  request.post<unknown, { ok: boolean }>('/login/logout', null, { params: { session_id: sessionId } })
