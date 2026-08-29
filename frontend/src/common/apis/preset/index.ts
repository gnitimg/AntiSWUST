import { request } from "@/http/axios"
import type { CourseCategoryValue } from "@/common/apis/course/type"

export interface PresetEntry {
  id: string
  category: CourseCategoryValue
  name: string
  teacher: string
  class_name: string
  campus: string
  day_of_week: number | null
  node: number | null
  priority: number
  enabled: boolean
}

export interface PresetResult {
  preset_id: string
  name: string
  category: CourseCategoryValue
  status: "pending" | "unmatched" | "submitted" | "success" | "skipped" | "failed"
  message: string
  matched: string
  attempts: number
}

export interface PresetRun {
  id: string
  status: "waiting" | "running" | "finished" | "stopped" | "error"
  begin_at: number | null
  retry: boolean
  interval: number
  stop_same_category: boolean
  created_at: number
  finished_at: number | null
  error: string
  cycles: number
  results: Record<string, PresetResult>
}

export function listPresetsApi() {
  return request<{ items: PresetEntry[] }>({ url: "/preset", method: "get" })
}

export function createPresetApi(entry: Omit<PresetEntry, "id" | "priority"> & { priority?: number }) {
  return request<{ entry: PresetEntry }>({ url: "/preset", method: "post", data: entry })
}

export function updatePresetApi(id: string, entry: Omit<PresetEntry, "id" | "priority"> & { priority?: number }) {
  return request<{ ok: boolean }>({ url: `/preset/${id}`, method: "put", data: entry })
}

export function deletePresetApi(id: string) {
  return request<{ ok: boolean }>({ url: `/preset/${id}`, method: "delete" })
}

export function importPresetsApi(content: string, category: CourseCategoryValue) {
  return request<{ imported: number; items: PresetEntry[] }>({
    url: "/preset/import",
    method: "post",
    data: { content, category }
  })
}

export function startPresetRunApi(data: {
  start_at?: number
  retry: boolean
  interval: number
  stop_same_category: boolean
}) {
  return request<{ run: PresetRun }>({ url: "/preset/run/start", method: "post", data })
}

export function stopPresetRunApi() {
  return request<{ ok: boolean }>({ url: "/preset/run/stop", method: "post" })
}

export function getPresetRunApi() {
  return request<{ run: PresetRun | null }>({ url: "/preset/run", method: "get" })
}
