import { useState } from 'react'
import FilePanel       from '../files/FilePanel'
import AsyncJobsPanel  from './AsyncJobsPanel'
import ToolLaunchPanel from './ToolLaunchPanel'


export default function RightPanel({
  className,
  isMobile = false,
  onClose,
  activeTab: controlledTab,
  onTabChange,
  sessionId,
  filePanelRefresh,
  jobRefresh,
  onRerun,
  onManualRun,
  onOpenFile,
}) {
  // which tab is active — 'files' | 'tools' | 'jobs'. Controlled by App when
  // provided so the sidebar's "Tools & Jobs" entry can jump straight here.
  const [internalTab, setInternalTab] = useState('files')
  const activeTab = controlledTab ?? internalTab
  const setActiveTab = onTabChange ?? setInternalTab
  // bumped when a tool panel launches a job, to refresh the jobs list at once
  const [nebRefresh, setNebRefresh] = useState(0)
  // bumped when the tool panel uploads a structure, to refresh the Files tab
  const [fileRefresh, setFileRefresh] = useState(0)

  return (
    <div className={className} style={{
      width: 'var(--panel-width)',
      minWidth: 'var(--panel-width)',
      height: '100vh',
      background: 'var(--bg-panel)',
      borderLeft: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>

      {/* ── mobile sheet header (title + close) ── */}
      {isMobile && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 14px', borderBottom: '1px solid var(--border)', flexShrink: 0,
        }}>
          <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
            Files &amp; outputs
          </span>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: '40px', height: '40px', display: 'flex', alignItems: 'center',
              justifyContent: 'center', background: 'none', border: 'none',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
              fontSize: '20px', cursor: 'pointer', lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── tab bar ── */}
      <div style={{
        display: 'flex',
        gap: '6px',
        padding: '12px 14px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-panel)',
        flexShrink: 0,
      }}>
        {[['files', 'Files'], ['tools', 'Tools'], ['jobs', 'Jobs']].map(([tab, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              padding: isMobile ? '11px 0' : '7px 0',
              borderRadius: 'var(--radius-sm)',
              border: activeTab === tab
                ? '1px solid var(--border)'
                : '1px solid transparent',
              background: activeTab === tab ? 'var(--bg-elevated)' : 'transparent',
              color: activeTab === tab
                ? 'var(--text-primary)'
                : 'var(--text-muted)',
              fontSize: '13px',
              fontWeight: activeTab === tab ? '500' : '400',
              cursor: 'pointer',
              fontFamily: 'var(--font)',
              transition: 'all 0.15s ease',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── tab content — only one panel visible at a time ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'files' && (
          <FilePanel
            sessionId={sessionId}
            refreshTrigger={filePanelRefresh + fileRefresh}
            onOpenFile={onOpenFile}
          />
        )}

        {/* Manual tools — laid out from the top, scrolls on overflow. */}
        {activeTab === 'tools' && (
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <ToolLaunchPanel
              sessionId={sessionId}
              onLaunched={() => { setNebRefresh((n) => n + 1); setActiveTab('jobs') }}
              onManualRun={() => { setNebRefresh((n) => n + 1); setFileRefresh((n) => n + 1); onManualRun?.() }}
              onUploaded={() => setFileRefresh((n) => n + 1)}
            />
          </div>
        )}

        {/* Live jobs — own panel, polls and shows progress. */}
        {activeTab === 'jobs' && (
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <AsyncJobsPanel sessionId={sessionId} refreshSignal={nebRefresh} />
          </div>
        )}
      </div>

    </div>
  )
}