<script lang="ts" setup>
import { useLayoutMode } from "@@/composables/useLayoutMode"

interface Props {
  collapse?: boolean
}

const { collapse = true } = defineProps<Props>()

const { isLeft, isTop } = useLayoutMode()
</script>

<template>
  <div class="layout-logo-container" :class="{ 'collapse': collapse, 'layout-mode-top': isTop }">
    <transition name="layout-logo-fade">
      <router-link v-if="collapse" key="collapse" to="/" class="logo-text">
        <span class="logo-mark">A</span>
      </router-link>
      <router-link v-else key="expand" to="/" class="logo-text">
        <span class="logo-mark">A</span>
        <span class="logo-title">AntiSWUST</span>
      </router-link>
    </transition>
  </div>
</template>

<style lang="scss" scoped>
.layout-logo-container {
  position: relative;
  width: 100%;
  height: var(--v3-header-height);
  display: flex;
  justify-content: center;
  overflow: hidden;
}

.logo-text {
  display: flex;
  gap: 8px;
  align-items: center;

  .logo-mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(135deg, #409eff, #2b4a6f);
    border-radius: 6px;
    flex-shrink: 0;
  }

  .logo-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--el-text-color-primary);
    white-space: nowrap;
  }
}

.layout-mode-top {
  height: var(--v3-navigationbar-height);
}
</style>
