// // Materia brand mark — "Atomic Node":
// // a central atom (electron-orbital ring + nucleus) with four radiating bonds
// // ending in lattice nodes. Atom = matter, lattice bonds = materials science.
// // Single source of truth for the logo across the whole app.

// export function LogoMark({ size = 32, radius = 8, glow = false }) {
//   return (
//     <span
//       style={{
//         width: size,
//         height: size,
//         borderRadius: radius,
//         background: 'linear-gradient(135deg, #00B4A6 0%, #0EA5E9 100%)',
//         display: 'inline-flex',
//         alignItems: 'center',
//         justifyContent: 'center',
//         flexShrink: 0,
//         boxShadow: glow ? '0 8px 24px rgba(0, 180, 166, 0.40)' : 'none',
//       }}
//     >
//       <svg
//         width={size * 0.64}
//         height={size * 0.64}
//         viewBox="0 0 32 32"
//         fill="none"
//         xmlns="http://www.w3.org/2000/svg"
//         aria-hidden="true"
//       >
//         {/* radiating bonds (drawn first, sit under the atom) */}
//         <g stroke="#ffffff" strokeWidth="1.6" strokeLinecap="round">
//           <line x1="21.2" y1="10.8" x2="24.2" y2="7.8" />
//           <line x1="10.8" y1="10.8" x2="7.8"  y2="7.8" />
//           <line x1="21.2" y1="21.2" x2="24.2" y2="24.2" />
//           <line x1="10.8" y1="21.2" x2="7.8"  y2="24.2" />
//         </g>
//         {/* lattice nodes at the bond ends */}
//         <g fill="#ffffff">
//           <circle cx="24.2" cy="7.8"  r="1.7" />
//           <circle cx="7.8"  cy="7.8"  r="1.7" />
//           <circle cx="24.2" cy="24.2" r="1.7" />
//           <circle cx="7.8"  cy="24.2" r="1.7" />
//         </g>
//         {/* central atom: electron-orbital ring + nucleus */}
//         <circle cx="16" cy="16" r="5.6" stroke="#ffffff" strokeWidth="3" />
//         <circle cx="16" cy="16" r="2" fill="#ffffff" />
//       </svg>
//     </span>
//   )
// }

// export default function Logo({ size = 32, radius = 8, wordmark = true, glow = false, color = 'var(--text-primary)' }) {
//   return (
//     <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.32 }}>
//       <LogoMark size={size} radius={radius} glow={glow} />
//       {wordmark && (
//         <span
//           style={{
//             fontSize: size * 0.52,
//             fontWeight: 700,
//             letterSpacing: '-0.02em',
//             color,
//           }}
//         >
//           Materia
//         </span>
//       )}
//     </span>
//   )
// }

// Materia brand mark — "Atomic Node"
// A central atom (teal disc + white electron-orbital ring + nucleus) with four
// radiating bonds ending in lattice nodes. Atom = matter, bonds = the lattice
// of materials science. Matches the main Option-1 lockup exactly.
// Single source of truth for the logo across the whole app.

const TEAL = '#00B4A6'
const RING = '#FFFFFF'

export function LogoMark({ size = 32, tile = false, radius = 8, glow = false }) {
  // tile = false  → filled teal atom on transparent (the main lockup look)
  // tile = true   → white atom inside a teal→sky gradient app-icon square

  const fg = tile ? RING : TEAL          // artwork color
  const inner = tile ? 'transparent' : RING // the orbital "hole"

  const art = (
    <svg
      width={tile ? size * 0.64 : size}
      height={tile ? size * 0.64 : size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* four radiating bonds (drawn first, sit under the atom) */}
      <g stroke={fg} strokeWidth="1.6" strokeLinecap="round">
        <line x1="21.66" y1="10.34" x2="24.84" y2="7.16" />
        <line x1="10.34" y1="10.34" x2="7.16"  y2="7.16" />
        <line x1="21.66" y1="21.66" x2="24.84" y2="24.84" />
        <line x1="10.34" y1="21.66" x2="7.16"  y2="24.84" />
      </g>

      {/* lattice nodes at the bond ends */}
      <g fill={fg}>
        <circle cx="24.84" cy="7.16"  r="1.6" />
        <circle cx="7.16"  cy="7.16"  r="1.6" />
        <circle cx="24.84" cy="24.84" r="1.6" />
        <circle cx="7.16"  cy="24.84" r="1.6" />
      </g>

      {/* central atom: teal disc → white orbital ring → teal nucleus */}
      {tile ? (
        <>
          <circle cx="16" cy="16" r="6.4" stroke={fg} strokeWidth="2.6" />
          <circle cx="16" cy="16" r="2" fill={fg} />
        </>
      ) : (
        <>
          <circle cx="16" cy="16" r="8"   fill={TEAL} />
          <circle cx="16" cy="16" r="3.8" fill={inner} />
          <circle cx="16" cy="16" r="1.7" fill={TEAL} />
        </>
      )}
    </svg>
  )

  if (!tile) return art

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
      {art}
    </span>
  )
}

export default function Logo({
  size = 32,
  wordmark = true,
  tile = false,
  radius = 8,
  glow = false,
  color = 'var(--text-primary)',
}) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.34 }}>
      <LogoMark size={size} tile={tile} radius={radius} glow={glow} />
      {wordmark && (
        <span
          style={{
            fontFamily: "'DM Sans', sans-serif",
            fontSize: size * 0.78,
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