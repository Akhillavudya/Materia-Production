// Materia brand mark — "Atomic Node":
// a central atom (electron-orbital ring + nucleus) with four radiating bonds
// ending in lattice nodes. Atom = matter, lattice bonds = materials science.
// Single source of truth for the logo across the whole app.

export function LogoMark({ size = 32, radius = 8, glow = false }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: 'linear-gradient(135deg, #00B4A6 0%, #0EA5E9 100%)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        boxShadow: glow ? '0 8px 24px rgba(0, 180, 166, 0.40)' : 'none',
      }}
    >
      <svg
        width={size * 0.64}
        height={size * 0.64}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        {/* radiating bonds (drawn first, sit under the atom) */}
        <g stroke="#ffffff" strokeWidth="1.6" strokeLinecap="round">
          <line x1="21.2" y1="10.8" x2="24.2" y2="7.8" />
          <line x1="10.8" y1="10.8" x2="7.8"  y2="7.8" />
          <line x1="21.2" y1="21.2" x2="24.2" y2="24.2" />
          <line x1="10.8" y1="21.2" x2="7.8"  y2="24.2" />
        </g>
        {/* lattice nodes at the bond ends */}
        <g fill="#ffffff">
          <circle cx="24.2" cy="7.8"  r="1.7" />
          <circle cx="7.8"  cy="7.8"  r="1.7" />
          <circle cx="24.2" cy="24.2" r="1.7" />
          <circle cx="7.8"  cy="24.2" r="1.7" />
        </g>
        {/* central atom: electron-orbital ring + nucleus */}
        <circle cx="16" cy="16" r="5.6" stroke="#ffffff" strokeWidth="3" />
        <circle cx="16" cy="16" r="2" fill="#ffffff" />
      </svg>
    </span>
  )
}

export default function Logo({ size = 32, radius = 8, wordmark = true, glow = false, color = 'var(--text-primary)' }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.32 }}>
      <LogoMark size={size} radius={radius} glow={glow} />
      {wordmark && (
        <span
          style={{
            fontSize: size * 0.52,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            color,
          }}
        >
          Materia
        </span>
      )}
    </span>
  )
}
