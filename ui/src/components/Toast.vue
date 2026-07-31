<template>
  <div class="toast-stack">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="'toast-' + t.kind">
      <span class="toast-msg">{{ t.message }}</span>
      <button class="toast-close" @click="dismiss(t.id)" title="Закрыть">&times;</button>
    </div>
  </div>
</template>

<script setup>
import { toasts, dismiss } from '../store/toast.js'
</script>

<style scoped>
.toast-stack {
  position: fixed; top: 16px; right: 16px; z-index: 1000;
  display: flex; flex-direction: column; gap: 8px; max-width: 420px;
}
.toast {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 10px 12px; border-radius: 6px; font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,.2);
}
.toast-msg { flex: 1; word-break: break-word; }
.toast-error { background: var(--status-failed-bg); color: var(--color-result-fail); border-left: 3px solid var(--color-result-fail); }
.toast-success { background: var(--status-completed-bg); color: var(--color-result-ok); border-left: 3px solid var(--color-result-ok); }
.toast-info { background: var(--status-running-bg); color: var(--status-running-fg); border-left: 3px solid var(--status-running-fg); }
.toast-close {
  background: none; border: none; cursor: pointer;
  font-size: 16px; line-height: 1; color: inherit; opacity: .6; padding: 0;
}
.toast-close:hover { opacity: 1; }
</style>
