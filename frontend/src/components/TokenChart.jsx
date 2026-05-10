import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import './TokenChart.css'

/* ── Color palette (max separation on dark bg) ── */
const COL_CACHED   = '#22d3c9'   // teal  — matches --accent-2
const COL_UNCACHED = '#f59e0b'   // amber — warm contrast
const COL_RESPONSE = '#8b5cf6'   // violet — cool but distinct

function formatTokens(n) {
  if (n == null || n === 0) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="token-chart-tooltip">
      <p className="token-chart-tooltip-label">{label}</p>
      {d.cached > 0 && (
        <p style={{ color: COL_CACHED }}>Cached: {formatTokens(d.cached)}</p>
      )}
      <p style={{ color: COL_UNCACHED }}>Uncached: {formatTokens(d.uncached)}</p>
      <p style={{ color: COL_RESPONSE }}>Response: {formatTokens(d.response)}</p>
      <p className="token-chart-tooltip-total">
        Total: {formatTokens(d.prompt + d.response)}
        {d.cached > 0 && (
          <span className="token-chart-tooltip-pct">
            {' '}({Math.round((d.cached / d.prompt) * 100)}% cached)
          </span>
        )}
      </p>
    </div>
  )
}

export default function TokenChart({ messages }) {
  const data = useMemo(() => {
    if (!messages?.length) return []

    const points = []
    let prevPrompt = 0
    let prevResponse = 0
    let prevCached = 0
    let msgIdx = 0

    for (const msg of messages) {
      if (msg.role !== 'agent' || !msg.tokenUsage) continue
      msgIdx++

      const tu = msg.tokenUsage
      const prompt   = Math.max(0, (tu.total_prompt_tokens || 0) - prevPrompt)
      const response = Math.max(0, (tu.total_response_tokens || 0) - prevResponse)
      const cached   = Math.max(0, (tu.total_cached_tokens || 0) - prevCached)
      const uncached = Math.max(0, prompt - cached)

      points.push({
        name: `Q${msgIdx}`,
        prompt,
        uncached,
        cached,
        response,
        cumulative: tu.total_tokens || 0,
        rounds: tu.turns || 0,
        tools: tu.total_tool_calls || 0,
      })

      prevPrompt  = tu.total_prompt_tokens || 0
      prevResponse = tu.total_response_tokens || 0
      prevCached   = tu.total_cached_tokens || 0
    }

    return points
  }, [messages])

  if (data.length === 0) return null

  const totalTokens = data[data.length - 1]?.cumulative || 0
  const totalCached = data.reduce((s, d) => s + d.cached, 0)
  const totalRounds = data.reduce((s, d) => s + d.rounds, 0)
  const totalTools  = data.reduce((s, d) => s + d.tools, 0)
  const cachePct = totalTokens > 0 ? Math.round((totalCached / totalTokens) * 100) : 0

  return (
    <div className="token-chart-panel">
      <div className="token-chart-stats">
        <div className="token-stat">
          <span className="token-stat-value">{formatTokens(totalTokens)}</span>
          <span className="token-stat-label">total tokens</span>
        </div>
        <div className="token-stat">
          <span className="token-stat-value">{data.length}</span>
          <span className="token-stat-label">{data.length === 1 ? 'query' : 'queries'}</span>
        </div>
        <div className="token-stat">
          <span className="token-stat-value">{totalRounds}</span>
          <span className="token-stat-label">LLM rounds</span>
        </div>
        <div className="token-stat">
          <span className="token-stat-value">{totalTools}</span>
          <span className="token-stat-label">tool calls</span>
        </div>
        {totalCached > 0 && (
          <div className="token-stat token-stat-cached">
            <span className="token-stat-value">{formatTokens(totalCached)}</span>
            <span className="token-stat-label">{cachePct}% cached</span>
          </div>
        )}
      </div>

      <div className="token-chart-container">
        <ResponsiveContainer width="100%" height={110}>
          <AreaChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="gradCached" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor={COL_CACHED} stopOpacity={0.45} />
                <stop offset="100%" stopColor={COL_CACHED} stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="gradUncached" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor={COL_UNCACHED} stopOpacity={0.45} />
                <stop offset="100%" stopColor={COL_UNCACHED} stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="gradResponse" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor={COL_RESPONSE} stopOpacity={0.4} />
                <stop offset="100%" stopColor={COL_RESPONSE} stopOpacity={0.05} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis
              dataKey="name"
              tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tickFormatter={formatTokens}
              tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={42}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="cached"
              stackId="1"
              stroke={COL_CACHED}
              strokeWidth={2}
              fill="url(#gradCached)"
              dot={{ r: 3, fill: COL_CACHED, strokeWidth: 0 }}
              activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
            />
            <Area
              type="monotone"
              dataKey="uncached"
              stackId="1"
              stroke={COL_UNCACHED}
              strokeWidth={2}
              fill="url(#gradUncached)"
              dot={{ r: 3, fill: COL_UNCACHED, strokeWidth: 0 }}
              activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
            />
            <Area
              type="monotone"
              dataKey="response"
              stackId="1"
              stroke={COL_RESPONSE}
              strokeWidth={2}
              fill="url(#gradResponse)"
              dot={{ r: 3, fill: COL_RESPONSE, strokeWidth: 0 }}
              activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="token-chart-legend">
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: COL_CACHED }} />
          Cached
        </span>
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: COL_UNCACHED }} />
          Uncached
        </span>
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: COL_RESPONSE }} />
          Response
        </span>
      </div>
    </div>
  )
}
