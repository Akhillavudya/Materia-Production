import { useState } from 'react'
import FilePanel       from '../files/FilePanel'
import AsyncJobsPanel  from './AsyncJobsPanel'
import ToolLaunchPanel from './ToolLaunchPanel'


export default function RightPanel({
  sessionId,
  filePanelRefresh,
  jobRefresh,
  onRerun,
  onOpenFile,
}) {
  // which tab is active — 'files' or 'jobs'
  const [activeTab, setActiveTab] = useState('files')
  // bumped when a tool panel launches a job, to refresh the jobs list at once
  const [nebRefresh, setNebRefresh] = useState(0)
  // bumped when the tool panel uploads a structure, to refresh the Files tab
  const [fileRefresh, setFileRefresh] = useState(0)

  return (
    <div style={{
      width: 'var(--panel-width)',
      minWidth: 'var(--panel-width)',
      height: '100vh',
      background: 'var(--bg-panel)',
      borderLeft: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>

      {/* ── tab bar ── */}
      <div style={{
        display: 'flex',
        gap: '6px',
        padding: '12px 14px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-panel)',
        flexShrink: 0,
      }}>
        {['files', 'jobs'].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              padding: '7px 0',
              borderRadius: 'var(--radius-sm)',
              border: activeTab === tab
                ? '1px solid var(--border)'
                : '1px solid transparent',
              background: activeTab === tab ? '#ffffff' : 'transparent',
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
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* ── tab content — only one visible at a time ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'files' ? (
          <FilePanel
            sessionId={sessionId}
            refreshTrigger={filePanelRefresh + fileRefresh}
            onOpenFile={onOpenFile}
          />
        ) : (
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
            <AsyncJobsPanel sessionId={sessionId} refreshSignal={nebRefresh} />
            <div style={{ flex: 1 }} />
            <ToolLaunchPanel
              sessionId={sessionId}
              onLaunched={() => setNebRefresh((n) => n + 1)}
              onUploaded={() => setFileRefresh((n) => n + 1)}
            />
          </div>
        )}
      </div>

    </div>
  )
}