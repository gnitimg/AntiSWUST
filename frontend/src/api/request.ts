import axios from 'axios'

const request = axios.create({
  baseURL: '/api',
  timeout: 65000,
})

request.interceptors.request.use((config) => {
  const sessionId = localStorage.getItem('session_id')
  if (sessionId) {
    config.params = { ...(config.params || {}), session_id: sessionId }
  }
  return config
})

request.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    if (err?.response?.status === 401) {
      localStorage.removeItem('session_id')
      if (location.pathname !== '/login') location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default request
