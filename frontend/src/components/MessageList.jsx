import { useEffect, useRef } from 'react'
import Message from './Message'
import { EXPLORE_CHIPS } from '../lib/exploreChips'
import { WORKFLOW_CARDS } from '../lib/workflowCards'
import './MessageList.css'

function WorkflowIcon({ name, size = 20 }) {
  const common = {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round',
  }
  switch (name) {
    case 'bar-chart':
      return <svg {...common}><path d="M4 19V5"/><path d="M4 19h16"/><rect x="7" y="11" width="3" height="5" rx="1"/><rect x="12" y="7" width="3" height="9" rx="1"/><rect x="17" y="9" width="3" height="7" rx="1"/></svg>
    case 'layers':
      return <svg {...common}><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    case 'piggy-bank':
      return <svg {...common}><path d="M19 5c-1.5 0-2.8 1.4-3 2-3.5-1.5-11-.3-11 5 0 1.8 0 3 2 4.5V20h4v-2h3v2h4v-4c1-.5 1.7-1 2-2h2v-4h-2c0-1-.5-1.5-1-2"/><path d="M2 9v1c0 1.1.9 2 2 2h1"/><circle cx="13" cy="9" r="1"/></svg>
    case 'alert-triangle':
      return <svg {...common}><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    case 'trending-up':
      return <svg {...common}><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
    case 'gauge':
      return <svg {...common}><path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M12 6v6l4 2"/></svg>
    default:
      return null
  }
}

export default function MessageList({ messages, onSuggestion, suggestionsDisabled, chartMode }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="message-list-empty">
        <div className="empty-hero">
          <p className="empty-kicker">Cloud cost, without the jargon</p>
          <h2 className="empty-heading">What would you like to do?</h2>
          <p className="empty-lead">
            Pick a workflow below or type your own question — the agent will guide you from there.
          </p>
        </div>
        <div className="empty-explore" aria-label="Topics you can explore">
          <span className="empty-explore-label">You can explore</span>
          <div className="empty-explore-scroll">
            {EXPLORE_CHIPS.map((c) => (
              <span key={c.id} className="empty-explore-chip">{c.label}</span>
            ))}
          </div>
        </div>
        <div className="workflow-grid" role="list" aria-label="Guided workflows">
          {WORKFLOW_CARDS.map((card) => (
            <button
              key={card.id}
              type="button"
              className="workflow-card"
              disabled={suggestionsDisabled}
              onClick={() => onSuggestion?.(card.prompt)}
            >
              <span className="workflow-card-icon">
                <WorkflowIcon name={card.icon} />
              </span>
              <span className="workflow-card-body">
                <span className="workflow-card-label">{card.label}</span>
                <span className="workflow-card-desc">{card.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="message-list">
      {messages.map((msg, i) => (
        <Message
          key={i}
          message={msg}
          onOptionClick={onSuggestion}
          disabled={suggestionsDisabled}
          chartMode={chartMode}
        />
      ))}
      <div ref={endRef} />
    </div>
  )
}
