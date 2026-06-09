import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ToastProvider } from './components/wiki/Toast'
import './styles/index.css'

function reportError(type: string, message: string, extra?: Record<string, unknown>) {
  fetch('/api/log/error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, message, url: window.location.href, ...extra }),
  }).catch(() => {})
}

window.addEventListener('error', (event) => {
  reportError('window.error', event.message, {
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    stack: event.error?.stack,
  })
})

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason
  reportError('unhandledrejection', String(reason), {
    stack: reason?.stack,
  })
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
)
