import { useEffect, useState } from 'react'
import Sidebar from './features/sessions/Sidebar'
import Chat from './features/chat/Chat'
import RightPanel from './features/sessions/RightPanel'
import AuthScreen from './features/auth/AuthScreen'
import Landing from './features/landing/Landing'
import SettingsPanel from './features/settings/SettingsPanel'
import FileViewer from './features/files/FileViewer'
import { fetchMessages, getAuthToken, getMe, getStoredUser, logout } from './api'

export default function App() {
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [loadedMessages, setLoadedMessages] = useState([])
  const [filePanelRefresh, setFilePanelRefresh] = useState(0)
  const [jobRefresh, setJobRefresh] = useState(0)
  const [rerunMessage, setRerunMessage] = useState(null)
  const [user, setUser] = useState(() => getStoredUser())
  const [authChecked, setAuthChecked] = useState(() => !getAuthToken())
  const [authMessage, setAuthMessage] = useState(null)
  // logged-out view: 'landing' (marketing page) or 'auth' (sign in / sign up)
  const [authView, setAuthView] = useState('landing')
  const [showSettings, setShowSettings] = useState(false)
  // when set, a file is open full-width: { relPath, fileName }. Sidebar + right
  // panel hide so the viewer sits beside the chat (Claude-style focused view).
  const [viewingFile, setViewingFile] = useState(null)

  useEffect(() => {
    if (!getAuthToken()) return

    getMe()
      .then(nextUser => {
        setUser(nextUser)
        setAuthMessage(null)
      })
      .catch(() => {
        logout()
        setUser(null)
        setAuthMessage('Session expired. Please log in again.')
      })
      .finally(() => setAuthChecked(true))
  }, [])


  useEffect(() => {
    function handleAuthExpired(event) {
      logout()
      setUser(null)
      setAuthChecked(true)
      setAuthView('auth')
      setAuthMessage(event.detail?.message || 'Session expired. Please log in again.')
      handleNewChat()
    }

    window.addEventListener('materia-auth-expired', handleAuthExpired)
    return () => window.removeEventListener('materia-auth-expired', handleAuthExpired)
  }, [])

  async function handleSelectSession(id) {
    if (id === activeSessionId) return
    setFilePanelRefresh(0)
    setJobRefresh(0)
    try {
      const msgs = await fetchMessages(id)
      setLoadedMessages(msgs)
    } catch {
      setLoadedMessages([])
    }
    setActiveSessionId(id)
  }

  function handleNewChat() {
    setActiveSessionId(null)
    setLoadedMessages([])
    setFilePanelRefresh(0)
    setJobRefresh(0)
    setRerunMessage(null)
  }

  function handleSessionCreated(id) {
    setActiveSessionId(id)
  }

  function handleFilesGenerated() {
    setFilePanelRefresh(p => p + 1)
  }

  function handleJobDone() {
    setJobRefresh(p => p + 1)
  }

  function handleRerun(msg) {
    setRerunMessage(msg)
  }

  function handleRerunConsumed() {
    setRerunMessage(null)
  }

  function handleAuthenticated(nextUser) {
    setUser(nextUser)
    setAuthMessage(null)
    setAuthView('landing')
  }

  function handleSignOut() {
    logout()
    setUser(null)
    setAuthMessage(null)
    setAuthView('landing')
    handleNewChat()
  }

  if (!authChecked) {
    return null
  }

  if (!user) {
    if (authView === 'auth') {
      return (
        <AuthScreen
          onAuthenticated={handleAuthenticated}
          initialError={authMessage}
          onBack={() => { setAuthMessage(null); setAuthView('landing') }}
        />
      )
    }
    return (
      <Landing
        onGetStarted={() => setAuthView('auth')}
        onLogin={() => setAuthView('auth')}
      />
    )
  }

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg-page)',
    }}>
      {!viewingFile && (
        <Sidebar
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          user={user}
          onSignOut={handleSignOut}
          onOpenSettings={() => setShowSettings(true)}
        />
      )}

      <Chat
        sessionId={activeSessionId}
        userName={user?.full_name || user?.email}
        initialMessages={loadedMessages}
        onSessionCreated={handleSessionCreated}
        onFilesGenerated={handleFilesGenerated}
        onJobDone={handleJobDone}
        rerunMessage={rerunMessage}
        onRerunConsumed={handleRerunConsumed}
      />

      {viewingFile ? (
        <FileViewer
          relPath={viewingFile.relPath}
          fileName={viewingFile.fileName}
          onClose={() => setViewingFile(null)}
        />
      ) : activeSessionId ? (
        <RightPanel
          sessionId={activeSessionId}
          filePanelRefresh={filePanelRefresh}
          jobRefresh={jobRefresh}
          onRerun={handleRerun}
          onOpenFile={(relPath, fileName) => setViewingFile({ relPath, fileName })}
        />
      ) : null}

      {showSettings && (
        <SettingsPanel onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}

