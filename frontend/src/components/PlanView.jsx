import './PlanView.css'

export default function PlanView({ plan }) {
  if (!plan || !plan.goals || plan.goals.length === 0) return null

  const allDone = plan.goals.every((g) => g.status === 'done')
  const doneCount = plan.goals.filter((g) => g.status === 'done').length

  return (
    <div className={`plan-view ${allDone ? 'plan-view--complete' : ''}`}>
      <div className="plan-header">
        <span className="plan-title">
          {allDone ? 'Plan complete' : 'Plan'}
        </span>
        <span className="plan-counter">
          {doneCount} of {plan.goals.length}
        </span>
      </div>
      <ol className="plan-goals">
        {plan.goals.map((goal, idx) => (
          <li key={goal.id} className={`plan-goal plan-goal--${goal.status}`}>
            <span className="plan-goal-num">
              {goal.status === 'done' ? (
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.15" />
                  <path d="M5 8l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : goal.status === 'running' ? (
                <span className="plan-goal-spinner" />
              ) : goal.status === 'error' ? (
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" fill="currentColor" fillOpacity="0.15" />
                  <path d="M6 6l4 4M10 6l-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              ) : (
                <span className="plan-goal-dot">{idx + 1}</span>
              )}
            </span>
            <span className="plan-goal-text">{goal.text}</span>
          </li>
        ))}
      </ol>
      {!allDone && (
        <div className="plan-progress">
          <div
            className="plan-progress-bar"
            style={{ width: `${(doneCount / plan.goals.length) * 100}%` }}
          />
        </div>
      )}
    </div>
  )
}
