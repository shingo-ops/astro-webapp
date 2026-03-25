import { useEffect, useState } from 'react'
import './App.css'

interface HealthStatus {
  status: string
  database: string
}

function App() {
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch('/api/health')
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        const data = await response.json()
        setHealthStatus(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setLoading(false)
      }
    }

    checkHealth()
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Jarvis CRM</h1>
        <p className="subtitle">Multi-tenant B2B SaaS CRM Platform</p>
      </header>

      <main className="app-main">
        <div className="status-card">
          <h2>API接続状態</h2>
          {loading && <p className="loading">接続確認中...</p>}
          {error && (
            <div className="error">
              <p>エラー: {error}</p>
            </div>
          )}
          {healthStatus && (
            <div className="success">
              <p>
                <strong>ステータス:</strong> {healthStatus.status}
              </p>
              <p>
                <strong>データベース:</strong> {healthStatus.database}
              </p>
            </div>
          )}
        </div>

        <div className="info-card">
          <h2>システム情報</h2>
          <ul>
            <li>フロントエンド: React 18 + TypeScript + Vite</li>
            <li>バックエンド: FastAPI + Python 3.12</li>
            <li>データベース: PostgreSQL 16</li>
            <li>インフラ: Docker Compose + Nginx + SSL</li>
          </ul>
        </div>
      </main>

      <footer className="app-footer">
        <p>&copy; 2026 Jarvis CRM - Powered by Claude Code</p>
      </footer>
    </div>
  )
}

export default App
