import { useEffect, useState } from 'react'
import Sidebar from './features/sessions/Sidebar'
import Chat from './features/chat/Chat'
import RightPanel from './features/sessions/RightPanel'
import AuthScreen from './features/auth/AuthScreen'
import Landing from './features/landing/Landing'
import SettingsPanel from './features/settings/SettingsPanel'
import FileViewer from './features/files/FileViewer'
import { useIsMobile, useBodyScrollLock, useTheme } from './hooks/ui'
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

  // ── responsive + theme ──
  const isMobile = useIsMobile()
  const { theme, toggleTheme } = useTheme()
  // mobile-only: sidebar drawer + files bottom-sheet open state
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  // desktop-only: collapse (hide) the sidebar, Claude-style
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  // which right-panel tab is showing — lifted so the sidebar can jump to Tools
  const [rightTab, setRightTab] = useState('files')

  // lock background scroll while an overlay is up on mobile
  useBodyScrollLock(isMobile && (drawerOpen || panelOpen || !!viewingFile))

  // collapse mobile overlays when we drop back to desktop width
  useEffect(() => {
    if (!isMobile) { setDrawerOpen(false); setPanelOpen(false) }
  }, [isMobile])

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
    setDrawerOpen(false)
    if (id === activeSessionId) return
    setFilePanelRefresh(0)
    setJobRefresh(0)
    setPanelOpen(false)
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
    setDrawerOpen(false)
    setPanelOpen(false)
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

  // A manual tool run (right panel) persisted an "action" message — reload the
  // chat history so it appears in the timeline, and refresh files/jobs.
  async function handleManualRun() {
    if (!activeSessionId) return
    setFilePanelRefresh(p => p + 1)
    setJobRefresh(p => p + 1)
    try {
      const msgs = await fetchMessages(activeSessionId)
      setLoadedMessages(msgs)
    } catch {
      /* keep current messages on a transient fetch error */
    }
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

  // on desktop the focused file view hides the sidebar; on mobile the sidebar is
  // an off-canvas drawer that simply stays behind the full-screen viewer.
  const showSidebar = isMobile || (!viewingFile && !sidebarCollapsed)

  function openFile(relPath, fileName) {
    setViewingFile({ relPath, fileName })
    setPanelOpen(false)
  }

  // open the menu: drawer on mobile, un-collapse on desktop
  function handleOpenSidebar() {
    if (isMobile) setDrawerOpen(true)
    else setSidebarCollapsed(false)
  }

  // jump straight to the manual Tools panel (the launcher; Jobs is its own tab)
  function handleOpenTools() {
    setRightTab('tools')
    setDrawerOpen(false)
    if (isMobile) setPanelOpen(true)
  }

  return (
    <div className="app-shell">
      {showSidebar && (
        <Sidebar
          className={`app-sidebar${drawerOpen ? ' is-open' : ''}`}
          isMobile={isMobile}
          onClose={() => setDrawerOpen(false)}
          onCollapse={() => setSidebarCollapsed(true)}
          hasSession={!!activeSessionId}
          onOpenTools={handleOpenTools}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          user={user}
          onSignOut={handleSignOut}
          onOpenSettings={() => { setShowSettings(true); setDrawerOpen(false) }}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}

      {/* drawer backdrop (mobile only) */}
      {isMobile && (
        <div
          className={`app-backdrop${drawerOpen ? ' is-open' : ''}`}
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <Chat
        className="app-chat"
        sessionId={activeSessionId}
        userName={user?.full_name || user?.email}
        initialMessages={loadedMessages}
        onSessionCreated={handleSessionCreated}
        onFilesGenerated={handleFilesGenerated}
        onJobDone={handleJobDone}
        rerunMessage={rerunMessage}
        onRerunConsumed={handleRerunConsumed}
        isMobile={isMobile}
        hasSession={!!activeSessionId}
        showMenuButton={isMobile || sidebarCollapsed}
        onOpenSidebar={handleOpenSidebar}
        onOpenFiles={() => setPanelOpen(true)}
        onOpenFile={openFile}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      {viewingFile ? (
        <FileViewer
          className="app-fileviewer"
          isMobile={isMobile}
          relPath={viewingFile.relPath}
          fileName={viewingFile.fileName}
          onClose={() => setViewingFile(null)}
        />
      ) : activeSessionId ? (
        // desktop: always-visible column. mobile: bottom-sheet toggled by panelOpen
        // (kept mounted so it can slide in/out smoothly).
        <RightPanel
          className={`app-rightpanel${isMobile && panelOpen ? ' is-open' : ''}`}
          isMobile={isMobile}
          onClose={() => setPanelOpen(false)}
          activeTab={rightTab}
          onTabChange={setRightTab}
          sessionId={activeSessionId}
          filePanelRefresh={filePanelRefresh}
          jobRefresh={jobRefresh}
          onRerun={handleRerun}
          onManualRun={handleManualRun}
          onOpenFile={openFile}
        />
      ) : null}

      {showSettings && (
        <SettingsPanel onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}

