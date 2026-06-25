/**
 * Coordination-polyhedra geometry for the VESTA-style viewer.
 *
 * 3Dmol.js cannot draw coordination polyhedra, so we compute them ourselves:
 *   1. parse the lattice + atoms (POSCAR, or a 3Dmol model for CIF/XYZ),
 *   2. for every cation, gather its neighbouring anions within a bond cutoff,
 *      searching periodic images so cell-edge polyhedra come out complete,
 *   3. take the convex hull of those neighbours → a triangle mesh,
 *   4. hand the mesh to 3Dmol via viewer.addCustom (coloured by the cation).
 *
 * The result mirrors VESTA's default "polyhedral" rendering.
 */

// Common anions — these sit at polyhedron vertices, never at the centre.
const ANIONS = new Set(['O', 'F', 'Cl', 'Br', 'I', 'S', 'Se', 'Te', 'N', 'P', 'As', 'H'])

// Covalent radii (Å). Used for a per-pair bond cutoff. Fallback is 1.5 Å.
const COV = {
  H: 0.31, Li: 1.28, Be: 0.96, B: 0.84, C: 0.76, N: 0.71, O: 0.66, F: 0.57,
  Na: 1.66, Mg: 1.41, Al: 1.21, Si: 1.11, P: 1.07, S: 1.05, Cl: 1.02,
  K: 2.03, Ca: 1.76, Sc: 1.70, Ti: 1.60, V: 1.53, Cr: 1.39, Mn: 1.39,
  Fe: 1.32, Co: 1.26, Ni: 1.24, Cu: 1.32, Zn: 1.22, Ga: 1.22, Ge: 1.20,
  As: 1.19, Se: 1.20, Br: 1.20, Rb: 2.20, Sr: 1.95, Y: 1.90, Zr: 1.75,
  Nb: 1.64, Mo: 1.54, Ru: 1.46, Rh: 1.42, Pd: 1.39, Ag: 1.45, Cd: 1.44,
  In: 1.42, Sn: 1.39, Sb: 1.39, Te: 1.38, I: 1.39, Cs: 2.44, Ba: 2.15,
  La: 2.07, Ce: 2.04, Hf: 1.75, Ta: 1.70, W: 1.62, Re: 1.51, Os: 1.44,
  Ir: 1.41, Pt: 1.36, Au: 1.36, Hg: 1.32, Pb: 1.46, Bi: 1.48,
}
function radius(el) { return COV[el] ?? 1.5 }

// ── small vector helpers (plain [x,y,z] arrays) ──────────────────────────────
const sub  = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot  = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]
const len  = (a) => Math.hypot(a[0], a[1], a[2])
const dist = (a, b) => len(sub(a, b))

// 3×3 inverse (rows). Returns null if (near-)singular.
function inv3(m) {
  const [a, b, c] = m[0], [d, e, f] = m[1], [g, h, i] = m[2]
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
  if (Math.abs(det) < 1e-12) return null
  const r = 1 / det
  return [
    [(e * i - f * h) * r, (c * h - b * i) * r, (b * f - c * e) * r],
    [(f * g - d * i) * r, (a * i - c * g) * r, (c * d - a * f) * r],
    [(d * h - e * g) * r, (b * g - a * h) * r, (a * e - b * d) * r],
  ]
}
// row-vector × matrix: result[k] = Σ_j v[j]·M[j][k]  (so cart·L⁻¹ → frac)
function matVec(M, v) {
  return [
    v[0] * M[0][0] + v[1] * M[1][0] + v[2] * M[2][0],
    v[0] * M[0][1] + v[1] * M[1][1] + v[2] * M[2][1],
    v[0] * M[0][2] + v[1] * M[1][2] + v[2] * M[2][2],
  ]
}

// ── POSCAR parser → { lattice:[a,b,c], atoms:[{elem, cart}] } ─────────────────
// Hand-rolled (we do NOT trust 3Dmol's VASP parser — it bails to zero atoms on
// minor formatting quirks). Tolerant of blank lines, VASP4/5, selective
// dynamics, Direct/Cartesian, and trailing per-line element labels.
export function parsePoscar(text) {
  // keep only non-empty lines so stray blank lines never shift the layout
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l.length)
  if (lines.length < 7) return { lattice: null, atoms: [] }

  const scale = parseFloat(lines[1]) || 1
  const sc = scale > 0 ? scale : 1
  const vec = (ln) => lines[ln].split(/\s+/).map(Number)
  const lattice = [vec(2), vec(3), vec(4)].map(v => v.map(x => x * sc))

  // line 5 is either element symbols (VASP5) or counts (VASP4)
  const tok5 = lines[5].split(/\s+/)
  let symbols, idx
  let counts
  if (tok5.every(t => /^\d+$/.test(t))) {
    counts = tok5.map(Number)
    symbols = counts.map((_, i) => `X${i}`)   // VASP4 — no symbols available
    idx = 6
  } else {
    symbols = tok5
    counts = lines[6].split(/\s+/).map(Number)
    idx = 7
  }

  // optional "Selective dynamics" line, then the coordinate-mode line
  let mode = lines[idx] || ''
  if (/^[sS]/.test(mode)) { idx++; mode = lines[idx] || '' }
  const cartesian = /^[cCkK]/.test(mode)
  idx++

  const elems = []
  symbols.forEach((sym, i) => { for (let n = 0; n < counts[i]; n++) elems.push(sym) })

  const invL = cartesian ? inv3(lattice) : null   // for cart → frac recovery
  const atoms = []
  for (let n = 0; n < elems.length; n++) {
    const p = (lines[idx + n] || '').split(/\s+/).map(Number)
    if (p.length < 3 || [p[0], p[1], p[2]].some(Number.isNaN)) break
    let cart, frac
    if (cartesian) {
      cart = [p[0] * sc, p[1] * sc, p[2] * sc]
      frac = invL ? matVec(invL, cart) : null   // cart·L⁻¹
    } else {
      frac = [p[0], p[1], p[2]]
      cart = [
        frac[0] * lattice[0][0] + frac[1] * lattice[1][0] + frac[2] * lattice[2][0],
        frac[0] * lattice[0][1] + frac[1] * lattice[1][1] + frac[2] * lattice[2][1],
        frac[0] * lattice[0][2] + frac[1] * lattice[1][2] + frac[2] * lattice[2][2],
      ]
    }
    atoms.push({ elem: elems[n], cart, frac })
  }
  return { lattice, atoms }
}

// Replicate atoms across the lattice into an na×nb×nc supercell.
export function replicateAtoms(atoms, lattice, na = 1, nb = 1, nc = 1) {
  if (!lattice || (na <= 1 && nb <= 1 && nc <= 1)) return atoms
  const out = []
  for (let i = 0; i < na; i++)
    for (let j = 0; j < nb; j++)
      for (let k = 0; k < nc; k++)
        for (const at of atoms) {
          out.push({
            elem: at.elem,
            cart: [
              at.cart[0] + i * lattice[0][0] + j * lattice[1][0] + k * lattice[2][0],
              at.cart[1] + i * lattice[0][1] + j * lattice[1][1] + k * lattice[2][1],
              at.cart[2] + i * lattice[0][2] + j * lattice[1][2] + k * lattice[2][2],
            ],
          })
        }
  return out
}

// VESTA-style boundary duplication: an atom sitting on a cell face/edge/corner
// (a fractional coordinate ≈0 or ≈1) is also drawn in the neighbouring cells, so
// a slab/crystal fills out instead of looking sparse. Needs per-atom `frac`.
export function expandBoundaryAtoms(atoms, lattice, tol = 0.02) {
  if (!lattice) return atoms
  const toCart = (f) => [
    f[0] * lattice[0][0] + f[1] * lattice[1][0] + f[2] * lattice[2][0],
    f[0] * lattice[0][1] + f[1] * lattice[1][1] + f[2] * lattice[2][1],
    f[0] * lattice[0][2] + f[1] * lattice[1][2] + f[2] * lattice[2][2],
  ]
  const out = []
  const seen = new Set()
  for (const at of atoms) {
    const f = at.frac
    if (!f) { out.push({ elem: at.elem, cart: at.cart }); continue }
    // per-axis options: keep f, plus its periodic twin when on a boundary
    const opts = f.map(v => {
      const o = [v]
      if (Math.abs(v) < tol) o.push(v + 1)
      else if (Math.abs(v - 1) < tol) o.push(v - 1)
      return o
    })
    for (const x of opts[0]) for (const y of opts[1]) for (const z of opts[2]) {
      const cart = toCart([x, y, z])
      const key = cart.map(c => Math.round(c * 100)).join(',')
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ elem: at.elem, cart })
    }
  }
  return out
}

// Build a minimal XYZ document — 3Dmol's most reliable parser, so we feed it
// our own parsed atoms instead of trusting its VASP/CIF readers.
export function toXyz(atoms, comment = 'structure') {
  const body = atoms
    .map(a => `${a.elem} ${a.cart[0].toFixed(6)} ${a.cart[1].toFixed(6)} ${a.cart[2].toFixed(6)}`)
    .join('\n')
  return `${atoms.length}\n${comment}\n${body}\n`
}

// ── convex hull of a small point set → outward-oriented triangles ─────────────
// Brute force (O(n^4)); n is a coordination number (~4–12), so this is cheap and
// robust. Coplanar vertex sets (square-planar, etc.) collapse to a flat polygon.
function hullTriangles(points) {
  const n = points.length
  if (n < 3) return []
  if (n === 3) {
    const nrm = cross(sub(points[1], points[0]), sub(points[2], points[0]))
    const l = len(nrm) || 1
    return [[points[0], points[1], points[2], nrm.map(x => x / l)]]
  }

  const centroid = points.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1], acc[2] + p[2]], [0, 0, 0])
    .map(x => x / n)

  const eps = 1e-3
  const tris = []
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      for (let k = j + 1; k < n; k++) {
        const nrm = cross(sub(points[j], points[i]), sub(points[k], points[i]))
        const l = len(nrm)
        if (l < eps) continue                 // collinear triple
        let pos = false, neg = false
        for (let m = 0; m < n; m++) {
          if (m === i || m === j || m === k) continue
          const d = dot(nrm, sub(points[m], points[i])) / l
          if (d > eps) pos = true
          else if (d < -eps) neg = true
        }
        if (pos && neg) continue              // interior plane, not a hull face
        // orient the normal outward (away from the polyhedron centre)
        let un = [nrm[0] / l, nrm[1] / l, nrm[2] / l]
        const mid = [
          (points[i][0] + points[j][0] + points[k][0]) / 3,
          (points[i][1] + points[j][1] + points[k][1]) / 3,
          (points[i][2] + points[j][2] + points[k][2]) / 3,
        ]
        if (dot(un, sub(mid, centroid)) < 0) {
          un = [-un[0], -un[1], -un[2]]
          tris.push([points[i], points[k], points[j], un])  // flip winding too
        } else {
          tris.push([points[i], points[j], points[k], un])
        }
      }
    }
  }
  return tris
}

/**
 * Build polyhedra meshes ready for viewer.addCustom().
 *
 * @param {{lattice:number[][]|null, atoms:{elem:string,cart:number[]}[]}} geom
 * @param {{ tol:number, getColor:(el:string)=>string }} opts
 * @returns {{color:string, vertexArr:object[], normalArr:object[], faceArr:number[]}[]}
 */
export function buildPolyhedra(geom, { tol = 1.3, getColor }) {
  const { lattice, atoms } = geom
  if (!atoms?.length) return []

  // periodic images: 27 cells when we have a lattice, else just the atoms
  const shifts = []
  if (lattice) {
    for (let i = -1; i <= 1; i++)
      for (let j = -1; j <= 1; j++)
        for (let k = -1; k <= 1; k++) shifts.push([i, j, k])
  } else {
    shifts.push([0, 0, 0])
  }
  const images = []
  for (const at of atoms) {
    for (const [i, j, k] of shifts) {
      const c = lattice
        ? [
            at.cart[0] + i * lattice[0][0] + j * lattice[1][0] + k * lattice[2][0],
            at.cart[1] + i * lattice[0][1] + j * lattice[1][1] + k * lattice[2][1],
            at.cart[2] + i * lattice[0][2] + j * lattice[1][2] + k * lattice[2][2],
          ]
        : at.cart
      images.push({ elem: at.elem, cart: c })
    }
  }

  const hasAnions = atoms.some(a => ANIONS.has(a.elem))
  const shapes = []

  for (const at of atoms) {
    if (hasAnions && ANIONS.has(at.elem)) continue   // anions are vertices, not centres
    const r0 = radius(at.elem)

    const neigh = []
    for (const im of images) {
      // when the structure is ionic, only bond cations to anions (VESTA default)
      if (hasAnions && !ANIONS.has(im.elem)) continue
      const d = dist(at.cart, im.cart)
      if (d < 0.1) continue                          // itself
      if (d <= (r0 + radius(im.elem)) * tol) neigh.push(im.cart)
    }
    if (neigh.length < 3) continue

    const tris = hullTriangles(neigh)
    if (!tris.length) continue

    const vertexArr = [], normalArr = [], faceArr = []
    let idx = 0
    for (const [a, b, c, nrm] of tris) {
      vertexArr.push({ x: a[0], y: a[1], z: a[2] }, { x: b[0], y: b[1], z: b[2] }, { x: c[0], y: c[1], z: c[2] })
      const N = { x: nrm[0], y: nrm[1], z: nrm[2] }
      normalArr.push(N, N, N)
      faceArr.push(idx, idx + 1, idx + 2)
      idx += 3
    }
    shapes.push({ color: getColor(at.elem), vertexArr, normalArr, faceArr })
  }
  return shapes
}

/**
 * Geometry for the polyhedra builder, from whatever 3Dmol parsed.
 * POSCAR is parsed directly (exact); CIF/XYZ fall back to the 3Dmol model's
 * atoms + crystal matrix.
 */
export function geometryFor(model, content, format) {
  if (format === 'vasp') return parsePoscar(content)

  const atoms = model.selectedAtoms({}).map(a => ({ elem: a.elem, cart: [a.x, a.y, a.z] }))
  let lattice = null
  try {
    const cd = model.getCrystData?.()
    const m = cd?.matrix?.elements
    if (m && m.length >= 9) {
      // Matrix3 is column-major: columns are the lattice vectors a, b, c
      lattice = [[m[0], m[1], m[2]], [m[3], m[4], m[5]], [m[6], m[7], m[8]]]
    }
  } catch { /* molecule / no cell → non-periodic */ }
  return { lattice, atoms }
}
