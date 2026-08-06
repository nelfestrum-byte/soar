<template>
  <div ref="container" class="code-editor" :style="{ height }" data-test="code-editor"></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { loadMonaco } from '../monaco-setup.js'

const props = defineProps({
  modelValue: { type: String, required: true },
  language: { type: String, default: 'plaintext' },
  readOnly: { type: Boolean, default: false },
  height: { type: String, default: '400px' },
})
const emit = defineEmits(['update:modelValue'])

const container = ref(null)
let editor = null

onMounted(async () => {
  const monaco = await loadMonaco()
  editor = monaco.editor.create(container.value, {
    value: props.modelValue,
    language: props.language,
    readOnly: props.readOnly,
    automaticLayout: true,
    minimap: { enabled: false },
    tabSize: 4,
    scrollBeyondLastLine: false,
  })
  editor.onDidChangeModelContent(() => emit('update:modelValue', editor.getValue()))
})

watch(() => props.modelValue, (val) => {
  if (editor && val !== editor.getValue()) editor.setValue(val)
})

watch(() => props.readOnly, (val) => {
  editor?.updateOptions({ readOnly: val })
})

onUnmounted(() => {
  editor?.dispose()
})
</script>
