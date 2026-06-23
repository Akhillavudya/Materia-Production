import { useEffect, useState, useRef } from 'react'
import { fetchSessions, downloadSessionTxt, downloadSessionJson } from '../../api'
import { LogoMark } from '../../components/Logo'

// One clean nav row — icon + label, subtle hover (Claude-style).
function NavRow({ icon, label, onClick, disabled, title }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title || label}
      style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: '11px',
        padding: '9px 12px', minHeight: '40px',
        background: 'none', border: 'none', borderRadius: 'var(--radius-sm)',
        color: disabled ? 'var(--text-muted)' : 'var(--text-secondary)',
        fontSize: '14px', fontWeight: 500, fontFamily: 'var(--font)',
        cursor: disabled ? 'not-allowed' : 'pointer', textAlign: 'left',
        opacity: disabled ? 0.55 : 1, transition: 'background 0.12s',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = 'var(--hover-bg)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'none' }}
    >
      <span style={{ fontSize: '16px', width: '18px', textAlign: 'center', flexShrink: 0 }}>{icon}</span>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}

export default function Sidebar({
  className,
  isMobile = false,
  onClose,
  onCollapse,
  hasSession = false,
  onOpenTools,
  activeSessionId,
  onSelectSession,
  onNewChat,
  user,
  onSignOut,
  onOpenSettings,
  theme = 'light',
  onToggleTheme,
}) {
  const [sessions, setSessions] = useState([])
  const [openMenu, setOpenMenu] = useState(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [now, setNow] = useState(null)
  const menuRef = useRef(null)
  const profileRef = useRef(null)

  // reload whenever the active session changes
  // (catches newly created sessions)
  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {})
  }, [activeSessionId])

  useEffect(() => {
    const updateNow = () => setNow(Date.now())
    const initialTimer = window.setTimeout(updateNow, 0)
    const intervalTimer = window.setInterval(updateNow, 60000)
    return () => {
      window.clearTimeout(initialTimer)
      window.clearInterval(intervalTimer)
    }
  }, [])

  // close dropdown when clicking outside it
  useEffect(() => {
    if (!openMenu) return
    function handle(e) {
      if (menuRef.current && !menuRef.current.contains(e.target))
        setOpenMenu(null)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [openMenu])

  // close the profile menu when clicking outside it
  useEffect(() => {
    if (!profileOpen) return
    function handle(e) {
      if (profileRef.current && !profileRef.current.contains(e.target))
        setProfileOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [profileOpen])

  // format timestamp as "2m ago", "1h ago", "Yesterday" etc
  function timeAgo(iso) {
    if (!iso || !now) return ''
    const diff = now - new Date(iso).getTime()
    const m = Math.floor(diff / 60000)
    if (m < 1)   return 'just now'
    if (m < 60)  return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24)  return `${h}h ago`
    const d = Math.floor(h / 24)
    if (d === 1) return 'Yesterday'
    if (d < 7)   return `${d} days ago`
    return new Date(iso).toLocaleDateString()
  }

  return (
    <div className={className} style={{
      width: 'var(--sidebar-width)',
      minWidth: 'var(--sidebar-width)',
      height: '100vh',
      background: 'var(--bg-sidebar)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>

      {/* ── brand ── */}
      <div style={{
        padding: '20px 20px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
      }}>
        {/* logo mark */}
        <LogoMark size={32} radius={8} />
        <span style={{
          fontSize: '16px', fontWeight: '600',
          color: 'var(--text-primary)', letterSpacing: '-0.01em',
        }}>
          Materia
        </span>

        {/* collapse (desktop) / close drawer (mobile) — the "disappear" control */}
        <button
          onClick={isMobile ? onClose : onCollapse}
          aria-label={isMobile ? 'Close menu' : 'Hide sidebar'}
          title={isMobile ? 'Close' : 'Hide sidebar'}
          style={{
            marginLeft: 'auto', width: '38px', height: '38px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'none', border: 'none', borderRadius: 'var(--radius-sm)',
            color: 'var(--text-secondary)', fontSize: isMobile ? '20px' : '18px',
            cursor: 'pointer', lineHeight: 1, transition: 'background 0.12s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
          onMouseLeave={e => e.currentTarget.style.background = 'none'}
        >
          {isMobile ? '✕' : '«'}
        </button>
      </div>

      {/* ── primary nav (New chat · Tools & Jobs · Theme) ── */}
      <div style={{ padding: '0 10px 14px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {/* New chat — prominent */}
        <button
          onClick={onNewChat}
          style={{
            width: '100%',
            display: 'flex', alignItems: 'center', gap: '11px',
            padding: '10px 12px', minHeight: '44px',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontSize: '14px', fontWeight: '600',
            cursor: 'pointer', fontFamily: 'var(--font)',
            marginBottom: '4px', transition: 'background 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
          onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
        >
          <span style={{ fontSize: '17px', width: '18px', textAlign: 'center', lineHeight: 1, color: 'var(--text-secondary)' }}>✎</span>
          New chat
        </button>

        {/* Tools & Jobs — manual tool launcher + running jobs */}
        <NavRow
          icon="🛠"
          label="Tools & Jobs"
          onClick={onOpenTools}
          disabled={!hasSession}
          title={hasSession ? 'Run a tool · view running jobs' : 'Start a chat to run tools'}
        />

        {/* Theme */}
        <NavRow
          icon={theme === 'dark' ? '☀' : '🌙'}
          label={theme === 'dark' ? 'Light mode' : 'Dark mode'}
          onClick={onToggleTheme}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        />
      </div>

      {/* ── recents label ── */}
      <div style={{
        padding: '0 20px 8px',
        fontSize: '11px', fontWeight: '600',
        color: 'var(--text-muted)', letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}>
        Recents
      </div>

      {/* ── session list ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        {sessions.length === 0 && (
          <div style={{
            padding: '20px', fontSize: '13px',
            color: 'var(--text-muted)', textAlign: 'center',
          }}>
            No conversations yet
          </div>
        )}

        {sessions.map(session => {
          const isActive = session.id === activeSessionId
          const menuOpen = openMenu === session.id

          return (
            <div
              key={session.id}
              style={{ position: 'relative', marginBottom: '2px' }}
              onMouseEnter={e => {
                const btn = e.currentTarget.querySelector('.menu-btn')
                if (btn) btn.style.opacity = '1'
              }}
              onMouseLeave={e => {
                if (menuOpen) return
                const btn = e.currentTarget.querySelector('.menu-btn')
                if (btn) btn.style.opacity = '0'
              }}
            >
              {/* session row */}
              <div
                onClick={() => onSelectSession(session.id)}
                style={{
                  padding: '9px 12px',
                  borderRadius: 'var(--radius-sm)',
                  background: isActive ? 'var(--bg-elevated)' : 'transparent',
                  border: isActive
                    ? '1px solid var(--border)'
                    : '1px solid transparent',
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                  paddingRight: '32px',
                  animation: 'fadeInUp 0.15s ease',
                }}
                onMouseEnter={e => {
                  if (!isActive) e.currentTarget.style.background = 'var(--hover-bg)'
                }}
                onMouseLeave={e => {
                  if (!isActive) e.currentTarget.style.background = 'transparent'
                }}
              >
                {/* session title */}
                <div style={{
                  fontSize: '13px',
                  fontWeight: isActive ? '500' : '400',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  marginBottom: '2px',
                }}>
                  {session.title || 'Untitled'}
                </div>
                {/* timestamp */}
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {timeAgo(session.created_at)}
                </div>
              </div>

              {/* ⋯ menu trigger */}
              <button
                className="menu-btn"
                onClick={e => {
                  e.stopPropagation()
                  setOpenMenu(menuOpen ? null : session.id)
                }}
                style={{
                  position: 'absolute', right: '6px', top: '50%',
                  transform: 'translateY(-50%)',
                  opacity: menuOpen ? '1' : '0',
                  background: 'none', border: 'none',
                  color: 'var(--text-muted)', fontSize: '16px',
                  cursor: 'pointer', padding: '4px 6px',
                  borderRadius: '6px', lineHeight: 1,
                  transition: 'opacity 0.1s, background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--border)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                ···
              </button>

              {/* dropdown menu */}
              {menuOpen && (
                <div
                  ref={menuRef}
                  style={{
                    position: 'absolute', right: 0, top: '100%',
                    background: 'var(--bg-elevated)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '4px',
                    zIndex: 100,
                    minWidth: '170px',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
                  }}
                >
                  {[
                    { label: '📄 Export as .txt',  action: () => { downloadSessionTxt(session.id); setOpenMenu(null) } },
                    { label: '{ } Export as .json', action: () => { downloadSessionJson(session.id); setOpenMenu(null) } },
                  ].map(item => (
                    <button
                      key={item.label}
                      onClick={item.action}
                      style={{
                        display: 'block', width: '100%',
                        padding: '8px 12px', textAlign: 'left',
                        background: 'none', border: 'none',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '13px', color: 'var(--text-secondary)',
                        cursor: 'pointer', fontFamily: 'var(--font)',
                        transition: 'background 0.1s',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'none'}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── bottom profile section (click → Claude-style menu) ── */}
      <div ref={profileRef} style={{ position: 'relative', padding: '12px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
        <button
          onClick={() => setProfileOpen(o => !o)}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: '10px',
            padding: '6px 8px', background: profileOpen ? 'var(--hover-bg)' : 'none',
            border: 'none', borderRadius: 'var(--radius-md)', cursor: 'pointer',
            fontFamily: 'var(--font)', textAlign: 'left', transition: 'background 0.12s',
          }}
          onMouseEnter={e => { if (!profileOpen) e.currentTarget.style.background = 'var(--hover-bg)' }}
          onMouseLeave={e => { if (!profileOpen) e.currentTarget.style.background = 'none' }}
        >
          <div style={{
            width: '32px', height: '32px', borderRadius: '50%',
            background: 'linear-gradient(135deg, #00b4a6, #0ea5e9)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '13px', fontWeight: '600', color: '#fff', flexShrink: 0,
          }}>
            {(user?.full_name || user?.email || 'M').trim().charAt(0).toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.full_name || 'Materia User'}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.email}
            </div>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)', flexShrink: 0 }}>
            {profileOpen ? '▾' : '▴'}
          </span>
        </button>

        {/* dropdown — opens upward, above the profile row */}
        {profileOpen && (
          <div style={{
            position: 'absolute', bottom: 'calc(100% - 4px)', left: '12px', right: '12px',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', padding: '4px', zIndex: 200,
            boxShadow: '0 6px 24px rgba(0,0,0,0.12)',
          }}>
            {[
              { label: 'Settings', icon: '⚙', action: () => { setProfileOpen(false); onOpenSettings() } },
              { label: 'Log out', icon: '⎋', action: () => { setProfileOpen(false); onSignOut() }, danger: true },
            ].map(item => (
              <button
                key={item.label}
                onClick={item.action}
                style={{
                  display: 'flex', alignItems: 'center', gap: '9px', width: '100%',
                  padding: '9px 11px', textAlign: 'left', background: 'none', border: 'none',
                  borderRadius: 'var(--radius-sm)', fontSize: '13px',
                  color: item.danger ? '#b42318' : 'var(--text-secondary)',
                  cursor: 'pointer', fontFamily: 'var(--font)', transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                <span style={{ fontSize: '14px', width: '16px', textAlign: 'center' }}>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>

    </div>
  )
}
