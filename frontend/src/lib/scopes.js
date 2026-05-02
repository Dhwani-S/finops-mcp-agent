/**
 * Scope storage utilities.
 * Scopes are persisted in localStorage and attached to chat messages
 * so the LLM knows the user's intent context (cloud, project, env, owner, etc.)
 */

const SCOPES_KEY = 'finops_scopes'
const ACTIVE_SCOPE_KEY = 'finops_active_scope'

export const CLOUD_OPTIONS = ['AWS', 'Azure', 'GCP']
export const ENVIRONMENT_OPTIONS = ['Production', 'Staging', 'Development', 'Sandbox']

/**
 * @typedef {Object} Scope
 * @property {string} id
 * @property {string} name
 * @property {string[]} clouds - e.g. ['AWS', 'Azure']
 * @property {string[]} projects - project names
 * @property {string[]} environments - e.g. ['Production']
 * @property {string[]} owners - owner names
 * @property {string} freetext - additional freeform scope text
 * @property {number} createdAt
 */

export function loadScopes() {
  try {
    const raw = localStorage.getItem(SCOPES_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export function saveScopes(scopes) {
  try {
    localStorage.setItem(SCOPES_KEY, JSON.stringify(scopes))
  } catch { /* ignore */ }
}

export function getActiveScope() {
  try {
    return localStorage.getItem(ACTIVE_SCOPE_KEY) || null
  } catch {
    return null
  }
}

export function setActiveScope(scopeId) {
  try {
    if (scopeId) {
      localStorage.setItem(ACTIVE_SCOPE_KEY, scopeId)
    } else {
      localStorage.removeItem(ACTIVE_SCOPE_KEY)
    }
  } catch { /* ignore */ }
}

export function createScope(data) {
  return {
    id: crypto.randomUUID(),
    name: data.name || 'Untitled Scope',
    clouds: data.clouds || [],
    projects: data.projects || [],
    environments: data.environments || [],
    owners: data.owners || [],
    coreIds: data.coreIds || [],
    freetext: data.freetext || '',
    createdAt: Date.now(),
  }
}

/**
 * Build a context string from a scope to prepend to user messages.
 */
export function scopeToContext(scope) {
  if (!scope) return ''
  const parts = []
  if (scope.clouds.length) parts.push(`Cloud: ${scope.clouds.join(', ')}`)
  if (scope.projects.length) parts.push(`Projects: ${scope.projects.join(', ')}`)
  if (scope.environments.length) parts.push(`Environments: ${scope.environments.join(', ')}`)
  if (scope.owners.length) parts.push(`Owners: ${scope.owners.join(', ')}`)
  if (scope.coreIds?.length) parts.push(`Core IDs: ${scope.coreIds.join(', ')}`)
  if (scope.freetext) parts.push(scope.freetext)
  if (parts.length === 0) return ''
  return `[Scope: ${scope.name}] ${parts.join(' | ')}`
}
