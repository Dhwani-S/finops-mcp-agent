import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell,
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
      <p style={{ color: 'var(--chart-1, #6366f1)' }}>Prompt: {formatTokens(d.prompt)}</p>
      <p style={{ color: 'var(--chart-2, #22d3ee)' }}>Response: {formatTokens(d.response)}</p>
      {d.cached > 0 && (
        <p style={{ color: 'var(--chart-5, #10b981)' }}>Cached: {formatTokens(d.cached)}</p>
      )}
      <p className="token-chart-tooltip-total">Total: {formatTokens(d.prompt + d.response)}</p>
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
      const prompt = (tu.total_prompt_tokens || 0) - prevPrompt
      const response = (tu.total_response_tokens || 0) - prevResponse
      const cached = (tu.total_cached_tokens || 0) - prevCached

      points.push({
        name: `Q${msgIdx}`,
        prompt: Math.max(0, prompt),
        response: Math.max(0, response),
        cached: Math.max(0, cached),
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

  const maxBar = Math.max(...data.map((d) => d.prompt + d.response))

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
            <span className="token-stat-label">cached</span>
          </div>
        )}
      </div>

      <div className="token-chart-container">
        <ResponsiveContainer width="100%" height={110}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barGap={2}>
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
              width={45}
              domain={[0, maxBar * 1.1]}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'color-mix(in srgb, var(--accent) 8%, transparent)' }} />
            <Bar dataKey="prompt" stackId="a" fill="var(--chart-1, #6366f1)" radius={[0, 0, 0, 0]} maxBarSize={40}>
              {data.map((_, i) => (
                <Cell key={i} radius={data[i].response > 0 ? [0, 0, 0, 0] : [3, 3, 0, 0]} />
              ))}
            </Bar>
            <Bar dataKey="response" stackId="a" fill="var(--chart-2, #22d3ee)" radius={[3, 3, 0, 0]} maxBarSize={40} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="token-chart-legend">
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: 'var(--chart-1, #6366f1)' }} />
          Prompt
        </span>
        <span className="token-legend-item">
          <span className="token-legend-dot" style={{ background: 'var(--chart-2, #22d3ee)' }} />
          Response
        </span>
        {totalCached > 0 && (
          <span className="token-legend-item">
            <span className="token-legend-dot" style={{ background: 'var(--chart-5, #10b981)' }} />
            Cached
          </span>
        )}
      </div>
    </div>
  )
}
