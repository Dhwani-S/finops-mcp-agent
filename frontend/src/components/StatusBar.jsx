import './StatusBar.css'

function ActionIcon({ name }) {
  const common = {
    width: 14,
    height: 14,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  }

  if (name === 'copy') {
    return (
      <svg {...common}>
        <rect x="9" y="9" width="13" height="13" rx="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
    )
  }

  return (
    <svg {...common}>
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  )
}

function TokenIcon() {
  return (
    <svg
      width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v12" />
      <path d="M8 10h8" />
      <path d="M8 14h8" />
    </svg>
  )
}

function formatTokens(n) {
  if (n == null) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

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

export default function StatusBar({ status, statusUpdatedAt, onClear, onExport, hasMessages, tokenUsage }) {
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
              <ActionIcon name="copy" />
              Copy chat
            </button>
          )}
          <button type="button" className="btn-clear" onClick={onClear} title="Clear conversation">
            <ActionIcon name="clear" />
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
        {tokenUsage && tokenUsage.total_tokens > 0 && (
          <span className="token-badge" title={`Prompt: ${formatTokens(tokenUsage.total_prompt_tokens)} | Response: ${formatTokens(tokenUsage.total_response_tokens)} | Tool calls: ${tokenUsage.total_tool_calls || 0}`}>
            <TokenIcon />
            {formatTokens(tokenUsage.total_tokens)}
          </span>
        )}
        {hasMessages && (
          <button type="button" className="btn-clear" onClick={onExport} title="Copy conversation to clipboard">
            <ActionIcon name="copy" />
            Copy chat
          </button>
        )}
        <button type="button" className="btn-clear" onClick={onClear} title="Clear conversation">
          <ActionIcon name="clear" />
          Clear chat
        </button>
      </div>
    </div>
  )
}
