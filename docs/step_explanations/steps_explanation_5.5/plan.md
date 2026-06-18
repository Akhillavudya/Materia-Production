# Step 5.5 — Plan: More VASP calculations + structure-building tools

**Status:** 🚧 In progress (started 2026-06-18)
**Goal:** Give PhD users many more kinds of VASP input files from the *one* `generate_vasp_inputs`
tool, and add tools that **build/modify the crystal structure itself** (supercell, vacuum, slab,
format conversion, symmetry, point defects) — so they can prepare real research calculations
(surfaces, charged defects, solvation, AIMD, beyond-PBE accuracy) without leaving Materia.

> This folder holds the **plan** (this file) plus a **per-step explanation** (`stepN_explanation.md`)
> for each implementation step. Step 5.5 slots into the launch-hardening roadmap between the shipped
> Step 5 (invite-only signup) and later steps; it is feature work, hence the half-step number.

---

## The analogy
Materia could **write recipes** (INCAR/KPOINTS) for four dishes — static, relaxation, band, DOS —
for a structure you already had. Two things were missing:

1. **More recipes.** Researchers wanted ab-initio MD, elastic constants, phonons, dielectric/optical,
   Bader/ELF charge analysis, work functions, *and* the ability to switch the "cooking method"
   (HSE06/SCAN functionals, +U, spin-orbit, van-der-Waals, implicit solvent, charged cells).
2. **Preparing the ingredients.** You can't study a *surface* without first **slicing a slab** and
   **adding vacuum**; you can't study a *defect* without a **supercell** plus removing/swapping/adding
   an atom. Those are structure-building steps that happen *before* any recipe.

---

## Design decisions (locked with the user)
1. **VASP = ONE tool** (`generate_vasp_inputs`): a base `task` + **orthogonal modifier flags**, so e.g.
   an HSE06 band structure is `task=band, functional=hse06`.
2. **Structure work = 5 new tools:**
   - `build_structure` — one combined tool, four transform operations (`make_supercell`, `add_vacuum`,
     `make_slab`, `convert`) chosen by an `operation` arg.
   - `analyze_symmetry` — separate, *read-only* (space group / point group).
   - `create_vacancy` / `create_substitution` / `create_interstitial` — three point-defect tools.
3. **Defect tools come last** — only they need a new dependency (`pymatgen-analysis-defects`).
4. **Deferred to a follow-up:** NEB image folders, finite-displacement phonons, GW/BSE, multi-volume
   EOS — they need multi-directory/multi-step output that doesn't fit single-dir generation.
5. **Incremental** — one verifiable step at a time; **rebuild the Docker image ONCE at the end**.

---

## Build order (one commit per step; single Docker rebuild at the end)
| Step | What | Doc |
|---|---|---|
| 0 | Modifier scaffolding (inert at defaults) | `step0_explanation.md` ✅ |
| 1 | 7 new base tasks (aimd/elastic/phonon/dielectric/bader/elf/workfunction) | `step1_explanation.md` ✅ |
| 2 | Expose modifiers (functional/vdw/soc/hubbard_u/dipole/charge) | `step2_explanation.md` ✅ |
| 3 | Solvent modifier (vaspsol / vaspsol++) + warnings | `step3_explanation.md` ✅ |
| 4 | `build_structure` scaffold + `make_supercell` | `step4_explanation.md` ✅ |
| 5 | `add_vacuum` operation | `step5_explanation.md` ✅ |
| 6 | `make_slab` operation | `step6_explanation.md` ✅ |
| 7 | `convert` operation | `step7_explanation.md` ✅ |
| 8 | `analyze_symmetry` (read-only tool) | `step8_explanation.md` ✅ |
| 9 | Defect tools + `pymatgen-analysis-defects` (LAST) | `step9_explanation.md` ✅ |
| 10 | Frontend surfacing (tasks/modifiers form + tool labels) | `step10_explanation.md` |
| 11 | ONE Docker image rebuild + smoke test | `step11_explanation.md` |

---

## Running verification checklist
- [x] **Step 0** — existing static/relaxation/band/DOS INCARs **byte-identical** after scaffolding.
- [x] **Step 1** — 7 new tasks emit expected tags; AIMD Γ-only, dielectric/phonon denser; 11 tasks listed.
- [x] **Step 2** — modifiers wired; hse06+band, soc, vdw, +U, charge→NELECT, dipole verified; no-op default.
- [x] **Step 3** — solvent emits LSOL (+LRHOB/NC_K for ++) + warns about the patched VASP binary;
      pairs with charge for charged interfaces.
- [x] **Step 4** — `build_structure`+`make_supercell` writes the active POSCAR; atom cap rejects
      oversized supercells; registered in the agent schema (operation required).
- [x] **Step 5** — `add_vacuum` extends a lattice axis, recentres atoms, writes active POSCAR; chains
      after make_supercell.
- [x] **Step 6** — `make_slab` cuts a Miller-plane surface (vacuum included) via SlabGenerator;
      conventional-cell conversion; atom-capped; active POSCAR written.
- [x] **Step 7** — `convert` writes the structure as poscar/cif/xyz/cssr/json (early-return, does not
      touch the active POSCAR); invalid format rejected.
- [x] **Step 8** — `analyze_symmetry` reports space/point group + crystal system (read-only); optional
      write of primitive/conventional cell; registered (10 tools total).
- [x] **Step 9** — vacancy/substitution/interstitial tools build defective supercells (geometry-only;
      charge via generate_vasp_inputs); pymatgen-analysis-defects uncommented; 13 tools total.
- [ ] **Step 11** — Docker image rebuilds; one VASP gen + one structure op verified end-to-end.

---

## Not included (intentionally — deferred)
- **NEB** (climbing-image): needs initial+final structures, image interpolation, and a multi-folder
  `00/ 01/ …` layout.
- **Finite-displacement phonons** (Phonopy supercell sets) and **GW/BSE** multi-step chains.
- **Multi-volume EOS** (Birch–Murnaghan): several scaled-volume runs.
