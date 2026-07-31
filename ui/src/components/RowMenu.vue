<template>
  <span class="row-menu" ref="rootEl">
    <button class="btn row-menu-toggle" @click.stop="open = !open">
      <span class="material-symbols-outlined">more_vert</span>
    </button>
    <div v-if="open" class="row-menu-panel" @click="open = false">
      <slot />
    </div>
  </span>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'

const open = ref(false)
const rootEl = ref(null)

function onDocumentClick(e) {
  if (open.value && rootEl.value && !rootEl.value.contains(e.target)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>
