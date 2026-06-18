# Step 5.5 — More VASP calculations + structure-building tools

**Status:** 🚧 Planned / in progress (started 2026-06-18)
**Goal:** Give PhD users many more kinds of VASP input files from the *one* `generate_vasp_inputs`
tool, and add tools that **build/modify the crystal structure itself** (supercell, vacuum, slab,
format conversion, symmetry, point defects) — so they can prepare real research calculations
(surfaces, charged defects, solvation, AIMD, beyond-PBE accuracy) without leaving Materia.

> Slots into the launch-hardening roadmap as **Step 5.5**, between the shipped Step 5 (invite-only
> signup) and later steps. It is feature work, not security hardening, hence the half-step number.

---

## The analogy
Until now Materia could **write recipes** (INCAR/KPOINTS) for four dishes — static, relaxation,
band, DOS — for a structure you already had. Two things were missing:

1. **More recipes.** Researchers wanted ab-initio MD, elastic constants, phonons, dielectric/optical,
   Bader/ELF charge analysis, work functions, *and* the ability to switch the "cooking method"
   (HSE06/SCAN functionals, +U, spin-orbit, van-der-Waals, implicit solvent, charged cells).
2. **Preparing the ingredients.** You can't study a *surface* without first **slicing a slab** and
   **adding vacuum**; you can't study a *defect* without first building a **supercell** and removing,
   swapping, or inserting an atom. Those are structure-building steps that happen *before* any recipe.

Step 5.5 adds both — the extra recipes (as options on one VASP tool) and the ingredient-prep tools.

---

## How it works

### A) One VASP tool, many tags — `task` + modifiers
`generate_vasp_inputs` keeps a single entry point. You pick a **base task** (what physics you want)
and optionally stack **modifiers** (orthogonal knobs that apply to *any* task). Example:
*"HSE06 band structure with spin-orbit"* → `task=band, functional=hse06, soc=true`.

**New base tasks:** `aimd`, `elastic`, `phonon_dfpt`, `dielectric`, `bader`, `elf`, `workfunction`
(added alongside the existing `static`/`relaxation`/`band`/`dos`).

**Modifiers (combine freely):** `functional` (pbe/hse06/scan), `vdw` (d3/d3bj/optb88/df2),
`soc`, `hubbard_u` (DFT+U), `solvent` (vaspsol / vaspsol++), `dipole`, `charge` (sets `NELECT`).

> Why one tool, not 20: fewer choices for the AI agent = it picks the right one more reliably.
> This mirrors the deliberate "few tools" design already used elsewhere in Materia.

### B) Structure tools — 5 new tools
- **`build_structure`** — one tool, four *transform* operations chosen by an `operation` arg:
  `make_supercell`, `add_vacuum`, `make_slab`, `convert`. They share the same shape (read a
  structure → modify it → write a new POSCAR into the session), so they live behind one entry point.
  Because each writes the active POSCAR, you can **chain** them (e.g. slab → then convert) just by
  asking for both — the agent calls the tool twice in sequence.
- **`analyze_symmetry`** — *read-only*: reports space group, point group, crystal system. Kept
  separate because it inspects rather than builds.
- **`create_vacancy` / `create_substitution` / `create_interstitial`** — three point-defect tools
  (built last; they need the `pymatgen-analysis-defects` package).

All structure tools reuse the existing structure-resolution and **enforce the server atom cap on
their output** (a supercell or defect cell can balloon the atom count).

---

## 📁 Files that change & why (planned)

**VASP expansion (Part A):**
- `app/domain/vasp.py` — extend the `VaspTask` enum; add `Functional`/`Vdw`/`Solvent` enums; extend
  the `VaspInputSet` summary with the applied modifiers.
- `app/services/vasp/templates.py` — new per-task INCAR templates + modifier tag-group dicts.
- `app/services/vasp/incar.py` — `generate_incar` learns the modifier knobs and merges them in a
  defined order (common → task → modifiers → cell_relax → user overrides).
- `app/services/vasp/service.py` — `build_input_set` threads modifiers through; per-task KPOINTS/ENCUT
  tweaks; computes `NELECT` for charged cells from the POTCAR ZVAL table.
- `app/services/vasp/kpoints.py` — Gamma-only mesh for AIMD; denser default for phonon/dielectric.
- `app/tools/contracts.py` + `app/agent/tool_schemas.py` — expose the new task values + modifiers to
  the agent with clear descriptions.
- `app/tools/material_tools.py` — pass modifiers through; add the atom cap to the VASP path.
- `app/api/catalog.py` — list the new tasks + a modifier schema the UI can render.

**Structure tools (Part B):**
- `app/services/structure/builder.py` *(new)* — pure functions for supercell/vacuum/slab/convert,
  symmetry, and (last) the three defect builders.
- `app/tools/material_tools.py` — thin adapter tools that call the builders and write POSCARs.
- `app/tools/contracts.py`, `app/agent/tool_registry.py`, `app/agent/tool_schemas.py` — register the
  5 new agent tools (the 3-spot registration pattern).
- `backend/requirements.txt` — uncomment `pymatgen-analysis-defects` (only for the defect step).
- `frontend/src/features/chat/ToolStatus.jsx` (+ the VASP task/modifier form) — surface the new
  tasks/modifiers and label the new tools.

---

## Build order (incremental; ONE Docker rebuild at the very end)
Each step is verified in the dev venv (import + generate a sample) — **no Docker rebuild between
steps**, to avoid repeated slow ARM builds.

0. Modifier scaffolding (no behavior change; existing 4 tasks must stay byte-identical).
1. New base tasks → 2. functional/vdw/soc/dipole/+U/charge modifiers → 3. solvent (vaspsol/++).
4. `build_structure`+`make_supercell` → 5. `add_vacuum` → 6. `make_slab` → 7. `convert`.
8. `analyze_symmetry`. → 9. defect tools + the new dependency (**last**, isolates ARM-build risk).
10. Frontend surfacing. → 11. **single Docker image rebuild + smoke test.**

---

## Verified
*(updated as steps land)*
- [x] Step 0 — existing static/relaxation/band/DOS INCARs **byte-identical** after scaffolding;
      modifiers inject their tags when explicitly passed.
- [x] Step 1 — aimd/elastic/phonon_dfpt/dielectric/bader/elf/workfunction each emit the expected
      INCAR tags via `build_input_set`; AIMD gets a Γ-only mesh, dielectric/phonon a denser mesh;
      `/api/vasp/tasks` lists all 11; core tasks unchanged.
- [ ] Step 2–3 — each new modifier emits the expected INCAR tags; combinations work.
- [ ] Step 4–8 — structure tools write POSCARs; atom cap rejects oversized cells; tools chain.
- [ ] Step 9 — defect tools import and run after the dependency is added.
- [ ] Step 11 — Docker image rebuilds; one VASP gen + one structure op verified end-to-end.

## Not included (intentionally — deferred to a follow-up)
- **NEB** (climbing-image): needs an `initial`+`final` structure, image interpolation, and a
  multi-folder `00/ 01/ …` layout — structurally different from single-directory generation.
- **Finite-displacement phonons** (Phonopy supercell sets) and **GW/BSE** multi-step chains.
- **Multi-volume EOS** (Birch–Murnaghan): needs several scaled-volume runs.
These all require multi-directory / multi-step output and will be planned separately.
