import { useState, useRef, useEffect } from 'react'
import './ChatInput.css'

export default function ChatInput({
  onSend,
  onStop,
  isLoading,
}) {
  const [text, setText] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (!isLoading) inputRef.current?.focus()
  }, [isLoading])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (text.trim() && !isLoading) {
      onSend(text)
      setText('')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="chat-input-wrap">
      <form className="chat-input" onSubmit={handleSubmit}>
        <div className="chat-input-field">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="For example: Give me last month's top ten Azure services by cost..."
            rows={1}
            disabled={isLoading}
            aria-label="Your question"
          />
        </div>
        {isLoading ? (
          <button type="button" className="chat-input-btn chat-input-btn--stop" onClick={onStop}>
            <span className="chat-input-btn-icon stop-square" aria-hidden="true" />
            Stop
          </button>
        ) : (
          <button type="submit" className="chat-input-btn chat-input-btn--send" disabled={!text.trim()}>
            Ask
            <span className="chat-input-btn-icon send-arrow" aria-hidden="true" />
          </button>
        )}
      </form>
      <p className="chat-input-hint">
        <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line
      </p>
    </div>
  )
}
