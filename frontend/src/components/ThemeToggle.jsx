import './ThemeToggle.css'

export default function ThemeToggle({ theme, onChange }) {
  const isLight = theme === 'light'
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => onChange(isLight ? 'dark' : 'light')}
      title={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
      aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
    >
      {isLight ? (
        <span className="theme-toggle-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      ) : (
        <span className="theme-toggle-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" strokeLinecap="round" />
          </svg>
        </span>
      )}
      <span className="theme-toggle-label">{isLight ? 'Dark' : 'Light'}</span>
    </button>
  )
}
