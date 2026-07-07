/**
 * Direct tool-launch API (UI tool panel).
 *
 * Posts an optional structure file + curated parameters straight to the backend,
 * which stores the file (if any) and enqueues the same async job the chat agent
 * uses. Leaving the file out makes the tool auto-detect the session's active
 * structure. Each call returns the queued-job envelope ({ job_id, ... }).
 */

import { authRequest, readError } from './client'

/** Build FormData: attach the file only when present, stringify every param. */
function buildForm(file, params) {
  const form = new FormData()
  if (file) form.append('structure', file)
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') form.append(k, String(v))
  }
  return form
}

async function launch(sessionId, endpoint, file, params, errLabel) {
  const res = await authRequest(`/sessions/${sessionId}/${endpoint}`, {
    method: 'POST',
    body: buildForm(file, params),
  })
  if (!res.ok) throw new Error(await readError(res, errLabel))
  return res.json()
}

export const launchOptimize = (sessionId, file, params) =>
  launch(sessionId, 'optimize', file, params, 'Failed to start optimization')

export const launchMd = (sessionId, file, params) =>
  launch(sessionId, 'md', file, params, 'Failed to start MD')

export const launchPhonons = (sessionId, file, params) =>
  launch(sessionId, 'phonons', file, params, 'Failed to start phonons')

export const launchElastic = (sessionId, file, params) =>
  launch(sessionId, 'elastic', file, params, 'Failed to start mechanical')

export const launchSqs = (sessionId, file, params) =>
  launch(sessionId, 'sqs', file, params, 'Failed to start SQS')

// Pre-flight for the SQS panel: list the symmetry-distinct sublattices (Sr, Ti,
// O…) of the active/uploaded structure so the user knows which site to alloy.
export const fetchSqsSublattices = (sessionId, file, symprec = 0.1) =>
  launch(sessionId, 'sqs/sublattices', file, { symprec }, 'Failed to detect sublattices')

// ── instant structure tools (Step 3): synchronous, return a tool-card envelope
//    ({ status, files_written, message }) rather than a queued job. ──
export const launchMakeSupercell = (sessionId, file, params) =>
  launch(sessionId, 'make_supercell', file, params, 'Failed to build supercell')

export const launchAddVacuum = (sessionId, file, params) =>
  launch(sessionId, 'add_vacuum', file, params, 'Failed to add vacuum')

export const launchMakeSlab = (sessionId, file, params) =>
  launch(sessionId, 'make_slab', file, params, 'Failed to make slab')

export const launchAddAdsorbate = (sessionId, file, params) =>
  launch(sessionId, 'add_adsorbate', file, params, 'Failed to add adsorbate')

export const launchConvertStructure = (sessionId, file, params) =>
  launch(sessionId, 'convert_structure', file, params, 'Failed to convert structure')

// ── VASP-input + defect tools (instant, return a tool-card envelope) ──
export const launchGenerateVaspInputs = (sessionId, file, params) =>
  launch(sessionId, 'generate_vasp_inputs', file, params, 'Failed to generate VASP inputs')

export const launchGeneratePoscar = (sessionId, file, params) =>
  launch(sessionId, 'generate_poscar', file, params, 'Failed to generate POSCAR')

export const launchGenerateKpoints = (sessionId, file, params) =>
  launch(sessionId, 'generate_kpoints', file, params, 'Failed to generate KPOINTS')

export const launchCreateVacancy = (sessionId, file, params) =>
  launch(sessionId, 'create_vacancy', file, params, 'Failed to create vacancy')

export const launchCreateSubstitution = (sessionId, file, params) =>
  launch(sessionId, 'create_substitution', file, params, 'Failed to create substitution')

export const launchCreateInterstitial = (sessionId, file, params) =>
  launch(sessionId, 'create_interstitial', file, params, 'Failed to create interstitial')

/**
 * Fetch the locally-available ML-potential models grouped by family
 * ({ models: { mace: [{name, exists}], mattersim: [...] }, available }).
 * Powers the Model dropdown in the tool launcher so only present checkpoints
 * are offered.
 */
export async function fetchCalculators() {
  const res = await authRequest('/calculators')
  if (!res.ok) throw new Error(await readError(res, 'Failed to load models'))
  return res.json()
}
