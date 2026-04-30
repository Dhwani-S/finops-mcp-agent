import './LeftRail.css'
import ThemeToggle from './ThemeToggle'
import { CONNECTED_SERVICE_LABELS, serviceLabelForServerKey } from '../lib/finopsUi'
import { formatSessionTime } from '../lib/chatSessions'

const SERVER_ORDER = ['bq', 'sql', 'analytics', 'file']

export default function LeftRail({
  status,
  theme,
  onThemeChange,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
}) {
  const byKey = status?.servers ? { ...status.servers } : {}
  const ordered = SERVER_ORDER.filter((k) => k in byKey).map((k) => [k, byKey[k]])
  const extras = Object.entries(byKey).filter(([k]) => !SERVER_ORDER.includes(k))
  const rows = [...ordered, ...extras]
  const allOnline = rows.length > 0 && rows.every(([, ok]) => ok)
  const anyOnline = rows.some(([, ok]) => ok)

  const statusLabel = !status
    ? 'Connecting…'
    : allOnline
      ? 'All systems online'
      : anyOnline
        ? 'Partial connectivity'
        : 'Services unavailable'

  return (
    <aside className="left-rail" aria-label="Conversations and workspace">
      <div className="left-rail-top">
        <div className="left-rail-brand">
          <div className="left-rail-logo" aria-hidden="true">
            <span className="left-rail-logo-core" />
          </div>
          <div className="left-rail-brand-text">
            <div className="left-rail-title">FinOps Agent</div>
            <div className="left-rail-sub">Cost intelligence</div>
          </div>
        </div>
        <ThemeToggle theme={theme} onChange={onThemeChange} />
      </div>

      <div className="left-rail-connection">
        <details className="left-rail-details">
          <summary className="left-rail-details-summary">
            <span className={`left-rail-status-pill ${allOnline ? 'is-ok' : anyOnline ? 'is-warn' : 'is-warn'}`}>
              <span className="left-rail-status-dot" aria-hidden="true" />
              {statusLabel}
            </span>
            <span className="left-rail-details-hint">Data sources</span>
          </summary>
          {!status && <p className="left-rail-muted">Checking connection…</p>}
          {status && rows.length > 0 && (
            <ul className="left-rail-service-list">
              {rows.map(([key, connected]) => (
                <li key={key} className={`left-rail-service ${connected ? 'is-up' : 'is-down'}`}>
                  <span className="left-rail-service-dot" aria-hidden="true" />
                  <span>{CONNECTED_SERVICE_LABELS[key] ?? serviceLabelForServerKey(key)}</span>
                  <span className="left-rail-service-state">{connected ? 'Ready' : 'Down'}</span>
                </li>
              ))}
            </ul>
          )}
        </details>
      </div>

      <div className="left-rail-history">
        <div className="left-rail-history-head">
          <h2 className="left-rail-section-title">Conversations</h2>
          <p className="left-rail-history-help">
            Saved on this device. Open a row to continue or review. New questions start with a fresh assistant context when you switch chats.
          </p>
          <button type="button" className="left-rail-new-btn" onClick={onNewSession}>
            New conversation
          </button>
        </div>
        <nav className="left-rail-session-scroll" aria-label="Chat history">
          <ul className="left-rail-session-list">
            {sessions.map((s) => (
              <li key={s.id}>
                <div
                  className={`left-rail-session ${s.id === activeSessionId ? 'is-active' : ''}`}
                  role="group"
                >
                  <button
                    type="button"
                    className="left-rail-session-main"
                    onClick={() => onSelectSession(s.id)}
                    aria-current={s.id === activeSessionId ? 'true' : undefined}
                  >
                    <span className="left-rail-session-title">{s.title || 'New conversation'}</span>
                    <span className="left-rail-session-meta">
                      {formatSessionTime(s.updatedAt)}
                      {s.messages?.length ? ` · ${s.messages.length} msgs` : ''}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="left-rail-session-delete"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteSession(s.id)
                    }}
                    title="Delete conversation"
                    aria-label={`Delete ${s.title || 'conversation'}`}
                  >
                    ×
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </aside>
  )
}
