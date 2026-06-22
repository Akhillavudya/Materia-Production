// Friendly labels for the current agent tools (kept in sync with tool_registry.py).
const TOOL_LABELS = {
  search_materials:     'Searching material databases',
  generate_vasp_inputs: 'Generating VASP inputs',
  generate_poscar:      'Generating POSCAR',
  make_supercell:       'Building supercell',
  add_vacuum:           'Adding vacuum',
  make_slab:            'Building surface slab',
  convert_structure:    'Converting structure format',
  analyze_symmetry:     'Analyzing symmetry',
  create_vacancy:       'Creating vacancy defect',
  create_substitution:  'Creating substitution defect',
  create_interstitial:  'Creating interstitial defect',
  read_file:            'Reading file',
  list_files:           'Listing session files',
  list_models:          'Listing models',
  optimize_structure:   'Optimizing structure',
  run_md_simulation:    'Running MD simulation',
}

// inject spin keyframe once
if (!document.getElementById('ts-spin')) {
  const st = document.createElement('style')
  st.id = 'ts-spin'
  st.textContent = `@keyframes ts-spin { to { transform: rotate(360deg) } }`
  document.head.appendChild(st)
}

export default function ToolStatus({ toolName, status }) {
  if (!toolName) return null

  const label = TOOL_LABELS[toolName] || toolName.replace(/_/g, ' ')

  // color config per status
  const cfg = {
    running: { bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
    success: { bg: '#ecfdf3', color: '#166534', border: '#bbf7d0' },
    error:   { bg: '#fef2f2', color: '#b91c1c', border: '#fecaca' },
    canceled:{ bg: '#f8fafc', color: '#64748b', border: '#e2e8f0' },
  }[status] || { bg: '#f8fafc', color: '#64748b', border: '#e2e8f0' }

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '8px',
      marginTop: '10px',
      padding: '8px 14px',
      background: cfg.bg,
      border: `1px solid ${cfg.border}`,
      borderRadius: '20px',
      maxWidth: '100%',
    }}>
      {/* spinner or icon */}
      {status === 'running' ? (
        <div style={{
          width: '13px', height: '13px',
          border: `2px solid ${cfg.border}`,
          borderTop: `2px solid ${cfg.color}`,
          borderRadius: '50%',
          flexShrink: 0,
          animation: 'ts-spin 0.8s linear infinite',
        }} />
      ) : (
        <span style={{ fontSize: '13px', flexShrink: 0 }}>
          {status === 'success' ? '✓' : status === 'canceled' ? '■' : '✗'}
        </span>
      )}

      <div>
        <div style={{
          fontSize: '13px', fontWeight: '500',
          color: cfg.color, lineHeight: '1.3',
        }}>
          {status === 'running' ? label + '…' : status === 'canceled' ? label + ' stopped' : label}
        </div>
        <div style={{
          fontSize: '11px',
          color: cfg.color,
          opacity: 0.7,
          fontFamily: 'monospace',
        }}>
          {toolName}()
        </div>
      </div>
    </div>
  )
}
