import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import './TokenChart.css'

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
        <p style={{ color: '#10b981' }}>Cached: {formatTokens(d.cached)}</p>
      )}
      <p style={{ color: '#6366f1' }}>Uncached: {formatTokens(d.uncached)}</p>
      <p style={{ color: '#22d3ee' }}>Response: {formatTokens(d.response)}</p>
      <p className="token-chart-tooltip-total">
        Total: {formatTokens(d.prompt + d.response)}
        {d.cached > 0 && (
          <span className="token-chart-tooltip-pct"> ({Math.round((d.cached / d.prompt) * 100)}% cached)</span>
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
      const prompt = Math.max(0, (tu.total_prompt_tokens || 0) - prevPrompt)
      const response = Math.max(0, (tu.total_response_tokens || 0) - prevResponse)
      const cached = Math.max(0, (tu.total_cached_tokens || 0) - prevCached)
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

      prevPrompt = tu.total_prompt_tokens || 0
      prevResponse = tu.total_response_tokens || 0
      prevCached = tu.total_cached_tokens || 0
    }

    return points
  }, [messages])

  if (data.length === 0) return null

  const totalTokens = data[data.length - 1]?.cumulative || 0
  const totalCached = data.reduce((s, d) => s + d.cached, 0)
  const totalRounds = data.reduce((s, d) => s + d.rounds, 0)
  const totalTools = data.reduce((s, d) => s + d.tools, 0)
  const cachePct = totalTokens > 0 ? Math.round((totalCached / totalTokens) * 100) : 0

  // Dynamic bar width: wider when fewer data points
  const barSize = data.length <= 3 ? 48 : data.length <= 6 ? 36 : undefined

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
        <ResponsiveContainer width="100%" height={100}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barCategoryGap={data.length <= 3 ? '30%' : '20%'}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
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
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'color-mix(in srgb, var(--accent) 8%, transparent)' }} />
            <Bar dataKey="cached" stackId="a" fill="var(--chart-5, #10b981)" radius={[0, 0, 0, 0]} barSize={barSize} />
            <Bar dataKey="uncached" stackId="a" fill="var(--chart-1, #6366f1)" radius={[3, 3, 0, 0]} barSize={barSize} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="token-chart-legend">
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: 'var(--chart-5, #10b981)' }} />
          Cached
        </span>
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: 'var(--chart-1, #6366f1)' }} />
          Uncached
        </span>
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: 'var(--chart-2, #22d3ee)' }} />
          Response
        </span>
      </div>
    </div>
  )
}
