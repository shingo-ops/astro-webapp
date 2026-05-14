import React from 'react'
import ReactDOM from 'react-dom/client'
import './i18n' // i18next を App より先に初期化する（ADR-027）
import App from './App.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
