import { useState, useEffect, useRef } from 'react'
import SUGGESTIONS from './suggestions'

/**
 * Simple fuzzy match: every word the user typed must appear somewhere in
 * the suggestion (case-insensitive, order-independent). This lets
 * "aws spend" match "Show me AWS spend by service for last month".
 */
function fuzzyMatch(query, text) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const lower = text.toLowerCase()
  return words.every((w) => lower.includes(w))
}

export default function Autocomplete({ query, onSelect, visible }) {
  const [selectedIdx, setSelectedIdx] = useState(0)
  const listRef = useRef(null)

  const matches = visible && query.length >= 2
    ? SUGGESTIONS.filter((s) => fuzzyMatch(query, s)).slice(0, 7)
    : []

  // Reset selection when matches change
  useEffect(() => {
    setSelectedIdx(0)
  }, [matches.length, query])

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return
    const item = listRef.current.children[selectedIdx]
    if (item) item.scrollIntoView({ block: 'nearest' })
  }, [selectedIdx])

  if (matches.length === 0) return null

  return (
    <div className="autocomplete-dropdown" ref={listRef} role="listbox">
      {matches.map((suggestion, i) => (
        <button
          key={suggestion}
          type="button"
          role="option"
          aria-selected={i === selectedIdx}
          className={`autocomplete-item ${i === selectedIdx ? 'selected' : ''}`}
          onMouseEnter={() => setSelectedIdx(i)}
          onMouseDown={(e) => {
            e.preventDefault() // keep focus on textarea
            onSelect(suggestion)
          }}
        >
          {highlightMatch(suggestion, query)}
        </button>
      ))}
    </div>
  )
}

function highlightMatch(text, query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return text

  // Build a regex that matches any of the query words
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = text.split(re)

  return parts.map((part, i) => {
    // Odd-indexed parts are the captured matches from split
    if (i % 2 === 1) {
      return <mark key={i} className="autocomplete-highlight">{part}</mark>
    }
    return part
  })
}

export { fuzzyMatch, SUGGESTIONS }
