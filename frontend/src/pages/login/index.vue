<script lang="ts" setup>
import { getQrcodeApi, pollStatusApi } from "@@/apis/login"
import { useUserStore } from "@/pinia/stores/user"

defineOptions({ name: "Login" })

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const sessionId = ref("")
const ticket = ref("")
const qrImage = ref("")
const status = ref<"loading" | "waiting" | "scanned" | "success" | "expired" | "error">("loading")
const errorMsg = ref("")
const expireAt = ref(0)

let pollTimer: ReturnType<typeof setTimeout> | null = null
let expireTimer: ReturnType<typeof setTimeout> | null = null
let polling = false

/** 二维码不可扫时模糊：加载中/已扫描/已过期/出错，防止误扫 */
const qrBlurred = computed(() =>
  status.value === "loading" || status.value === "scanned" || status.value === "expired" || status.value === "error"
)

async function loadQrcode() {
  status.value = "loading"
  errorMsg.value = ""
  try {
    const resp = await getQrcodeApi()
    sessionId.value = resp.session_id
    ticket.value = resp.ticket
    qrImage.value = resp.image_base64
    // 后端 expire_at 为秒级 Unix 时间戳
    expireAt.value = resp.expire_at * 1000
    status.value = "waiting"
    startPolling()
    startExpire()
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || "无法获取二维码，请确认已连接校园网或 atrust"
    status.value = "error"
  }
}

/** 串行轮询：等上一次返回再发下一次，避免长轮询请求堆积 */
function startPolling() {
  stopPolling()
  const tick = async () => {
    if (!sessionId.value || !ticket.value || polling) return
    polling = true
    try {
      const resp = await pollStatusApi(sessionId.value, ticket.value)
      if (resp.status === "success") {
        status.value = "success"
        userStore.setToken(sessionId.value)
        stopPolling()
        ElMessage.success("登录成功")
        const redirect = (route.query.redirect as string) || "/"
        router.replace(redirect)
        return
      } else if (resp.status === "scanned") {
        status.value = "scanned"
      } else if (resp.status === "expired") {
        status.value = "expired"
        stopPolling()
        return
      } else if (resp.status === "network_error") {
        status.value = "error"
        errorMsg.value = resp.detail || "无法连接学校认证服务器，请确认已连接 SWUST 校园网或 atrust"
        stopPolling()
        return
      }
    } catch {
      /* 继续轮询 */
    } finally {
      polling = false
    }
    if (status.value === "waiting" || status.value === "scanned") {
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
    status.value = "expired"
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
  <div class="login-container">
    <el-card class="login-card" shadow="always">
      <div class="title">
        <h2>AntiSWUST 教务辅助系统</h2>
        <p class="sub">微信扫码登录 · 需连接校园网或 atrust VPN</p>
      </div>

      <div class="qr-area">
        <div v-loading="status === 'loading'" class="qr-box">
          <img
            v-if="qrImage"
            :src="`data:image/png;base64,${qrImage}`"
            alt="登录二维码"
            :class="{ blurred: qrBlurred }"
          >
          <div v-else class="qr-placeholder">
            <el-empty description="等待二维码" :image-size="60" />
          </div>
          <!-- 遮罩：防止误扫 -->
          <div v-if="status === 'loading'" class="qr-mask">
            <span class="mask-text">二维码加载中…</span>
          </div>
          <div v-else-if="status === 'scanned'" class="qr-mask">
            <span class="mask-text">已扫描，请在微信上确认</span>
          </div>
          <div v-else-if="status === 'expired'" class="qr-mask">
            <el-button type="primary" @click="loadQrcode">
              二维码已过期，点击刷新
            </el-button>
          </div>
          <div v-else-if="status === 'error'" class="qr-mask">
            <div class="error-box">
              <p>{{ errorMsg }}</p>
              <el-button type="primary" @click="loadQrcode">
                重试
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <el-alert
        v-if="status === 'waiting'"
        title="请使用微信扫描二维码登录"
        type="info"
        show-icon
        :closable="false"
        class="mt-4"
      />
      <el-alert
        v-else-if="status === 'scanned'"
        title="已扫描，请在微信上点击确认登录"
        type="warning"
        show-icon
        :closable="false"
        class="mt-4"
      />
      <el-alert
        v-else-if="status === 'success'"
        title="登录成功，正在跳转…"
        type="success"
        show-icon
        :closable="false"
        class="mt-4"
      />
      <p class="tip">登录态暂不限制时长，可点击右上角头像手动退出</p>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.login-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4a6f 50%, #3a7bd5 100%);


  .login-card {
    width: 400px;
    border-radius: 8px;

    .title {
      margin-bottom: 16px;
      text-align: center;

      h2 {
        margin: 0 0 8px;
        font-size: 20px;
      }

      .sub {
        margin: 0;
        font-size: 13px;
        color: var(--el-text-color-secondary);
      }
    }

    .qr-area {
      display: flex;
      justify-content: center;
    }

    .qr-box {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 220px;
      height: 220px;
      overflow: hidden;
      border: 1px dashed var(--el-border-color);
      border-radius: 4px;

      img {
        width: 200px;
        height: 200px;

        &.blurred {
          filter: blur(10px);
        }
      }

      .qr-placeholder {
        display: flex;
        justify-content: center;
        width: 100%;
      }

      .qr-mask {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 8px;
        background: rgb(255 255 255 / 88%);

        .mask-text {
          padding: 4px 10px;
          font-size: 14px;
          color: var(--el-text-color-regular);
          background: rgb(255 255 255 / 90%);
          border-radius: 4px;
        }

        .error-box {
          padding: 8px;
          text-align: center;

          p {
            margin-bottom: 12px;
            font-size: 13px;
            color: var(--el-color-danger);
          }
        }
      }
    }

    .tip {
      margin-top: 12px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
      text-align: center;
    }
  }
}
</style>
