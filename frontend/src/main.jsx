import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { THEME_STORAGE_KEY } from './lib/chatSessions'
import './index.css'

try {
  const t = localStorage.getItem(THEME_STORAGE_KEY)
  document.documentElement.setAttribute(
    'data-theme',
    t === 'light' || t === 'dark' ? t : 'dark',
  )
} catch {
  document.documentElement.setAttribute('data-theme', 'dark')
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
