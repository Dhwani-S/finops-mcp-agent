import { useState, useCallback } from 'react'
import ToolEvent from './ToolEvent'
import {
  humanizeToolCall,
  humanizeToolResult,
  humanizeThinkingMessage,
} from '../lib/finopsUi'
import './ReasoningBlock.css'

/* ── Per-type step icons ── */
function StepIconThinking() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" strokeOpacity="0.3" />
      <path d="M12 6v2m0 8v2m-4.24-9.76l1.42 1.42m5.64 5.64l1.42 1.42M6 12h2m8 0h2m-2.24-4.24l-1.42 1.42m-5.64 5.64l-1.42 1.42" strokeLinecap="round" />
    </svg>
  )
}

function StepIconTool() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" strokeLinejoin="round" />
    </svg>
  )
}

function StepIconResult() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" strokeLinecap="round" />
      <path d="M22 4 12 14.01l-3-3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function getStepIcon(type) {
  switch (type) {
    case 'thinking': return <StepIconThinking />
    case 'tool_call': return <StepIconTool />
    case 'result': return <StepIconResult />
    default: return <StepIconResult />
  }
}

/**
 * Build a short one-line summary from events, e.g. "Queried cost data · Retrieved results"
 */
function buildSummary(events) {
  if (!events?.length) return 'Thinking…'

  const seen = new Set()
  const steps = []

  for (const evt of events) {
    let label = ''
    if (evt.type === 'thinking') {
      label = humanizeThinkingMessage(evt.message)
    } else if (evt.type === 'tool_call') {
      label = humanizeToolCall(evt.tool)
    } else if (evt.type === 'tool_result') {
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
 * Build step list for animated display.
 * Each step = { label, status: 'done' | 'active', type }
 */
function buildSteps(events, loading) {
  const steps = []
  const seen = new Set()

  for (let i = 0; i < events.length; i++) {
    const evt = events[i]
    let label = ''
    let type = evt.type

    if (evt.type === 'thinking') {
      label = humanizeThinkingMessage(evt.message)
    } else if (evt.type === 'tool_call') {
      label = humanizeToolCall(evt.tool)
    } else if (evt.type === 'tool_result') {
      label = humanizeToolResult(evt.tool, evt.result)
      type = 'result'
    }

    if (!label) continue
    const key = `${type}:${label}`
    if (seen.has(key)) continue
    seen.add(key)

    steps.push({
      label,
      type,
      status: loading && i === events.length - 1 ? 'active' : 'done',
    })
  }

  return steps
}

export default function ReasoningBlock({ events, loading }) {
  const [expanded, setExpanded] = useState(false)
  const toggle = useCallback(() => setExpanded((v) => !v), [])

  const steps = buildSteps(events, loading)
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
          {loading ? (steps.length > 0 ? steps[steps.length - 1].label : 'Thinking…') : summary}
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
          {loading && steps.length > 0 ? (
            <div className="reasoning-steps">
              {steps.map((step, i) => (
                <div
                  key={i}
                  className={`reasoning-step reasoning-step--${step.status} reasoning-step--${step.type}`}
                  style={{ animationDelay: `${i * 0.05}s` }}
                >
                  <span className="reasoning-step-icon">
                    {step.status === 'active' ? (
                      <span className="reasoning-step-pulse" />
                    ) : (
                      getStepIcon(step.type)
                    )}
                  </span>
                  <span className="reasoning-step-label">{step.label}</span>
                </div>
              ))}
            </div>
          ) : (
            events.map((evt, i) => (
              <ToolEvent key={i} event={evt} />
            ))
          )}
        </div>
      )}
    </div>
  )
}
