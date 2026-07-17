import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { setUnauthorizedHandler } from './api.js'
import { auth, checkAuth, resetAuth } from './store/auth.js'

const routes = [
  { path: '/', component: () => import('./views/Status.vue') },
  { path: '/workflows', component: () => import('./views/Workflows.vue') },
  { path: '/jobs', component: () => import('./views/Jobs.vue') },
  { path: '/actions', component: () => import('./views/Actions.vue') },
  { path: '/connectors', component: () => import('./views/Connectors.vue') },
  { path: '/tools', component: () => import('./views/Tools.vue') },
  { path: '/generate', component: () => import('./views/Generate.vue') },
  { path: '/settings', component: () => import('./views/Settings.vue') },
  { path: '/api-keys', component: () => import('./views/ApiKeys.vue') },
  { path: '/login', component: () => import('./views/Login.vue') },
  { path: '/logs/:id', component: () => import('./views/Logs.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (to.path === '/login') return true
  if (!auth.checked) await checkAuth()
  if (!auth.authenticated) return { path: '/login', query: { redirect: to.fullPath } }
  return true
})

setUnauthorizedHandler(() => {
  resetAuth()
  router.push('/login')
})

createApp(App).use(router).mount('#app')
