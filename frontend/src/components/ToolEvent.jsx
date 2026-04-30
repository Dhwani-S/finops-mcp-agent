import { useState, useCallback } from 'react'
import {
  humanizeToolCall,
  humanizeToolResult,
  humanizeThinkingMessage,
} from '../lib/finopsUi'
import './ToolEvent.css'

function IconThinking() {
  return (
    <svg className="tool-event-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M12 3a6 6 0 0 0-6 6c0 2 .5 3 2 5" strokeLinecap="round" />
      <path d="M18 9a6 6 0 0 1-6 6c-2 0-3-.5-5-2" strokeLinecap="round" />
      <path d="M12 21v-2M8 21h8" strokeLinecap="round" />
    </svg>
  )
}

function IconWrench() {
  return (
    <svg className="tool-event-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden>
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" strokeLinejoin="round" />
    </svg>
  )
}

function IconCheck() {
  return (
    <svg className="tool-event-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Chevron({ open }) {
  return (
    <svg className={`tool-event-chevron ${open ? 'is-open' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export default function ToolEvent({ event }) {
  const [expanded, setExpanded] = useState(false)
  const toggle = useCallback(() => setExpanded((v) => !v), [])
  const onKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        toggle()
      }
    },
    [toggle],
  )

  if (event.type === 'thinking') {
    return (
      <div className="tool-event tool-event--thinking" role="status">
        <span className="tool-event-icon-wrap" aria-hidden="true">
          <IconThinking />
        </span>
        <span className="tool-event-text">{humanizeThinkingMessage(event.message)}</span>
      </div>
    )
  }

  if (event.type === 'tool_call') {
    const expandable = Boolean(event.args && Object.keys(event.args).length)
    const headline = humanizeToolCall(event.tool)
    return (
      <div
        className={`tool-event tool-event--call ${expandable ? 'is-interactive' : ''}`}
        role={expandable ? 'button' : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? expanded : undefined}
        aria-label={expandable ? `${headline} Technical details` : undefined}
        onClick={expandable ? toggle : undefined}
        onKeyDown={expandable ? onKeyDown : undefined}
      >
        <span className="tool-event-icon-wrap tool-event-icon-wrap--accent" aria-hidden="true">
          <IconWrench />
        </span>
        <div className="tool-event-body">
          <div className="tool-event-row">
            <span className="tool-event-headline">{headline}</span>
            {expandable && <Chevron open={expanded} />}
          </div>
          {expandable && expanded && event.args && (
            <pre className="tool-event-detail">{JSON.stringify(event.args, null, 2)}</pre>
          )}
        </div>
      </div>
    )
  }

  if (event.type === 'tool_result') {
    const headline = humanizeToolResult(event.tool)
    return (
      <div
        className="tool-event tool-event--result is-interactive"
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`${headline}. Open for technical details.`}
        onClick={toggle}
        onKeyDown={onKeyDown}
      >
        <span className="tool-event-icon-wrap tool-event-icon-wrap--success" aria-hidden="true">
          <IconCheck />
        </span>
        <div className="tool-event-body">
          <div className="tool-event-row">
            <span className="tool-event-headline">{headline}</span>
            <Chevron open={expanded} />
          </div>
          {expanded && (
            <pre className="tool-event-detail">{event.result}</pre>
          )}
        </div>
      </div>
    )
  }

  return null
}
