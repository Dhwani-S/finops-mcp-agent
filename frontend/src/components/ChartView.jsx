import { useState } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import './ChartView.css'

const COLORS = [
  'var(--chart-1, #6366f1)',
  'var(--chart-2, #22d3ee)',
  'var(--chart-3, #f59e0b)',
  'var(--chart-4, #ef4444)',
  'var(--chart-5, #10b981)',
  'var(--chart-6, #8b5cf6)',
  'var(--chart-7, #ec4899)',
  'var(--chart-8, #14b8a6)',
]

const CHART_TYPES = ['bar', 'pie']

/**
 * Try to extract chartable JSON arrays from tool_result strings.
 * Returns an array of { label, data, labelKey, valueKeys } objects.
 */
export function extractChartData(events) {
  if (!events?.length) return []

  const charts = []

  for (const evt of events) {
    if (evt.type !== 'tool_result' || !evt.result) continue

    let parsed
    try {
      parsed = JSON.parse(evt.result)
    } catch {
      continue
    }

    // Handle wrapped results like { values: [...] }
    if (!Array.isArray(parsed)) {
      if (parsed?.values && Array.isArray(parsed.values)) {
        parsed = parsed.values
      } else {
        continue
      }
    }

    if (parsed.length < 2) continue

    // Find string keys (labels) and numeric keys (values)
    const sample = parsed[0]
    const stringKeys = []
    const numericKeys = []

    for (const [k, v] of Object.entries(sample)) {
      if (typeof v === 'string') stringKeys.push(k)
      else if (typeof v === 'number') numericKeys.push(k)
    }

    if (stringKeys.length === 0 || numericKeys.length === 0) continue

    // Pick the string key with the most distinct values as the label
    let labelKey = stringKeys[0]
    let maxDistinct = 0
    for (const sk of stringKeys) {
      const distinct = new Set(parsed.map((r) => r[sk])).size
      if (distinct > maxDistinct) {
        maxDistinct = distinct
        labelKey = sk
      }
    }
    const valueKeys = numericKeys

    // Build chart-ready data — filter out rows where all numeric values are zero
    const data = parsed
      .map((row) => {
        const entry = { [labelKey]: row[labelKey] }
        for (const vk of valueKeys) {
          entry[vk] = typeof row[vk] === 'number' ? Math.round(row[vk] * 100) / 100 : row[vk]
        }
        return entry
      })
      .filter((entry) => valueKeys.some((vk) => entry[vk] && Math.abs(entry[vk]) > 0.005))

    charts.push({
      label: evt.tool || 'Query result',
      data,
      labelKey,
      valueKeys,
    })
  }

  return charts
}

function formatCurrency(value) {
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(2)}`
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-label">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="chart-tooltip-value" style={{ color: p.color }}>
          {p.name}: {formatCurrency(p.value)}
        </p>
      ))}
    </div>
  )
}

function PieLabel({ cx, cy, midAngle, outerRadius, percent, name }) {
  if (percent < 0.05) return null
  const RADIAN = Math.PI / 180
  // Place labels outside the pie with a line
  const radius = outerRadius + 24
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)
  return (
    <text
      x={x}
      y={y}
      fill="var(--text-secondary)"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      fontSize={11}
      fontWeight={500}
    >
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  )
}

export default function ChartView({ chartData }) {
  const [chartType, setChartType] = useState('bar')

  if (!chartData || chartData.data.length === 0) return null

  const { data, labelKey, valueKeys } = chartData
  const primaryValue = valueKeys[0]

  // Pie chart needs more height when there are many legend items
  const pieHeight = Math.max(380, 300 + data.length * 12)

  // Truncate long labels for better chart readability
  const truncateLabel = (label, max = 30) =>
    typeof label === 'string' && label.length > max ? label.slice(0, max) + '…' : label

  return (
    <div className="chart-view">
      <div className="chart-header">
        <div className="chart-type-toggle">
          {CHART_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              className={`chart-type-btn ${chartType === t ? 'active' : ''}`}
              onClick={() => setChartType(t)}
            >
              {t === 'bar' ? '📊' : '🍩'} {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="chart-container">
        {chartType === 'bar' && (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey={labelKey}
                angle={-35}
                textAnchor="end"
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                tickFormatter={(v) => truncateLabel(v, 25)}
                interval={0}
                height={80}
              />
              <YAxis
                tickFormatter={formatCurrency}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                width={65}
              />
              <Tooltip content={<CustomTooltip />} />
              {valueKeys.length > 1 && <Legend />}
              {valueKeys.map((vk, i) => (
                <Bar key={vk} dataKey={vk} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        {chartType === 'pie' && (
          <ResponsiveContainer width="100%" height={pieHeight}>
            <PieChart>
              <Pie
                data={data}
                dataKey={primaryValue}
                nameKey={labelKey}
                cx="50%"
                cy="40%"
                outerRadius={Math.min(110, 90 + Math.max(0, 8 - data.length) * 3)}
                labelLine
                label={PieLabel}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend
                layout="horizontal"
                verticalAlign="bottom"
                align="center"
                wrapperStyle={{ paddingTop: '16px', fontSize: '12px', lineHeight: '1.8' }}
                formatter={(value) => (
                  <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    {truncateLabel(value, 40)}
                  </span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
