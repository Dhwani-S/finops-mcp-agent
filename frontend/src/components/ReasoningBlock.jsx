import { useState, useCallback } from 'react'
import ToolEvent from './ToolEvent'
import {
  humanizeToolCall,
  humanizeToolResult,
  humanizeThinkingMessage,
} from '../lib/finopsUi'
import './ReasoningBlock.css'

/**
 * Build a short one-line summary from events, e.g. "Queried cost data · Retrieved results"
 */
function buildSummary(events) {
  if (!events?.length) return 'Thinking…'

  // Gather unique step labels (skip duplicates)
  const seen = new Set()
  const steps = []

  for (const evt of events) {
    let label = ''
    if (evt.type === 'thinking') {
      label = humanizeThinkingMessage(evt.message)
    } else if (evt.type === 'tool_call') {
      label = humanizeToolCall(evt.tool)
    } else if (evt.type === 'tool_result') {
      // Skip result labels — the call label is enough
      continue
    }
    if (label && !seen.has(label)) {
      seen.add(label)
      steps.push(label)
    }
  }

  if (steps.length === 0) return 'Thinking…'
  if (steps.length <= 2) return steps.join(' · ')
  return `${steps[0]} · ${steps.length - 1} more steps`
}

/**
 * Get the last in-progress step for the live indicator
 */
function getActiveStep(events, loading) {
  if (!loading || !events?.length) return null
  // Find the last thinking or tool_call event
  for (let i = events.length - 1; i >= 0; i--) {
    const evt = events[i]
    if (evt.type === 'thinking') return humanizeThinkingMessage(evt.message)
    if (evt.type === 'tool_call') return humanizeToolCall(evt.tool)
  }
  return null
}

export default function ReasoningBlock({ events, loading }) {
  const [expanded, setExpanded] = useState(false)
  const toggle = useCallback(() => setExpanded((v) => !v), [])

  const activeStep = getActiveStep(events, loading)
  const summary = buildSummary(events)
  const toolCount = events.filter((e) => e.type === 'tool_call').length

  return (
    <div className={`reasoning-block ${expanded ? 'is-expanded' : ''}`}>
      <button
        type="button"
        className="reasoning-header"
        onClick={toggle}
        aria-expanded={expanded}
        aria-label="Toggle reasoning details"
      >
        <span className="reasoning-indicator">
          {loading ? (
            <span className="reasoning-spinner" aria-hidden="true" />
          ) : (
            <svg className="reasoning-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
              <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>

        <span className="reasoning-summary">
          {loading && activeStep ? activeStep : summary}
        </span>

        {toolCount > 0 && !loading && (
          <span className="reasoning-badge">{toolCount} {toolCount === 1 ? 'tool' : 'tools'}</span>
        )}

        <svg
          className={`reasoning-chevron ${expanded ? 'is-open' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden
        >
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {expanded && (
        <div className="reasoning-details">
          {events.map((evt, i) => (
            <ToolEvent key={i} event={evt} />
          ))}
        </div>
      )}
    </div>
  )
}
