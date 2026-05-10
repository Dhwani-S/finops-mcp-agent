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
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function formatChars(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatCost(promptTokens, responseTokens, cachedTokens) {
  const PROMPT_RATE = 1.25
  const RESPONSE_RATE = 10.0
  const CACHED_RATE = 0.3125

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

function ContextGrowthBar({ turns }) {
  if (!turns || turns.length < 2) return null
  const maxCum = Math.max(...turns.map((t) => t.cumulative_prompt || 0), 1)
  return (
    <div className="trace-context-growth">
      {turns.map((t) => {
        const pct = ((t.cumulative_prompt || 0) / maxCum) * 100
        return (
          <div key={t.round} className="trace-ctx-bar-wrapper" title={`R${t.round}: ${formatTokens(t.cumulative_prompt)} prompt tokens`}>
            <div className="trace-ctx-bar" style={{ height: `${pct}%` }} />
            <span className="trace-ctx-label">R{t.round}</span>
          </div>
        )
      })}
    </div>
  )
}

function ToolDetailRow({ td }) {
  const hasError = !!td.error
  return (
    <div className={`trace-tool-detail ${hasError ? 'has-error' : ''}`}>
      <span className="trace-tool-name" title={td.tool}>{td.tool}</span>
      <span className="trace-tool-server">{td.server}</span>
      <span className="trace-tool-chars" title={`~${formatTokens(td.result_tokens_est)} tokens`}>
        {formatChars(td.result_chars)} chars
        {td.truncated && <span className="trace-tool-tag truncated">cut</span>}
        {hasError && <span className="trace-tool-tag error">err</span>}
      </span>
      <span className="trace-tool-time">{formatDuration(td.duration_ms)}</span>
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
    total_duration_ms: totalDuration = 0,
    total_result_chars: totalResultChars = 0,
    turns = 0,
    per_turn = [],
  } = tokenUsage

  const { cost, saved } = formatCost(prompt, response, cached)
  const maxTurnTokens = Math.max(...per_turn.map((t) => t.prompt_tokens + t.response_tokens), 1)
  const hasCached = per_turn.some((t) => t.cached_tokens > 0)
  const hasToolDetails = per_turn.some((t) => t.tool_details?.length > 0)

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
          {totalDuration > 0 && <span className="trace-time"> · {formatDuration(totalDuration)}</span>}
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

          {/* Context growth */}
          {per_turn.length >= 2 && (
            <div className="trace-section">
              <div className="trace-section-title">
                Context growth
                <span className="trace-section-subtitle">
                  {formatTokens(per_turn[0]?.cumulative_prompt)} → {formatTokens(per_turn[per_turn.length - 1]?.cumulative_prompt)} prompt
                </span>
              </div>
              <ContextGrowthBar turns={per_turn} />
            </div>
          )}

          {/* Cost estimate */}
          {cost > 0 && (
            <div className="trace-section">
              <div className="trace-section-title">Cost estimate</div>
              <div className="trace-cost-grid">
                <span className="trace-cost-label">This query</span>
                <span className="trace-cost-value">${cost.toFixed(4)}</span>
                {saved > 0.0001 && (
                  <>
                    <span className="trace-cost-label">Saved by cache</span>
                    <span className="trace-cost-value trace-cost-saved">−${saved.toFixed(4)}</span>
                  </>
                )}
                {totalResultChars > 0 && (
                  <>
                    <span className="trace-cost-label">Tool result data</span>
                    <span className="trace-cost-value">{formatChars(totalResultChars)} chars (~{formatTokens(Math.round(totalResultChars / 4))} tok)</span>
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
                    {hasCached && <th>Cached</th>}
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
                        {hasCached && (
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

          {/* Tool-level details */}
          {hasToolDetails && (
            <div className="trace-section">
              <div className="trace-section-title">Tool execution detail</div>
              <div className="trace-tool-header">
                <span>Tool</span>
                <span>Server</span>
                <span>Result</span>
                <span>Time</span>
              </div>
              {per_turn.flatMap((t) =>
                (t.tool_details || []).map((td, i) => (
                  <ToolDetailRow key={`${t.round}-${i}`} td={td} />
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
