import { useState, useMemo } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  LineChart, Line, AreaChart, Area,
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

const CHART_TYPES = ['bar', 'stacked', 'line', 'area', 'hbar', 'pie', 'donut']

function ChartTypeIcon({ type }) {
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

  if (type === 'pie') {
    return (
      <svg {...common}>
        <path d="M21 12a9 9 0 1 1-9-9v9z" />
        <path d="M12 3a9 9 0 0 1 9 9h-9z" />
      </svg>
    )
  }

  if (type === 'donut') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="4" />
      </svg>
    )
  }

  if (type === 'line') {
    return (
      <svg {...common}>
        <path d="M4 19 8 13 12 15 16 9 20 5" />
      </svg>
    )
  }

  if (type === 'area') {
    return (
      <svg {...common}>
        <path d="M4 19 8 13 12 15 16 9 20 5V19H4Z" fill="currentColor" opacity="0.2" />
        <path d="M4 19 8 13 12 15 16 9 20 5" />
      </svg>
    )
  }

  if (type === 'hbar') {
    return (
      <svg {...common}>
        <path d="M4 4v16" />
        <path d="M4 20h16" />
        <rect x="6" y="6" width="10" height="3" rx="1" />
        <rect x="6" y="11" width="7" height="3" rx="1" />
        <rect x="6" y="16" width="12" height="3" rx="1" />
      </svg>
    )
  }

  if (type === 'stacked') {
    return (
      <svg {...common}>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <rect x="7" y="13" width="3" height="3" rx="0" fill="currentColor" opacity="0.3" />
        <rect x="7" y="9" width="3" height="4" rx="0" fill="currentColor" opacity="0.6" />
        <rect x="12" y="10" width="3" height="3" rx="0" fill="currentColor" opacity="0.3" />
        <rect x="12" y="5" width="3" height="5" rx="0" fill="currentColor" opacity="0.6" />
        <rect x="17" y="11" width="3" height="4" rx="0" fill="currentColor" opacity="0.3" />
        <rect x="17" y="8" width="3" height="3" rx="0" fill="currentColor" opacity="0.6" />
      </svg>
    )
  }

  return (
    <svg {...common}>
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <rect x="7" y="11" width="3" height="5" rx="1" />
      <rect x="12" y="7" width="3" height="9" rx="1" />
      <rect x="17" y="9" width="3" height="7" rx="1" />
    </svg>
  )
}

const CHART_TYPE_LABELS = {
  bar: 'Bar',
  stacked: 'Stacked',
  line: 'Line',
  area: 'Area',
  hbar: 'H-Bar',
  pie: 'Pie',
  donut: 'Donut',
}

/**
 * Auto-detect the best chart type based on data characteristics.
 */
function detectBestChartType(data, labelKey, valueKeys, isMultiCloud) {
  if (!data || data.length === 0) return 'bar'

  const rowCount = data.length
  const labels = data.map((r) => r[labelKey])
  const distinctLabels = new Set(labels).size
  const hasMultipleValues = valueKeys.length > 1

  // Check if labels look like dates/time-series
  const datePattern = /^\d{4}[-/]\d{2}|^\d{2}[-/]\d{2}|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|week|day|month)/i
  const isTimeSeries = labels.filter((l) => datePattern.test(String(l))).length > rowCount * 0.5

  if (isTimeSeries) return hasMultipleValues ? 'area' : 'line'

  // Multi-cloud pivoted data → stacked bar
  if (isMultiCloud && hasMultipleValues) return 'stacked'

  // Many items with long labels → horizontal bar (even with multiple value keys)
  const avgLabelLen = labels.reduce((s, l) => s + String(l).length, 0) / rowCount
  if ((rowCount > 10 && avgLabelLen > 15) || avgLabelLen > 25) return 'hbar'

  // Multiple value keys → stacked bar for comparison
  if (hasMultipleValues) return 'stacked'

  // Few categories with single value → donut/pie
  if (distinctLabels <= 6 && !hasMultipleValues) return 'donut'

  // Many categories (>8) with long labels → horizontal bar
  if (rowCount > 8 || avgLabelLen > 20) return 'hbar'

  return 'bar'
}

/**
 * Try to extract chartable JSON arrays from tool_result strings.
 * Returns an array of { label, data, labelKey, valueKeys } objects.
 *
 * When data contains a `_cloud` column (from run_multi_cloud_query),
 * pivots the data so each cloud becomes a separate series — enabling
 * grouped/stacked bar comparisons.
 *
 * When multiple tool_result events have similar schemas (same numeric
 * column names), merges them into a single combined chart.
 */
export function extractChartData(events) {
  if (!events?.length) return []

  const charts = []
  // Track run_query results for potential merging
  const runQueryResults = []

  // Tools whose output is recommendations/findings, not chart-friendly data
  const SKIP_CHART_TOOLS = new Set([
    'evaluate_vm_rightsizing',
    'score_recommendations',
    'cross_examine_recommendations',
    'summarize_data',
  ])

  // Max items to render in a single chart to prevent dense/unreadable graphs
  const MAX_CHART_ITEMS = 20

  for (const evt of events) {
    if (evt.type !== 'tool_result' || !evt.result) continue

    // Skip tools that produce findings/recommendations, not chart data
    if (SKIP_CHART_TOOLS.has(evt.tool)) continue

    let parsed
    try {
      parsed = JSON.parse(evt.full_result || evt.result)
    } catch {
      continue
    }

    // Handle wrapped results like { values: [...] } or { top_results: [...] }
    if (!Array.isArray(parsed)) {
      const arrayField = parsed?.values || parsed?.top_results || parsed?.results || parsed?.rows || parsed?.data
      if (Array.isArray(arrayField)) {
        parsed = arrayField
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
    let data = parsed
      .map((row) => {
        const entry = { [labelKey]: row[labelKey] }
        for (const vk of valueKeys) {
          entry[vk] = typeof row[vk] === 'number' ? Math.round(row[vk] * 100) / 100 : row[vk]
        }
        return entry
      })
      .filter((entry) => valueKeys.some((vk) => entry[vk] && Math.abs(entry[vk]) > 0.005))

    // Deduplicate: if label values repeat, aggregate by summing numeric values
    const labelCounts = {}
    for (const row of data) {
      labelCounts[row[labelKey]] = (labelCounts[row[labelKey]] || 0) + 1
    }
    const hasDuplicates = Object.values(labelCounts).some((c) => c > 1)
    if (hasDuplicates) {
      const grouped = {}
      for (const row of data) {
        const key = row[labelKey]
        if (!grouped[key]) {
          grouped[key] = { ...row, __count: 1 }
        } else {
          for (const vk of valueKeys) {
            grouped[key][vk] = (grouped[key][vk] || 0) + (row[vk] || 0)
          }
          grouped[key].__count++
        }
      }
      data = Object.values(grouped).map(({ __count, ...rest }) => rest)
    }

    if (data.length < 1) continue

    // Check for _cloud column → pivot into per-cloud value columns
    const cloudCol = Object.keys(data[0]).find(
      (k) => k === '_cloud' || k === 'cloud' || k === 'Cloud'
    )
    if (cloudCol && valueKeys.length === 1) {
      const clouds = [...new Set(data.map((r) => r[cloudCol]))]
      if (clouds.length >= 2 && clouds.length <= 6) {
        // Find the non-cloud label key
        const pivotLabelKey = stringKeys.find((k) => k !== cloudCol) || labelKey
        // Build pivoted data: { service: "Compute", AWS: 123, Azure: 456, GCP: 789 }
        const grouped = {}
        const vk = valueKeys[0]
        for (const row of data) {
          const label = row[pivotLabelKey]
          if (!grouped[label]) {
            grouped[label] = { [pivotLabelKey]: label }
            for (const c of clouds) grouped[label][c] = 0
          }
          grouped[label][row[cloudCol]] = (grouped[label][row[cloudCol]] || 0) + (row[vk] || 0)
        }
        const pivoted = Object.values(grouped)
        if (pivoted.length >= 1) {
          charts.push({
            label: evt.tool || 'Cloud comparison',
            data: pivoted,
            labelKey: pivotLabelKey,
            valueKeys: clouds,
            isMultiCloud: true,
          })
          continue
        }
      }
    }

    // For run_query results, collect for potential merging
    if (evt.tool === 'run_query') {
      // Cap at MAX_CHART_ITEMS — sort by first numeric key descending and take top N
      if (data.length > MAX_CHART_ITEMS) {
        data.sort((a, b) => (b[valueKeys[0]] || 0) - (a[valueKeys[0]] || 0))
        data = data.slice(0, MAX_CHART_ITEMS)
      }
      runQueryResults.push({ data, labelKey, valueKeys, label: evt.tool })
      continue
    }

    // Cap non-query charts too
    if (data.length > MAX_CHART_ITEMS) {
      data.sort((a, b) => (b[valueKeys[0]] || 0) - (a[valueKeys[0]] || 0))
      data = data.slice(0, MAX_CHART_ITEMS)
    }

    charts.push({
      label: evt.tool || 'Query result',
      data,
      labelKey,
      valueKeys,
    })
  }

  // Merge multiple run_query results with similar schemas into one chart
  if (runQueryResults.length > 1) {
    // Check if all have same numeric column names (e.g., all have "cost" or "total_cost")
    const firstValueKeys = runQueryResults[0].valueKeys.map((k) => k).sort().join(',')
    const allSameSchema = runQueryResults.every(
      (r) => r.valueKeys.map((k) => k).sort().join(',') === firstValueKeys
    )
    if (allSameSchema) {
      // Merge all data into one array, deduplicate by label
      const mergedLabelKey = runQueryResults[0].labelKey
      const mergedValueKeys = runQueryResults[0].valueKeys
      let mergedData = []
      for (const rq of runQueryResults) {
        mergedData = mergedData.concat(rq.data)
      }
      // Sort by first value key descending
      mergedData.sort((a, b) => (b[mergedValueKeys[0]] || 0) - (a[mergedValueKeys[0]] || 0))
      // Take top entries to avoid huge charts
      if (mergedData.length > 15) mergedData = mergedData.slice(0, 15)

      charts.push({
        label: 'Combined results',
        data: mergedData,
        labelKey: mergedLabelKey,
        valueKeys: mergedValueKeys,
      })
    } else {
      // Different schemas — keep as separate charts
      for (const rq of runQueryResults) {
        charts.push(rq)
      }
    }
  } else if (runQueryResults.length === 1) {
    charts.push(runQueryResults[0])
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
  const { data, labelKey, valueKeys, isMultiCloud, title } = chartData || {}

  const bestType = useMemo(
    () => detectBestChartType(data, labelKey, valueKeys, isMultiCloud),
    [data, labelKey, valueKeys, isMultiCloud]
  )
  const [chartType, setChartType] = useState(null) // null = use auto-detected

  if (!chartData || !data || data.length === 0) return null

  const activeType = chartType || bestType
  const primaryValue = valueKeys[0]

  // Pie/Donut chart needs more height when there are many legend items
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
              className={`chart-type-btn ${activeType === t ? 'active' : ''}`}
              onClick={() => setChartType(t)}
              title={CHART_TYPE_LABELS[t]}
            >
              <ChartTypeIcon type={t} />
              {CHART_TYPE_LABELS[t]}
            </button>
          ))}
        </div>
      </div>

      <div className="chart-container">
        {activeType === 'bar' && (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey={labelKey}
                angle={-45}
                textAnchor="end"
                tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
                tickFormatter={(v) => truncateLabel(v, 18)}
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

        {activeType === 'stacked' && (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey={labelKey}
                angle={-45}
                textAnchor="end"
                tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
                tickFormatter={(v) => truncateLabel(v, 18)}
                interval={0}
                height={80}
              />
              <YAxis
                tickFormatter={formatCurrency}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                width={65}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {valueKeys.map((vk, i) => (
                <Bar key={vk} dataKey={vk} stackId="stack" fill={COLORS[i % COLORS.length]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        {activeType === 'hbar' && (
          <ResponsiveContainer width="100%" height={Math.max(300, data.length * 36)}>
            <BarChart data={data} layout="vertical" margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" horizontal={false} />
              <XAxis
                type="number"
                tickFormatter={formatCurrency}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
              />
              <YAxis
                type="category"
                dataKey={labelKey}
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                tickFormatter={(v) => truncateLabel(v, 32)}
                width={180}
              />
              <Tooltip content={<CustomTooltip />} />
              {valueKeys.length > 1 && <Legend />}
              {valueKeys.map((vk, i) => (
                <Bar key={vk} dataKey={vk} fill={COLORS[i % COLORS.length]} radius={[0, 4, 4, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}

        {activeType === 'line' && (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey={labelKey}
                angle={-45}
                textAnchor="end"
                tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
                tickFormatter={(v) => truncateLabel(v, 18)}
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
                <Line
                  key={vk}
                  type="monotone"
                  dataKey={vk}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}

        {activeType === 'area' && (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey={labelKey}
                angle={-45}
                textAnchor="end"
                tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
                tickFormatter={(v) => truncateLabel(v, 18)}
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
                <Area
                  key={vk}
                  type="monotone"
                  dataKey={vk}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        )}

        {activeType === 'pie' && (
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

        {activeType === 'donut' && (
          <ResponsiveContainer width="100%" height={pieHeight}>
            <PieChart>
              <Pie
                data={data}
                dataKey={primaryValue}
                nameKey={labelKey}
                cx="50%"
                cy="40%"
                innerRadius={55}
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
