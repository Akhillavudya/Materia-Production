import { useEffect, useState, useRef } from 'react'
import {
  Plus, Search, Box, Wrench, Sun, Moon, Monitor, PanelLeftClose, X,
  Settings, LogOut, ChevronUp, ChevronDown, FileText, FileJson,
  UserRound, HelpCircle,
} from 'lucide-react'
import { fetchSessions, downloadSessionTxt, downloadSessionJson } from '../../api'
import { LogoMark } from '../../components/Logo'

// One clean nav row — Lucide icon + label, subtle hover (Claude-style).
// `icon` is a Lucide component; `active` gives it the selected pill styling.
function NavRow({ icon: Icon, label, onClick, disabled, title, active }) {
  const base = {
    width: '100%', display: 'flex', alignItems: 'center', gap: '10px',
    padding: '9px 12px', minHeight: '40px',
    border: 'none', borderRadius: 'var(--radius-sm)',
    background: active ? 'var(--bg-elevated)' : 'none',
    color: disabled ? 'var(--text-muted)' : active ? 'var(--text-primary)' : 'var(--text-secondary)',
    fontSize: '14px', fontWeight: 500, fontFamily: 'var(--font)',
    cursor: disabled ? 'not-allowed' : 'pointer', textAlign: 'left',
    opacity: disabled ? 0.55 : 1, transition: 'background 0.12s',
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title || label}
      style={base}
      onMouseEnter={e => { if (!disabled && !active) e.currentTarget.style.background = 'var(--hover-bg)' }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'none' }}
    >
      {Icon && (
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '18px', flexShrink: 0 }}>
          <Icon size={17} strokeWidth={1.75} />
        </span>
      )}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}

// Icon for the Theme nav item, reflecting the current preference live.
const THEME_ICON = { light: Sun, dark: Moon, system: Monitor }

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
  onOpenViewer,
  user,
  onSignOut,
  onOpenSettings,
  onOpenProfile,
  onOpenHelp,
  mode = 'system',
  onOpenTheme,
  themeActive = false,
}) {
  const [sessions, setSessions] = useState([])
  const [openMenu, setOpenMenu] = useState(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [now, setNow] = useState(null)
  // centered "Search chats" modal (opened from the nav item)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const menuRef = useRef(null)
  const profileRef = useRef(null)
  const searchInputRef = useRef(null)

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

  // focus the input when the search modal opens; Escape closes it
  useEffect(() => {
    if (!searchOpen) return
    const t = window.setTimeout(() => searchInputRef.current?.focus(), 0)
    const onKey = (e) => { if (e.key === 'Escape') closeSearch() }
    document.addEventListener('keydown', onKey)
    return () => {
      window.clearTimeout(t)
      document.removeEventListener('keydown', onKey)
    }
  }, [searchOpen])

  function closeSearch() {
    setSearchOpen(false)
    setQuery('')
  }

  function pickSearchResult(id) {
    onSelectSession(id)
    closeSearch()
  }

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
          {isMobile ? <X size={20} strokeWidth={1.75} /> : <PanelLeftClose size={18} strokeWidth={1.75} />}
        </button>
      </div>

      {/* ── primary nav (New chat · Visualize · Tools & Jobs · Theme) ── */}
      <div style={{ padding: '0 10px 14px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {/* New chat — prominent */}
        <button
          onClick={onNewChat}
          style={{
            width: '100%',
            display: 'flex', alignItems: 'center', gap: '10px',
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
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '18px', flexShrink: 0 }}>
            <Plus size={17} strokeWidth={2} />
          </span>
          New chat
        </button>

        {/* Search chats — opens the centered search modal */}
        <NavRow
          icon={Search}
          label="Search chats"
          onClick={() => setSearchOpen(true)}
          active={searchOpen}
          title="Search your conversations"
        />

        {/* Visualize — VESTA-style structure viewer */}
        <NavRow
          icon={Box}
          label="Visualize"
          onClick={onOpenViewer}
          title="Open the structure viewer (VESTA-style)"
        />

        {/* Tools & Jobs — manual tool launcher + running jobs */}
        <NavRow
          icon={Wrench}
          label="Manual Tools"
          onClick={onOpenTools}
          disabled={!hasSession}
          title={hasSession ? 'Run a tool · view running jobs' : 'Start a chat to run tools'}
        />

        {/* Theme — opens the dedicated Appearance page; icon tracks the mode */}
        <NavRow
          icon={THEME_ICON[mode] || Monitor}
          label="Theme"
          onClick={onOpenTheme}
          active={themeActive}
          title="Appearance settings"
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
                    { label: 'Export as .txt',  Icon: FileText, action: () => { downloadSessionTxt(session.id); setOpenMenu(null) } },
                    { label: 'Export as .json', Icon: FileJson, action: () => { downloadSessionJson(session.id); setOpenMenu(null) } },
                  ].map(item => (
                    <button
                      key={item.label}
                      onClick={item.action}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
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
                      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '15px', flexShrink: 0 }}>
                        <item.Icon size={14} strokeWidth={1.75} />
                      </span>
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
          <span style={{ display: 'flex', alignItems: 'center', color: 'var(--text-muted)', flexShrink: 0 }}>
            {profileOpen
              ? <ChevronDown size={16} strokeWidth={1.75} />
              : <ChevronUp size={16} strokeWidth={1.75} />}
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
              { label: 'Profile', Icon: UserRound, action: () => { setProfileOpen(false); onOpenProfile?.() } },
              { label: 'Settings', Icon: Settings, action: () => { setProfileOpen(false); onOpenSettings() } },
              { label: 'Help', Icon: HelpCircle, action: () => { setProfileOpen(false); onOpenHelp?.() } },
              { label: 'Log out', Icon: LogOut, action: () => { setProfileOpen(false); onSignOut() }, danger: true },
            ].map(item => (
              <button
                key={item.label}
                onClick={item.action}
                style={{
                  display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
                  padding: '9px 11px', textAlign: 'left', background: 'none', border: 'none',
                  borderRadius: 'var(--radius-sm)', fontSize: '13px',
                  color: item.danger ? 'var(--danger-fg)' : 'var(--text-secondary)',
                  cursor: 'pointer', fontFamily: 'var(--font)', transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '16px', flexShrink: 0 }}>
                  <item.Icon size={15} strokeWidth={1.75} />
                </span>
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── centered "Search chats" modal ── */}
      {searchOpen && (
        <div
          onMouseDown={closeSearch}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(26,26,26,0.38)',
            backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            padding: '14vh 16px 16px',
          }}
        >
          <div
            onMouseDown={e => e.stopPropagation()}
            style={{
              width: '420px', maxWidth: '94vw', maxHeight: '70vh',
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
              background: 'var(--bg-chat)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', boxShadow: '0 24px 70px rgba(0,0,0,0.22)',
              fontFamily: 'var(--font)',
            }}
          >
            {/* search input */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '10px',
              padding: '12px 14px', borderBottom: '1px solid var(--border-light)',
            }}>
              <Search size={17} strokeWidth={1.75} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
              <input
                ref={searchInputRef}
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search chats..."
                style={{
                  flex: 1, border: 'none', outline: 'none', background: 'transparent',
                  fontSize: '14px', color: 'var(--text-primary)', fontFamily: 'var(--font)',
                }}
              />
              <button
                onClick={closeSearch}
                aria-label="Close search"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: 'none', border: 'none', color: 'var(--text-muted)',
                  cursor: 'pointer', padding: '4px', borderRadius: 'var(--radius-sm)', lineHeight: 1,
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                <X size={16} strokeWidth={1.75} />
              </button>
            </div>

            {/* results */}
            <div style={{ overflowY: 'auto', padding: '6px' }}>
              {(() => {
                const q = query.trim().toLowerCase()
                const results = q
                  ? sessions.filter(s => (s.title || 'Untitled').toLowerCase().includes(q))
                  : sessions
                if (results.length === 0) {
                  return (
                    <div style={{ padding: '24px 16px', textAlign: 'center', fontSize: '13px', color: 'var(--text-muted)' }}>
                      {q ? 'No matching chats' : 'No conversations yet'}
                    </div>
                  )
                }
                return results.map(s => (
                  <button
                    key={s.id}
                    onClick={() => pickSearchResult(s.id)}
                    style={{
                      display: 'flex', flexDirection: 'column', gap: '2px', width: '100%',
                      padding: '9px 12px', textAlign: 'left', background: 'none', border: 'none',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontFamily: 'var(--font)',
                      transition: 'background 0.1s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'none'}
                  >
                    <span style={{
                      fontSize: '13.5px', color: 'var(--text-primary)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', width: '100%',
                    }}>
                      {s.title || 'Untitled'}
                    </span>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {timeAgo(s.created_at)}
                    </span>
                  </button>
                ))
              })()}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
