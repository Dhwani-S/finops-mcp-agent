import { useEffect, useRef } from 'react'
import Message from './Message'
import { EXPLORE_CHIPS } from '../lib/exploreChips'
import './MessageList.css'

const STARTER_PROMPTS = [
  {
    title: 'Where is the most money going?',
    text: 'What are the top 5 GCP services by cost last month?',
    hint: 'Table + chart-style breakdown',
  },
  {
    title: 'Compare cloud providers',
    text: 'Compare Azure vs AWS spend this quarter',
    hint: 'Comparison view',
  },
  {
    title: 'Spot unusual spending',
    text: 'Show me cost anomalies in the last 30 days',
    hint: 'Alert-style summary',
  },
]

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
          <h2 className="empty-heading">Ask like you would in a meeting</h2>
          <p className="empty-lead">
            Ask in your own words — the agent will check what it needs and guide you
            with simple options before pulling any data.
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
        <div className="empty-prompts" role="list" aria-label="Example questions">
          {STARTER_PROMPTS.map((p) => (
            <button
              key={p.title}
              type="button"
              className="prompt-card"
              disabled={suggestionsDisabled}
              onClick={() => onSuggestion?.(p.text)}
            >
              <span className="prompt-card-title">{p.title}</span>
              <span className="prompt-card-text">{p.text}</span>
              <span className="prompt-card-hint">{p.hint}</span>
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
