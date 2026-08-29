<script lang="ts" setup>
import { useTheme, type ThemeName } from "@@/composables/useTheme"
import { Settings } from "@/layouts/components"

defineOptions({ name: "ThemeSettings" })

const { themeList, activeThemeName, setTheme } = useTheme()

/** 应用主题（借助点击位置做视图过渡动画） */
function onPickTheme(e: MouseEvent, name: ThemeName) {
  if (activeThemeName.value === name) return
  setTheme(e, name)
}
</script>

<template>
  <div class="app-container">
    <el-card shadow="never" class="mb-3">
      <template #header>
        <div class="card-header">
          <span class="title">主题外观</span>
        </div>
      </template>
      <div class="theme-list">
        <div
          v-for="theme in themeList"
          :key="theme.name"
          class="theme-item"
          :class="{ active: activeThemeName === theme.name }"
          @click="onPickTheme($event, theme.name)"
        >
          <div class="theme-preview" :class="`preview-${theme.name}`" />
          <span class="theme-title">{{ theme.title }}</span>
          <el-icon v-if="activeThemeName === theme.name" class="theme-check">
            <Check />
          </el-icon>
        </div>
      </div>
      <el-alert
        title="主题即时生效并自动保存；暗色系列会同时影响侧边栏、导航栏与内容区配色"
        type="info"
        show-icon
        :closable="false"
        class="mt-3"
      />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="title">布局与功能</span>
        </div>
      </template>
      <Settings />
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .title {
    font-size: 16px;
    font-weight: 600;
  }
}

.theme-list {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.theme-item {
  position: relative;
  width: 140px;
  padding: 12px;
  text-align: center;
  cursor: pointer;
  border: 2px solid var(--el-border-color);
  border-radius: 8px;
  transition: border-color 0.2s;

  &:hover {
    border-color: var(--el-color-primary-light-5);
  }

  &.active {
    border-color: var(--el-color-primary);

    .theme-title {
      color: var(--el-color-primary);
    }
  }

  .theme-preview {
    height: 64px;
    border-radius: 4px;
    margin-bottom: 8px;
    border: 1px solid var(--el-border-color-lighter);

    &.preview-normal {
      background: linear-gradient(135deg, #f5f7fa 60%, #409eff 60%);
    }

    &.preview-dark {
      background: linear-gradient(135deg, #141414 60%, #409eff 60%);
    }

    &.preview-dark-blue {
      background: linear-gradient(135deg, #0a2a4a 60%, #409eff 60%);
    }
  }

  .theme-title {
    font-size: 14px;
  }

  .theme-check {
    position: absolute;
    top: 6px;
    right: 6px;
    color: var(--el-color-primary);
  }
}
</style>
