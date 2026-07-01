import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'

const routes = [
  { path: '/', component: () => import('./views/Status.vue') },
  { path: '/workflows', component: () => import('./views/Workflows.vue') },
  { path: '/jobs', component: () => import('./views/Jobs.vue') },
  { path: '/actions', component: () => import('./views/Actions.vue') },
  { path: '/connectors', component: () => import('./views/Connectors.vue') },
  { path: '/settings', component: () => import('./views/Settings.vue') },
  { path: '/logs/:id', component: () => import('./views/Logs.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

createApp(App).use(router).mount('#app')
