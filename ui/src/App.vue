<template>
  <div id="app">
    <nav>
      <router-link to="/" class="brand">SOAR</router-link>
      <router-link to="/">Status</router-link>
      <router-link to="/workflows">Workflows</router-link>
      <router-link to="/jobs">Jobs</router-link>
      <router-link to="/actions">Actions</router-link>
      <router-link to="/connectors">Connectors</router-link>
      <router-link to="/generate">Generate</router-link>
      <router-link to="/settings">Settings</router-link>
    </nav>
    <main><router-view /></main>
  </div>
</template>

<style>
nav {
  background: #1a1a2e; padding: 0 20px; display: flex; align-items: center; gap: 4px;
}
nav a { color: #aaa; text-decoration: none; padding: 12px 16px; font-size: 14px; }
nav a:hover, nav a.router-link-active { color: #fff; }
nav .brand { color: #4fc3f7; font-weight: 700; font-size: 18px; margin-right: 16px; }
main { max-width: 1200px; margin: 20px auto; padding: 0 20px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
h2 { font-size: 16px; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; }
th { background: #fafafa; font-weight: 600; }
.btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.btn-primary { background: #4fc3f7; color: #000; }
.btn-danger { background: #ef5350; color: #fff; }
.btn-success { background: #66bb6a; color: #fff; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge-pending { background: #fff3e0; color: #e65100; }
.badge-running { background: #e3f2fd; color: #1565c0; }
.badge-completed { background: #e8f5e9; color: #2e7d32; }
.badge-failed { background: #ffebee; color: #c62828; }
.badge-cancelled { background: #f3e5f5; color: #7b1fa2; }
.badge-timeout { background: #fce4ec; color: #ad1457; }
pre { background: #1a1a2e; color: #a5d6a7; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 12px; max-height: 500px; overflow-y: auto; }
input, select { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
.loading { color: #999; font-style: italic; }
.error { color: #c62828; padding: 12px; background: #ffebee; border-radius: 4px; }
</style>
