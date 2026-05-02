/**
 * Auto-detect conversation category/tag from the first user message.
 * Returns { tag, color } or null.
 */

const TAG_RULES = [
  { tag: 'Anomaly', color: '#ef4444', patterns: ['anomal', 'spike', 'unusual', 'unexpected', 'surge', 'alert'] },
  { tag: 'Budget', color: '#f59e0b', patterns: ['budget', 'forecast', 'on track', 'overrun', 'burn rate'] },
  { tag: 'Savings', color: '#10b981', patterns: ['saving', 'recommend', 'idle', 'unattached', 'rightsize', 'optimiz'] },
  { tag: 'Trends', color: '#8b5cf6', patterns: ['trend', 'month-over-month', 'mom', 'growth', 'week-over-week', 'yoy', 'forecast'] },
  { tag: 'Compare', color: '#06b6d4', patterns: ['compare', 'vs', 'versus', 'difference', 'multi-cloud'] },
  { tag: 'Cost', color: '#3b82f6', patterns: ['spend', 'cost', 'expensive', 'breakdown', 'top', 'service'] },
  { tag: 'Report', color: '#ec4899', patterns: ['report', 'export', 'excel', 'csv', 'pdf', 'generate'] },
]

export function detectTag(firstMessage) {
  if (!firstMessage) return null
  const lower = firstMessage.toLowerCase()

  for (const rule of TAG_RULES) {
    if (rule.patterns.some((p) => lower.includes(p))) {
      return { tag: rule.tag, color: rule.color }
    }
  }
  return null
}

export { TAG_RULES }
