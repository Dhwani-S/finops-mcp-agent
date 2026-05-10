import { useState } from 'react'
import './ChatTrace.css'

function formatTokens(n) {
  if (n == null || n === 0) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatDuration(ms) {
  if (!ms) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function formatCost(promptTokens, responseTokens, cachedTokens) {
  // Gemini 2.5 Pro pricing (per 1M tokens)
  const PROMPT_RATE = 1.25   // $1.25/1M input (<=200K)
  const RESPONSE_RATE = 10.0 // $10/1M output
  const CACHED_RATE = 0.3125 // $0.3125/1M cached (75% off)

  const uncachedPrompt = promptTokens - cachedTokens
  const cost =
    (uncachedPrompt / 1_000_000) * PROMPT_RATE +
    (cachedTokens / 1_000_000) * CACHED_RATE +
    (responseTokens / 1_000_000) * RESPONSE_RATE

  const costWithoutCache =
    (promptTokens / 1_000_000) * PROMPT_RATE +
    (responseTokens / 1_000_000) * RESPONSE_RATE

  return { cost, costWithoutCache, saved: costWithoutCache - cost }
}

function TraceIcon() {
  return (
    <svg
      width={13} height={13} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M12 20V10" />
      <path d="M18 20V4" />
      <path d="M6 20v-4" />
    </svg>
  )
}

function ChevronIcon({ open }) {
  return (
    <svg
      width={12} height={12} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"
      className={`trace-chevron ${open ? 'open' : ''}`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

function TokenBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="trace-bar-row">
      <span className="trace-bar-label">{label}</span>
      <div className="trace-bar-track">
        <div className="trace-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="trace-bar-value">{formatTokens(value)}</span>
    </div>
  )
}

export default function ChatTrace({ tokenUsage }) {
  const [open, setOpen] = useState(false)

  if (!tokenUsage || !tokenUsage.tracking_enabled) return null

  const {
    total_prompt_tokens: prompt = 0,
    total_response_tokens: response = 0,
    total_cached_tokens: cached = 0,
    total_tokens: total = 0,
    total_tool_calls: toolCalls = 0,
    turns = 0,
    per_turn = [],
  } = tokenUsage

  const { cost, saved } = formatCost(prompt, response, cached)
  const maxTurnTokens = Math.max(...per_turn.map((t) => t.prompt_tokens + t.response_tokens), 1)

  return (
    <div className="chat-trace">
      <button
        type="button"
        className={`trace-toggle ${open ? 'active' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        <TraceIcon />
        <span className="trace-toggle-summary">
          {formatTokens(total)} tokens · {turns} {turns === 1 ? 'round' : 'rounds'} · {toolCalls} tool {toolCalls === 1 ? 'call' : 'calls'}
          {cost > 0 && <span className="trace-cost"> · ~${cost.toFixed(4)}</span>}
        </span>
        <ChevronIcon open={open} />
      </button>

      {open && (
        <div className="trace-detail">
          {/* Token breakdown */}
          <div className="trace-section">
            <div className="trace-section-title">Token breakdown</div>
            <TokenBar label="Prompt" value={prompt} max={total} color="var(--chart-1, #6366f1)" />
            <TokenBar label="Response" value={response} max={total} color="var(--chart-2, #22d3ee)" />
            {cached > 0 && (
              <TokenBar label="Cached" value={cached} max={prompt} color="var(--chart-5, #10b981)" />
            )}
          </div>

          {/* Cost estimate */}
          {cost > 0 && (
            <div className="trace-section">
              <div className="trace-section-title">Cost estimate</div>
              <div className="trace-cost-grid">
                <span className="trace-cost-label">This chat</span>
                <span className="trace-cost-value">${cost.toFixed(4)}</span>
                {saved > 0.0001 && (
                  <>
                    <span className="trace-cost-label">Saved by cache</span>
                    <span className="trace-cost-value trace-cost-saved">−${saved.toFixed(4)}</span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Per-round breakdown */}
          {per_turn.length > 0 && (
            <div className="trace-section">
              <div className="trace-section-title">Per-round detail</div>
              <table className="trace-table">
                <thead>
                  <tr>
                    <th>Round</th>
                    <th>Prompt</th>
                    <th>Response</th>
                    {per_turn.some((t) => t.cached_tokens > 0) && <th>Cached</th>}
                    <th>Tools</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {per_turn.map((t) => {
                    const rowTotal = t.prompt_tokens + t.response_tokens
                    const pct = maxTurnTokens > 0 ? (rowTotal / maxTurnTokens) * 100 : 0
                    return (
                      <tr key={t.round} style={{ '--row-pct': `${pct}%` }}>
                        <td className="trace-td-round">{t.round}</td>
                        <td>{formatTokens(t.prompt_tokens)}</td>
                        <td>{formatTokens(t.response_tokens)}</td>
                        {per_turn.some((t2) => t2.cached_tokens > 0) && (
                          <td className="trace-td-cached">{formatTokens(t.cached_tokens)}</td>
                        )}
                        <td>
                          {t.tools_used.length > 0 ? (
                            <span className="trace-tools-list" title={t.tools_used.join(', ')}>
                              {t.tools_used.length}× {t.tools_used[0]}
                              {t.tools_used.length > 1 && ` +${t.tools_used.length - 1}`}
                            </span>
                          ) : (
                            <span className="trace-tools-none">text</span>
                          )}
                        </td>
                        <td className="trace-td-time">{formatDuration(t.duration_ms)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
