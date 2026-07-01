<template>
  <div>
    <h1>Settings</h1>

    <div class="card">
      <h2>Export</h2>
      <p>Download all entities (connectors, actions, workflows) and configs as a zip archive.</p>
      <button class="btn btn-primary" @click="doExport" :disabled="exporting">
        {{ exporting ? 'Exporting...' : 'Download Archive' }}
      </button>
      <span v-if="exportError" class="error">{{ exportError }}</span>
    </div>

    <div class="card">
      <h2>Import</h2>
      <p>Upload a previously exported archive to restore entities.</p>
      <input type="file" ref="fileInput" accept=".zip" @change="handleFile" style="display:none" />
      <button class="btn btn-primary" @click="$refs.fileInput.click()" :disabled="importing">
        {{ importing ? 'Importing...' : 'Select Archive' }}
      </button>

      <div v-if="conflicts.length" class="conflicts">
        <h3>Conflicts Found</h3>
        <ul>
          <li v-for="c in conflicts" :key="c.type + c.name">
            {{ c.type }}: <strong>{{ c.name }}</strong> (already exists)
          </li>
        </ul>
        <button class="btn btn-danger" @click="doImport(true)" :disabled="importing">
          Overwrite All
        </button>
        <button class="btn" @click="conflicts = []">Cancel</button>
      </div>

      <div v-if="importResult" class="result">
        <h3>Import Complete</h3>
        <p>Connectors: {{ importResult.imported.connectors.length }}</p>
        <p>Actions: {{ importResult.imported.actions.length }}</p>
        <p>Workflows: {{ importResult.imported.workflows.length }}</p>
      </div>

      <span v-if="importError" class="error">{{ importError }}</span>
    </div>
  </div>
</template>

<script>
import { api } from '../api'

export default {
  data() {
    return {
      exporting: false,
      exportError: '',
      importing: false,
      importError: '',
      importFile: null,
      conflicts: [],
      importResult: null,
    }
  },
  methods: {
    async doExport() {
      this.exporting = true
      this.exportError = ''
      try {
        const blob = await api.exportEntities()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `soar-export-${new Date().toISOString().slice(0,10)}.zip`
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) {
        this.exportError = e.message
      } finally {
        this.exporting = false
      }
    },
    handleFile(e) {
      this.importFile = e.target.files[0]
      if (this.importFile) {
        this.doImport(false)
      }
    },
    async doImport(force) {
      if (!this.importFile) return
      this.importing = true
      this.importError = ''
      this.importResult = null
      try {
        const result = await api.importEntities(this.importFile, force)
        if (result.status === 'conflicts') {
          this.conflicts = result.conflicts
        } else {
          this.importResult = result
          this.conflicts = []
          this.importFile = null
          this.$refs.fileInput.value = ''
        }
      } catch (e) {
        this.importError = e.message
      } finally {
        this.importing = false
      }
    },
  },
}
</script>

<style scoped>
.conflicts { margin-top: 12px; padding: 12px; background: #fff3e0; border-radius: 4px; }
.conflicts ul { margin: 8px 0; padding-left: 20px; }
.result { margin-top: 12px; padding: 12px; background: #e8f5e9; border-radius: 4px; }
</style>
