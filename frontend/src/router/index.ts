import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
    { path: '/debug', name: 'debug', component: () => import('@/views/Debug.vue') },
    { path: '/', name: 'home', component: () => import('@/views/CourseSelect.vue') },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.name === 'login' || to.name === 'debug') return true
  const ok = await auth.verify()
  if (!ok) return { name: 'login' }
  return true
})

export default router
