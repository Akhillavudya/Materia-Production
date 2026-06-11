const TOOL_LABELS = {
  generate_vasp_poscar:                          'Fetching structure from Materials Project',
  generate_vasp_poscar_with_vacancy_defects:     'Generating vacancy defects',
  generate_vasp_poscar_with_substitution_defects:'Generating substitution defects',
  generate_supercell_from_poscar:                'Building supercell',
  generate_surface_slab_from_poscar:             'Creating surface slab',
  customize_vasp_kpoints_with_accuracy:          'Generating KPOINTS',
  generate_vasp_inputs_from_poscar:              'Preparing VASP input files',
  generate_vasp_workflow_of_eos:                 'Building EOS workflow',
  run_simulation_using_mlps:                     'Running MLP simulation',
  visualize_structure_from_poscar:               'Rendering structure',
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
