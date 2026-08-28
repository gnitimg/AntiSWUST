<script setup lang="ts">
import { ref } from 'vue'
import request from '@/api/request'

interface WxDebugResp {
  ok: boolean
  error?: string
  status_code?: number
  url?: string
  html_length?: number
  js_qrcode_img_src?: string | null
  uuid_extracted?: string | null
  has_qrcode_div?: boolean
  img_tags?: string[]
  html_head?: string
}

interface WxPollDebugResp {
  ok: boolean
  error?: string
  status_code?: number
  response_text?: string
  wx_errcode?: string | null
  wx_code?: string | null
}

const wxDebug = ref<WxDebugResp | null>(null)
const wxPollDebug = ref<WxPollDebugResp | null>(null)
const uuidInput = ref('')
const loading = ref(false)

async function runWxDebug() {
  loading.value = true
  try {
    wxDebug.value = await request.get<unknown, WxDebugResp>('/login/wx-debug')
    if (wxDebug.value?.uuid_extracted) {
      uuidInput.value = wxDebug.value.uuid_extracted
    }
  } catch (e: any) {
    wxDebug.value = { ok: false, error: e?.message || '请求失败' }
  } finally {
    loading.value = false
  }
}

async function runPollDebug() {
  if (!uuidInput.value) return
  loading.value = true
  try {
    wxPollDebug.value = await request.get<unknown, WxPollDebugResp>('/login/wx-poll-debug', {
      params: { uuid: uuidInput.value },
    })
  } catch (e: any) {
    wxPollDebug.value = { ok: false, error: e?.message || '请求失败' }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <a-layout style="min-height: 100vh">
    <a-layout-header style="color: #fff; font-size: 18px; padding: 0 24px">
      AntiSWUST 微信登录诊断
    </a-layout-header>
    <a-layout-content style="padding: 24px">
      <a-card title="1. 二维码页解析（验证选择器是否过时）" :bordered="false" style="margin-bottom: 16px">
        <a-button type="primary" :loading="loading" @click="runWxDebug">请求微信二维码页</a-button>
        <pre v-if="wxDebug" style="margin-top: 16px; background: #f5f5f5; padding: 12px; overflow: auto">{{ JSON.stringify(wxDebug, null, 2) }}</pre>
      </a-card>

      <a-card title="2. 长轮询响应（验证 wx_errcode / wx_code 格式）" :bordered="false">
        <a-space>
          <a-input v-model:value="uuidInput" placeholder="输入 uuid（上方解析会自动填入）" style="width: 320px" />
          <a-button type="primary" :loading="loading" @click="runPollDebug">轮询一次</a-button>
        </a-space>
        <a-alert
          v-if="wxPollDebug?.ok"
          type="info"
          :message="`errcode=${wxPollDebug.wx_errcode}  wx_code=${wxPollDebug.wx_code}`"
          style="margin-top: 12px"
        />
        <pre v-if="wxPollDebug" style="margin-top: 12px; background: #f5f5f5; padding: 12px; overflow: auto">{{ JSON.stringify(wxPollDebug, null, 2) }}</pre>
      </a-card>

      <a-alert
        type="warning"
        message="说明：此页面直接请求微信 open.weixin.qq.com 并返回原始解析结果。若 js_qrcode_img_src 为 null，说明选择器需更新；若 wx_errcode 为 null，说明轮询响应格式已变。"
        show-icon
        style="margin-top: 16px"
      />
    </a-layout-content>
  </a-layout>
</template>
