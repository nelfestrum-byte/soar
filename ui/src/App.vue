<template>
  <div id="app">
    <nav v-if="route.path !== '/login'">
      <router-link to="/" class="brand">SOAR</router-link>
      <router-link to="/">Status</router-link>
      <router-link to="/workflows">Workflows</router-link>
      <router-link to="/jobs">Jobs</router-link>
      <router-link to="/actions">Actions</router-link>
      <router-link to="/connectors">Connectors</router-link>
      <div class="nav-more" ref="navMoreEl">
        <button class="btn nav-more-toggle" data-test="nav-more-toggle" @click.stop="toggleMore">
          <span class="material-symbols-outlined">settings</span> More
        </button>
        <div class="nav-more-panel" data-test="nav-more-panel" v-show="moreOpen">
          <router-link to="/tools">Tools</router-link>
          <router-link to="/prompts">Prompts</router-link>
          <router-link v-if="can(auth.role, 'connector.manage')" to="/generate">Generate</router-link>
          <router-link v-if="can(auth.role, 'transfer')" to="/settings">Settings</router-link>
          <router-link v-if="can(auth.role, 'auth.admin')" to="/users">Users</router-link>
          <router-link v-if="can(auth.role, 'auth.admin')" to="/api-keys">API Keys</router-link>
          <router-link v-if="can(auth.role, 'audit.read')" to="/audit-log">Audit Log</router-link>
        </div>
      </div>
      <div style="flex:1;"></div>
      <span v-if="auth.checked && auth.authenticated" class="user-badge">
        {{ auth.username }} <span class="role">({{ auth.role }})</span>
      </span>
      <button v-if="auth.checked && auth.authenticated && !auth.noAuthMode"
              class="btn btn-logout" @click="doLogout">Logout</button>
    </nav>
    <main><router-view /></main>
    <Toast />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, resetAuth } from './store/auth.js'
import { api } from './api.js'
import { can } from './permissions.js'
import Toast from './components/Toast.vue'

const route = useRoute()
const router = useRouter()

const NAV_MORE_KEY = 'soar.nav.moreOpen'
const moreOpen = ref(localStorage.getItem(NAV_MORE_KEY) === '1')
const navMoreEl = ref(null)

function toggleMore() {
  moreOpen.value = !moreOpen.value
  localStorage.setItem(NAV_MORE_KEY, moreOpen.value ? '1' : '0')
}

function onDocumentClick(e) {
  if (moreOpen.value && navMoreEl.value && !navMoreEl.value.contains(e.target)) {
    moreOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

async function doLogout() {
  await api.logout()
  resetAuth()
  router.push('/login')
}
</script>

<style>
#app {
  font-family: var(--font-sans); background: var(--color-surface); color: var(--color-text);
  min-height: 100vh;
}
nav {
  background: var(--color-surface-dark); padding: 0 20px; display: flex; align-items: center; gap: var(--space-1);
}
nav a { color: var(--color-text-faint); text-decoration: none; padding: 12px 16px; font-size: 14px; }
nav a:hover, nav a.router-link-active { color: var(--color-surface); }
nav .brand { color: var(--color-accent); font-weight: 700; font-size: 18px; margin-right: 16px; }
nav .user-badge { color: var(--color-border); font-size: 13px; margin-right: var(--space-2); }
nav .user-badge .role { color: var(--color-accent); }
.btn-logout { background: var(--color-text); color: var(--color-surface); }
.nav-more { position: relative; }
.nav-more-toggle { background: none; color: var(--color-text-faint); }
.nav-more-toggle:hover { color: var(--color-surface); }
.nav-more-panel {
  position: absolute; top: 100%; left: 0; z-index: 10; min-width: 160px;
  background: var(--color-surface-dark); border: 1px solid var(--color-text-muted);
  border-radius: var(--radius); display: flex; flex-direction: column;
  padding: var(--space-1) 0;
}
.nav-more-panel a { padding: var(--space-2) var(--space-3); }
.row-menu { position: relative; display: inline-block; }
.row-menu-toggle { background: none; color: var(--color-text-muted); }
.row-menu-toggle:hover { color: var(--color-text); }
.row-menu-panel {
  position: absolute; top: 100%; right: 0; z-index: 10; min-width: 140px;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius); box-shadow: 0 2px 8px rgba(0,0,0,.15);
  display: flex; flex-direction: column; padding: var(--space-1) 0;
}
.row-menu-panel .btn, .row-menu-panel a {
  background: none; color: var(--color-text); text-decoration: none;
  text-align: left; padding: var(--space-2) var(--space-3); border-radius: 0; font-size: 12px;
}
.row-menu-panel .btn:hover, .row-menu-panel a:hover { background: var(--color-surface-alt); }
.row-menu-item-danger, .row-menu-item-danger:hover { color: var(--color-danger); }
.editor-toolbar {
  position: sticky; top: 0; background: var(--color-surface); z-index: 1;
  display: flex; gap: var(--space-2); padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border-subtle); margin-bottom: var(--space-2);
}
main { max-width: 1200px; margin: 20px auto; padding: 0 20px; }
.card { background: var(--color-surface); border-radius: var(--radius-lg); padding: var(--space-4); margin-bottom: var(--space-3); box-shadow: 0 1px 3px rgba(0,0,0,.1); }
h2 {
  font-size: var(--text-h3); font-weight: var(--text-h3-weight); line-height: var(--text-h3-line);
  margin-bottom: var(--space-3);
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border-subtle); }
th { background: var(--color-surface-alt); font-weight: 600; }
.btn { padding: 6px 12px; border: none; border-radius: var(--radius); cursor: pointer; font-size: 12px; }
.btn-primary { background: var(--color-accent); color: var(--color-accent-fg); }
.btn-danger { background: var(--color-danger); color: var(--color-surface); }
.btn-success { background: var(--color-success); color: var(--color-surface); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.badge { padding: 2px 8px; border-radius: var(--radius-xl); font-size: 11px; font-weight: 600; }
.badge-pending { background: var(--status-pending-bg); color: var(--status-pending-fg); }
.badge-running { background: var(--status-running-bg); color: var(--status-running-fg); }
.badge-completed { background: var(--status-completed-bg); color: var(--status-completed-fg); }
.badge-failed { background: var(--status-failed-bg); color: var(--status-failed-fg); }
.badge-cancelled { background: var(--status-cancelled-bg); color: var(--status-cancelled-fg); }
.badge-timeout { background: var(--status-timeout-bg); color: var(--status-timeout-fg); }
pre { background: var(--color-surface-dark); color: var(--color-text-on-dark); font-family: var(--font-mono); padding: var(--space-3); border-radius: var(--radius); overflow-x: auto; font-size: var(--text-code); overflow-y: auto; max-height: 500px; }
input, select { padding: 6px 10px; border: 1px solid var(--color-border); border-radius: var(--radius); font-size: 13px; }
.empty { color: var(--color-text-faint); font-style: italic; }
.error { color: var(--color-result-fail); padding: var(--space-3); background: var(--status-failed-bg); border-radius: var(--radius); }
</style>
