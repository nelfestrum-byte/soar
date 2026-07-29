// Non-reactive identity holder. api.js needs the current role to explain a 403,
// but store/auth.js already imports api.js — keeping the value here avoids the
// import cycle. store/auth.js is still the reactive mirror the views read.

let role = ''

export function setSessionRole(value) {
  role = value || ''
}

export function getSessionRole() {
  return role
}
