// Base path per entity, shared by HistoryPanel and api.js. The four entities
// do NOT share a shape: actions have no /code segment
// (orchestrator/api/actions.py:116), connectors have both /code and /config.
export const HISTORY_PATHS = {
  workflow: (name) => `/workflows/${name}/code`,
  action: (name) => `/actions/${name}`,
  connector_code: (name) => `/connectors/${name}/code`,
  connector_config: (name) => `/connectors/${name}/config`,
}
