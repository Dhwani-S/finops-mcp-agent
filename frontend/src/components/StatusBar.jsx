import './StatusBar.css'

function formatUpdated(d) {
  if (!d) return null
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(d)
  } catch {
    return null
  }
}

export default function StatusBar({ status, statusUpdatedAt, onClear, onExport, hasMessages }) {
  const updatedStr = formatUpdated(statusUpdatedAt)

  if (!status) {
    return (
      <div className="status-bar">
        <div className="status-cluster">
          <span className="status-pulse" aria-hidden="true" />
          <span className="status-label">Connecting…</span>
        </div>
        <div className="status-bar-actions">
          {hasMessages && (
            <button type="button" className="btn-clear" onClick={onExport} title="Copy conversation to clipboard">
              Copy chat
            </button>
          )}
          <button type="button" className="btn-clear" onClick={onClear} title="Clear conversation">
            Clear chat
          </button>
        </div>
      </div>
    )
  }

  const servers = Object.entries(status.servers)
  const allConnected = servers.length > 0 && servers.every(([, connected]) => connected)
  const anyConnected = servers.some(([, connected]) => connected)

  return (
    <div className="status-bar">
      <div className="status-bar-inner">
        <div
          className={`status-live ${allConnected ? 'is-ok' : anyConnected ? 'is-warn' : 'is-warn'}`}
          title={allConnected ? 'All cost data services are reachable' : 'Some data sources may be unavailable'}
        >
          <span className="status-live-dot" aria-hidden="true" />
          {allConnected ? 'All systems online' : anyConnected ? 'Partial connectivity' : 'Offline'}
        </div>
        {updatedStr && (
          <span className="status-updated" title="When connection status was last checked">
            Updated {updatedStr}
          </span>
        )}
      </div>
      <div className="status-bar-actions">
        {hasMessages && (
          <button type="button" className="btn-clear" onClick={onExport} title="Copy conversation to clipboard">
            Copy chat
          </button>
        )}
        <button type="button" className="btn-clear" onClick={onClear} title="Clear conversation">
          Clear chat
        </button>
      </div>
    </div>
  )
}
