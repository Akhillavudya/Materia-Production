/**
 * NEB workflow launch + migration-path preview (UI panel).
 *
 * Two ways to launch NEB, both hitting the same `compute_neb` tool the agent uses:
 *   • by migrating element — the backend builds the vacancy-mediated initial/final
 *     endpoints from the cell as supplied (run make_supercell first for hop space);
 *   • by two uploaded endpoint files — the user supplies their own relaxed states.
 * `listMigrationPaths` is the pre-flight that lists candidate hops to pick from.
 */

import { authRequest, readError } from './client'

// List candidate migration hops for `element` (no job). Analyses the structure
// exactly as supplied (no supercell); labels match what compute_neb builds from.
export async function listMigrationPaths(sessionId, {
  element, cutoff = 5.0, structure = null,
} = {}) {
  const form = new FormData()
  form.append('element', element)
  form.append('cutoff', String(cutoff))
  if (structure) form.append('structure', structure)

  const res = await authRequest(`/sessions/${sessionId}/migration-paths`, {
    method: 'POST', body: form,
  })
  if (!res.ok) throw new Error(await readError(res, 'Failed to list migration paths'))
  return res.json()
}

// Launch an NEB job. `opts.migratingElement` (non-empty) selects hop mode;
// otherwise `opts.initial` + `opts.final` files are used (two-file mode).
export async function launchNeb(sessionId, opts = {}) {
  const form = new FormData()
  const useHop = !!(opts.migratingElement && opts.migratingElement.trim())

  if (useHop) {
    form.append('migrating_element', opts.migratingElement.trim())
    if (opts.sourceSite != null && opts.sourceSite !== '')
      form.append('source_site', String(opts.sourceSite))
    if (opts.destSite != null && opts.destSite !== '')
      form.append('dest_site', String(opts.destSite))
    if (opts.structure) form.append('structure', opts.structure)
  } else {
    form.append('initial', opts.initial)
    form.append('final', opts.final)
  }

  if (opts.nImages != null) form.append('n_images', String(opts.nImages))
  if (opts.endpointFmax != null) form.append('endpoint_fmax', String(opts.endpointFmax))
  if (opts.calculatorType) form.append('calculator_type', opts.calculatorType)
  if (opts.calculatorModel) form.append('calculator_model', opts.calculatorModel)
  form.append('climb', opts.climb === false ? 'false' : 'true')
  form.append('run_frequencies', opts.runFrequencies === false ? 'false' : 'true')
  form.append('emit_vasp_inputs', opts.emitVaspInputs === false ? 'false' : 'true')

  const res = await authRequest(`/sessions/${sessionId}/neb`, {
    method: 'POST', body: form,
  })
  if (!res.ok) throw new Error(await readError(res, 'Failed to start NEB'))
  return res.json()
}
