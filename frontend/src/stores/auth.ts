import { defineStore } from 'pinia'
import { ref } from 'vue'
import { checkSession, logout as apiLogout } from '@/api/login'

export const useAuthStore = defineStore('auth', () => {
  const sessionId = ref<string | null>(localStorage.getItem('session_id'))
  const user = ref<Record<string, unknown>>({})

  function setSession(id: string, u: Record<string, unknown> = {}) {
    sessionId.value = id
    user.value = u
    localStorage.setItem('session_id', id)
  }

  async function verify(): Promise<boolean> {
    if (!sessionId.value) return false
    try {
      const resp = await checkSession(sessionId.value)
      user.value = resp.user
      return true
    } catch {
      clear()
      return false
    }
  }

  function clear() {
    sessionId.value = null
    user.value = {}
    localStorage.removeItem('session_id')
  }

  async function logout() {
    if (sessionId.value) {
      try {
        await apiLogout(sessionId.value)
      } catch {
        /* ignore */
      }
    }
    clear()
  }

  return { sessionId, user, setSession, verify, clear, logout }
})
