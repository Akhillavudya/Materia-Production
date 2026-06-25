# T3 — VASP Input Fidelity, Explained

**The "are the simulation instruction files correct?" tier.**

> Read [`README.md`](README.md) first if you haven't. Raw output:
> `docs/validation_results/T3_vasp_inputs.md`. Test code:
> `backend/tests/validation/test_vasp_inputs.py`; helper script:
> `backend/scripts/validation/t3_potcar_mp_diff.py`.

---

## 1. The one-sentence idea

> Check that the **input files Materia generates for VASP** are correct, and — where a
> field-standard recipe exists — that they agree with **pymatgen's MPRelaxSet**.

## 2. First, what is VASP and why does it need input files?

**VASP** is a famous (commercial) program that runs DFT — the slow, accurate physics
simulation. To run a calculation, VASP reads **four text files**, each with a fixed name
and job:

| File | Plain-language job | Analogy (baking a cake) |
|------|--------------------|--------------------------|
| **POSCAR** | the atoms and their positions | the *ingredients list* (what's in the bowl) |
| **INCAR** | all the calculation settings/knobs | the *oven settings & method* (temperature, time, mode) |
| **KPOINTS** | how finely to sample the crystal's repeating pattern | the *resolution* — how carefully you check the batter |
| **POTCAR** | the "pseudopotential" data for each element | the *spec sheet* for each ingredient's behaviour |

If any of these is wrong, the simulation is wrong (or won't run). Materia **generates**
these files for the user, so we must validate them.

**Why "fidelity"?** Because the question isn't "is there one true answer" (there are
valid stylistic choices), it's "are our files *faithful* to correct physics and to the
field's standard recipes?"

## 3. The reference recipe: pymatgen's `MPRelaxSet`

The Materials Project published a standard "recipe" for VASP inputs called **MPRelaxSet**
(implemented in pymatgen). It's the most widely used default in the field. So for the
parts where a standard exists, we compare our files against it.

**Analogy:** MPRelaxSet is like the "official" recipe in a famous cookbook. We're checking
our recipe card against it — and where we deliberately deviate, we *write down why*.

## 4. What we check, concept by concept

### (a) KPOINTS — the "resolution" knob
A crystal repeats forever, so VASP samples it on a grid of points in "reciprocal space"
(**k-points**). More points = finer resolution = more accurate but slower.

**Analogy: photo resolution.** Low/Medium/High accuracy is like 480p/1080p/4K. Higher
should *never* give fewer pixels.

We assert:
- Higher accuracy (Low→Medium→High) **never decreases** the number of k-points
  (monotonic), and the realised density tracks what was requested.
- "Gamma-centred" vs "Monkhorst-Pack" (two standard grid styles) is honoured.
- Asking for a custom density without giving the number is rejected (good error-handling).

### (b) INCAR — the "oven settings"
This file has dozens of cryptic knobs (`IBRION`, `ISIF`, `ENCUT`, …). We check the
important ones are set correctly for each **task**:

- **Relaxation** ("let the structure settle"): must have the move-atoms knob on
  (`IBRION=2`), a positive number of steps, and a force-convergence target.
- **Static** ("just compute, don't move"): must have steps = 0.
- **Cell-relax mode → `ISIF`**: a small lookup (positions-only→2, shape→5, full→3). We
  check each maps correctly.
- **Magnetism auto-detection:** if the structure contains a magnetic element (Fe, Co, Ni,
  …), Materia must automatically turn on spin (`ISPIN=2`) and give one magnetic-moment
  value **per atom**. We verify the count matches the number of atoms.
- **DFT+U** (a correction for certain transition-metal oxides): the per-element
  correction values must be listed **in the same order as the elements appear** — get the
  order wrong and you'd apply the correction to the wrong element. We check the ordering.
- **Modifiers** (optional extras like a different functional or a van-der-Waals
  correction): when requested they add the right tags; when *not* requested the file is
  clean (no stray tags). This "inert by default" property matters.

**Analogy:** like checking that "bake" mode turns the heat on, "defrost" mode keeps it
low, and that selecting "convection" actually adds the fan setting — and selecting nothing
leaves the defaults untouched.

### (c) POTCAR — the per-element "spec sheets"
Real POTCAR files are **licensed** (you're not allowed to share them), so Materia ships a
human-readable **`POTCAR.spec`** (which potential to use per element, plus the recommended
energy cutoff `ENCUT`). A real POTCAR is only assembled at runtime if a licensed library
is mounted.

We check:
- The elements are listed in the **same order as in POSCAR** (VASP requires this — a
  mismatch silently corrupts the run). Analogy: the spec sheets must be stacked in the
  same order as the ingredients.
- The recommended `ENCUT` floor is computed correctly (`⌈max ENMAX × 1.3⌉` — a standard
  safety margin).
- An unknown element degrades gracefully (a warning, not a crash).

## 5. The interesting finding: a 69% POTCAR match — and why that's fine

We compared the **potential labels** Materia recommends per element against MPRelaxSet's.
They agree **11 out of 16 (69%)**. The 5 differences are: Cu, Fe, Mg, Ti, Ni.

**Is that a bug? No — and understanding why is the lesson.**
- Materia follows the **current VASP-recommended** set of potentials.
- The Materials Project froze its own (often the `_pv` "semicore" variants) years ago so
  that *all 150,000 entries in its database stay mutually comparable*.

**Analogy:** two reputable cookbooks call for slightly different flour (bread flour vs
all-purpose). Neither is "wrong" — they optimise for different goals (Materia: VASP's
latest accuracy advice; MP: internal database consistency). The honest move in validation
is to **report the deviation and explain it**, not hide it. (A future option is a switch
to mirror MP's exact labels when someone wants to reproduce MP energies.)

Meanwhile the **ENCUT default (520 eV) matches MPRelaxSet exactly** — agreement where it
counts.

## 6. The files that make T3 work

### `backend/tests/validation/test_vasp_inputs.py` — the checks (21 of them)
A pytest file like T2's. It generates INCAR/KPOINTS/POTCAR.spec for known structures and
asserts the contents are correct. It includes small helpers:
- `_parse_incar(text)` — turns the generated INCAR text into a `{key: value}` dictionary
  so tests can check individual knobs.
- `_kmesh(text)` — pulls the grid numbers out of a KPOINTS file.

These helpers exist because the tools return **text files**, and we need to read specific
values back out to check them — like parsing a receipt to verify a single line item.

### `backend/scripts/validation/t3_potcar_mp_diff.py` — the deviation report
A small standalone script (not a pass/fail test, because the deviations are *intentional*)
that prints the per-element Materia-vs-MP label table and the overall match rate (69%).
It produces the evidence behind §5.

### Shared setup: `conftest.py`
Same shared-fixtures file described in [`T2_explained.md`](T2_explained.md) — it provides
the reference crystals these tests reuse.

## 7. Why some things are *not* tested locally (and that's expected)

- **Real POTCAR assembly** needs the licensed VASP potential library, which is mounted
  only at runtime (never on a dev machine), so we test the `.spec` generation instead.
- We don't run actual VASP/DFT here — T3 validates the **inputs**, not a DFT run. (T1
  already covers "do the physics predictions come out right" via the fast ML potentials.)

## 8. How to run it

```bash
cd backend
# The 21 deterministic checks:
../venv/bin/python -m pytest tests/validation/test_vasp_inputs.py -v

# The POTCAR-vs-MP deviation table:
../venv/bin/python scripts/validation/t3_potcar_mp_diff.py
```

All 21 checks pass, and the script prints the 69%-match table with the reasoning.
