/**
 * Labels and copy for a business / product audience (hide infra details).
 */

/** Backend server keys → user-facing service names */
export const CONNECTED_SERVICE_LABELS = {
  bq: 'Cost data',
  sql: 'Savings & usage data',
  analytics: 'Trends & anomalies',
  file: 'Reports & files',
}

export function serviceLabelForServerKey(key) {
  if (!key) return 'Service'
  const k = String(key).toLowerCase()
  return CONNECTED_SERVICE_LABELS[k] ?? key.charAt(0).toUpperCase() + key.slice(1)
}

export const TIME_RANGE_OPTIONS = [
  { id: 'last_7', label: 'Last 7 days' },
  { id: 'last_month', label: 'Last month' },
  { id: 'quarter', label: 'This quarter' },
  { id: 'ytd', label: 'Year to date' },
  { id: 'any', label: 'Any period' },
]

export const CLOUD_OPTIONS = [
  { id: 'all', label: 'All clouds' },
  { id: 'aws', label: 'AWS' },
  { id: 'azure', label: 'Azure' },
  { id: 'gcp', label: 'GCP' },
]

const TIME_INSTRUCTIONS = {
  last_7: 'Please focus on roughly the last 7 days of cost data.',
  last_month: 'Please focus on the most recent full calendar month unless I say otherwise.',
  quarter: 'Please focus on the current calendar quarter to date.',
  ytd: 'Please focus on year-to-date spend.',
}

const CLOUD_INSTRUCTIONS = {
  aws: 'Please focus on AWS only.',
  azure: 'Please focus on Azure only.',
  gcp: 'Please focus on Google Cloud (GCP) only.',
}

/**
 * Prepends scope hints for the model only. The UI should still show `userText` as typed.
 */
export function augmentMessageForAgent(userText, { timeRange, cloud }) {
  const trimmed = userText.trim()
  const hints = []
  if (timeRange && timeRange !== 'any' && TIME_INSTRUCTIONS[timeRange]) {
    hints.push(TIME_INSTRUCTIONS[timeRange])
  }
  if (cloud && cloud !== 'all' && CLOUD_INSTRUCTIONS[cloud]) {
    hints.push(CLOUD_INSTRUCTIONS[cloud])
  }
  if (hints.length === 0) return trimmed
  return `${hints.join(' ')}\n\n${trimmed}`
}

const TOOL_CALL_PHRASES = [
  [/run_bq_query|run_sql_query/i, 'Looking up your cost data…'],
  [/^schema_|get_table_schema$/i, 'Checking which fields are available…'],
  [/guide_|taxonomy_|reference_|elicitation_/i, 'Gathering context to answer accurately…'],
  [/cost_breakdown|period_comparison/i, 'Breaking down spend…'],
  [/detect_anomalies|anomaly_investigation|investigate_anomaly/i, 'Scanning for unusual spend…'],
  [/forecast|forecast_summary/i, 'Projecting trends…'],
  [/calculate_growth/i, 'Measuring how spend changed…'],
  [/score_recommendations|validate_results/i, 'Double-checking recommendations…'],
  [/export_csv|write_file|append_file|read_file|list_files|delete_file|get_report|executive_summary|chargeback_report/i, 'Preparing files or a report…'],
  [/sql_exploration/i, 'Exploring savings opportunities…'],
]

export function humanizeToolCall(toolName) {
  const t = toolName || ''
  for (const [re, label] of TOOL_CALL_PHRASES) {
    if (re.test(t)) return label
  }
  return 'Gathering the numbers…'
}

export function humanizeToolResult(toolName) {
  const t = toolName || ''
  if (/export_csv|write_file|executive_summary|chargeback_report|get_report|append_file/i.test(t)) {
    return 'Output ready — open for details'
  }
  if (/forecast|detect_anomalies|calculate_growth|cost_breakdown|period_comparison|anomaly_investigation|investigate_anomaly/i.test(t)) {
    return 'Analysis ready — open for details'
  }
  if (/run_bq_query|run_sql_query/i.test(t)) {
    return 'Data retrieved — open for details'
  }
  return 'Step complete — open for details'
}

export function humanizeThinkingMessage(message) {
  if (!message) return 'Working on your question…'
  if (/Understanding your question/i.test(message)) return 'Understanding your question…'
  if (/Processing your query/i.test(message)) return 'Working on your question…'
  const m = message.match(/Analyzing results \(round (\d+)\)/i)
  if (m) return `Reviewing what we found (step ${m[1]})…`
  return message
}
