<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { getQrcode, pollStatus } from '@/api/login'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const sessionId = ref('')
const ticket = ref('')
const qrImage = ref('')
const status = ref<'loading' | 'waiting' | 'scanned' | 'success' | 'expired' | 'error'>('loading')
const errorMsg = ref('')
const expireAt = ref(0)

let pollTimer: ReturnType<typeof setTimeout> | null = null
let expireTimer: ReturnType<typeof setTimeout> | null = null
let polling = false

async function loadQrcode() {
  status.value = 'loading'
  errorMsg.value = ''
  try {
    const resp = await getQrcode()
    sessionId.value = resp.session_id
    ticket.value = resp.ticket
    qrImage.value = resp.image_base64
    // 后端 expire_at 为秒级 Unix 时间戳，前端 Date.now() 为毫秒级，需换算
    expireAt.value = resp.expire_at * 1000
    status.value = 'waiting'
    startPolling()
    startExpire()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || ''
    errorMsg.value = detail || '无法获取二维码，请确认已连接校园网或 atrust'
    status.value = 'error'
  }
}

// 串行轮询：等上一次返回再发下一次，避免请求堆积（后端为微信长轮询，单次可 hold 30s+）
function startPolling() {
  stopPolling()
  const tick = async () => {
    if (!sessionId.value || !ticket.value || polling) return
    polling = true
    try {
      const resp = await pollStatus(sessionId.value, ticket.value)
      if (resp.status === 'success') {
        status.value = 'success'
        auth.setSession(resp.session_id, resp.user)
        stopPolling()
        message.success('登录成功')
        router.replace({ name: 'home' })
        return
      } else if (resp.status === 'scanned') {
        status.value = 'scanned'
      } else if (resp.status === 'expired') {
        status.value = 'expired'
        stopPolling()
        return
      } else if (resp.status === 'network_error') {
        status.value = 'error'
        errorMsg.value = '无法连接学校认证服务器，请确认已连接 SWUST 校园网或 atrust'
        stopPolling()
        return
      }
    } catch {
      /* keep polling */
    } finally {
      polling = false
    }
    if (status.value === 'waiting' || status.value === 'scanned') {
      pollTimer = setTimeout(tick, 1000)
    }
  }
  pollTimer = setTimeout(tick, 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  polling = false
}

function startExpire() {
  if (expireTimer) clearTimeout(expireTimer)
  const remain = expireAt.value - Date.now()
  expireTimer = setTimeout(() => {
    status.value = 'expired'
    stopPolling()
  }, Math.max(remain, 0))
}

onMounted(loadQrcode)
onBeforeUnmount(() => {
  stopPolling()
  if (expireTimer) clearTimeout(expireTimer)
})
</script>

<template>
  <div class="login-wrap">
    <a-card class="login-card" title="西南科技大学教务辅助系统" :bordered="false">
      <a-alert
        type="warning"
        message="需连接 SWUST 校园网或 atrust VPN 才能登录"
        show-icon
        style="margin-bottom: 16px"
      />
      <div class="qr-area">
        <a-spin :spinning="status === 'loading'">
          <div class="qr-box">
            <img v-if="qrImage" :src="`data:image/png;base64,${qrImage}`" alt="登录二维码" />
            <div v-else class="qr-placeholder">
              <a-empty description="等待二维码" />
            </div>
            <div v-if="status === 'expired'" class="qr-mask">
              <a-button type="primary" @click="loadQrcode">二维码已过期，点击刷新</a-button>
            </div>
            <div v-else-if="status === 'error'" class="qr-mask">
              <div style="text-align: center; padding: 12px">
                <p style="margin-bottom: 12px">{{ errorMsg }}</p>
                <a-button type="primary" @click="loadQrcode">重试</a-button>
              </div>
            </div>
          </div>
        </a-spin>
      </div>
      <a-alert
        v-if="status === 'waiting'"
        type="info"
        message="请使用微信扫描二维码登录"
        show-icon
        style="margin-top: 16px"
      />
      <a-alert
        v-else-if="status === 'scanned'"
        type="warning"
        message="已扫描，请在微信上点击确认登录"
        show-icon
        style="margin-top: 16px"
      />
      <a-alert
        v-else-if="status === 'success'"
        type="success"
        message="登录成功，正在跳转..."
        show-icon
        style="margin-top: 16px"
      />
      <p class="tip">登录态本地保留 30 分钟，过期后需重新扫码</p>
    </a-card>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
}
.login-card {
  width: 380px;
}
.qr-area {
  display: flex;
  justify-content: center;
}
.qr-box {
  position: relative;
  width: 220px;
  height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #d9d9d9;
}
.qr-box img {
  width: 200px;
  height: 200px;
}
.qr-placeholder {
  width: 100%;
  display: flex;
  justify-content: center;
}
.qr-mask {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
}
.tip {
  margin-top: 12px;
  text-align: center;
  color: #999;
  font-size: 12px;
}
</style>
