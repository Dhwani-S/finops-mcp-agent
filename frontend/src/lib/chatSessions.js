export const STORAGE_KEY = 'finops_chat_sessions_v1'
export const THEME_STORAGE_KEY = 'finops_theme'

export function titleFromMessages(messages) {
  const first = messages?.find((m) => m.role === 'user')
  if (!first?.content?.trim()) return 'New conversation'
  const t = first.content.trim().replace(/\s+/g, ' ')
  return t.length > 56 ? `${t.slice(0, 54)}…` : t
}

function newId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export function createSession(overrides = {}) {
  const id = newId()
  return {
    id,
    title: 'New conversation',
    messages: [],
    updatedAt: Date.now(),
    ...overrides,
  }
}

export function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      if (Array.isArray(p.sessions) && p.sessions.length > 0 && p.activeSessionId) {
        const valid = p.sessions.filter((s) => s && s.id && Array.isArray(s.messages))
        if (valid.length) {
          const active = valid.some((s) => s.id === p.activeSessionId)
            ? p.activeSessionId
            : valid[0].id
          return { sessions: valid, activeSessionId: active }
        }
      }
    }
  } catch {
    /* ignore */
  }
  const s = createSession()
  return { sessions: [s], activeSessionId: s.id }
}

export function savePersisted(sessions, activeSessionId) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ sessions, activeSessionId, v: 1 }),
    )
  } catch {
    /* quota or private mode */
  }
}

export function formatSessionTime(ts) {
  const t = Number(ts)
  if (!Number.isFinite(t)) return ''
  const now = Date.now()
  if (now - t < 86_400_000) {
    return new Date(t).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  }
  return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
