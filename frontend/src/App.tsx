import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api, type AppConfig } from './lib/api'
import { ToastProvider } from './lib/useToast'
import ProjectsPage from './pages/Projects'
import EditorPage from './pages/Editor'
import SettingsPage from './pages/Settings'

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const loc = useLocation()

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null))
  }, [])

  return (
    <ToastProvider>
      <div className="app">
        <header className="topbar">
          <Link to="/projects" className="brand" style={{ color: 'inherit' }}>
            Dubbing<span>Studio</span>
          </Link>
          <span className="badge">EN ⇄ MY</span>
          <span className="spacer" />
          {config?.mock_mode && <span className="badge warn">mock workers</span>}
          <span className={`badge ${config?.secrets.gemini_api_key_configured ? 'ok' : ''}`}>
            Gemini key: {config?.secrets.gemini_api_key_configured ? 'in Secrets Manager' : 'not set'}
          </span>
          <span className="badge">storage: {config?.storage ?? '…'}</span>
          <Link to="/settings">
            <button className="ghost sm" data-active={loc.pathname === '/settings'}>
              Providers
            </button>
          </Link>
        </header>
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<EditorPage config={config} />} />
          <Route path="/settings" element={<SettingsPage config={config} />} />
        </Routes>
      </div>
    </ToastProvider>
  )
}
