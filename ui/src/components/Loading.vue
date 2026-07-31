<template>
  <div class="loading-spinner"><span class="spinner"></span> {{ label }}</div>
</template>

<script setup>
defineProps({ label: { type: String, default: 'Loading…' } })
</script>

<style scoped>
.loading-spinner {
  display: flex; align-items: center; gap: var(--space-2);
  color: var(--color-text-faint); font-style: italic;
}
.spinner {
  display: inline-block; width: 12px; height: 12px;
  border: 2px solid var(--color-border); border-top-color: var(--color-accent);
  border-radius: 50%; animation: spin .6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
