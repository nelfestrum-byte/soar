import './styles/tokens.css'
import './styles/fonts.css'
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { setUnauthorizedHandler } from './api.js'
import { auth, checkAuth, resetAuth } from './store/auth.js'
import { routeAllowed } from './router-guard.js'
import { notify } from './store/toast.js'

const routes = [
  { path: '/', component: () => import('./views/Status.vue') },
  { path: '/workflows', component: () => import('./views/Workflows.vue') },
  { path: '/jobs', component: () => import('./views/Jobs.vue') },
  { path: '/jobs/:id', component: () => import('./views/JobDetail.vue') },
  { path: '/actions', component: () => import('./views/Actions.vue') },
  { path: '/connectors', component: () => import('./views/Connectors.vue') },
  { path: '/tools', component: () => import('./views/Tools.vue') },
  { path: '/prompts', component: () => import('./views/Prompts.vue') },
  { path: '/generate', component: () => import('./views/Generate.vue'), meta: { cap: 'connector.manage' } },
  { path: '/settings', component: () => import('./views/Settings.vue'), meta: { cap: 'transfer' } },
  { path: '/api-keys', component: () => import('./views/ApiKeys.vue'), meta: { cap: 'auth.admin' } },
  { path: '/users', component: () => import('./views/Users.vue'), meta: { cap: 'auth.admin' } },
  { path: '/audit-log', component: () => import('./views/AuditLog.vue'), meta: { cap: 'audit.read' } },
  { path: '/login', component: () => import('./views/Login.vue') },
  { path: '/logs/:id', component: () => import('./views/Logs.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (to.path === '/login') return true
  if (!auth.checked) await checkAuth()
  if (!auth.authenticated) return { path: '/login', query: { redirect: to.fullPath } }
  if (!routeAllowed(to, auth.role)) {
    notify.error(`Раздел недоступен роли "${auth.role}"`)
    return { path: '/' }
  }
  return true
})

setUnauthorizedHandler(() => {
  resetAuth()
  router.push('/login')
})

createApp(App).use(router).mount('#app')
