import { useEffect, useState, useRef } from 'react'
import { fetchSessions, downloadSessionTxt, downloadSessionJson } from '../../api'

export default function Sidebar({ activeSessionId, onSelectSession, onNewChat, user, onSignOut }) {
  const [sessions, setSessions] = useState([])
  const [openMenu, setOpenMenu] = useState(null)
  const [now, setNow] = useState(null)
  const menuRef = useRef(null)

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
    <div style={{
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
        {/* logo circle */}
        <div style={{
          width: '32px', height: '32px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '16px', flexShrink: 0,
        }}>
          ⚗
        </div>
        <span style={{
          fontSize: '16px', fontWeight: '600',
          color: 'var(--text-primary)', letterSpacing: '-0.01em',
        }}>
          Materia
        </span>
      </div>

      {/* ── new chat button ── */}
      <div style={{ padding: '0 12px 16px' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%',
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 14px',
            background: '#ffffff',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontSize: '14px', fontWeight: '500',
            cursor: 'pointer', fontFamily: 'var(--font)',
            transition: 'background 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
          onMouseLeave={e => e.currentTarget.style.background = '#ffffff'}
        >
          <span style={{ fontSize: '18px', lineHeight: 1, color: 'var(--text-secondary)' }}>+</span>
          New chat
        </button>
      </div>

      {/* ── recent chats label ── */}
      <div style={{
        padding: '0 20px 8px',
        fontSize: '11px', fontWeight: '600',
        color: 'var(--text-muted)', letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}>
        Recent chats
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
                  background: isActive ? '#ffffff' : 'transparent',
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
                    background: '#ffffff',
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

      {/* ── bottom profile section ── */}
      <div style={{
        padding: '12px 16px',
        borderTop: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: '10px',
        flexShrink: 0,
      }}>
        {/* avatar */}
        <div style={{
          width: '32px', height: '32px', borderRadius: '50%',
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '13px', fontWeight: '600', color: '#fff', flexShrink: 0,
        }}>
          MA
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-primary)' }}>
            {user?.full_name || 'Materia User'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {user?.email}
          </div>
        </div>
        {/* settings icon */}
        <button style={{
          background: 'none', border: 'none',
          color: 'var(--text-muted)', cursor: 'pointer',
          fontSize: '16px', padding: '4px', borderRadius: '6px',
          transition: 'background 0.1s',
          flexShrink: 0,
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
        onMouseLeave={e => e.currentTarget.style.background = 'none'}
        title="Sign out"
        onClick={onSignOut}
        >
          ⎋
        </button>
      </div>

    </div>
  )
}
