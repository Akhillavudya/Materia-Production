# T1 — ML-Potential Accuracy, Explained

**The headline tier.** This is the result that makes Materia publishable.

> Read [`README.md`](README.md) first if you haven't. Raw outputs:
> `docs/validation_results/T1_mlp_accuracy.{md,csv}` + the two `*_parity.png` plots.

---

## 1. The one-sentence idea

> Take 6 ML potentials, ask each to predict two properties (equilibrium **volume** and
> **bulk modulus**) for 10 real materials, and measure how far each prediction is from
> the trusted **Materials Project DFT** answer.

## 2. Why this matters (the big analogy)

**Analogy: hiring 6 fast cooks and comparing them to a master chef.**

- The **master chef** = DFT (slow, accurate, the gold standard). The Materials Project
  is a cookbook of dishes the master chef already made and photographed.
- The **6 fast cooks** = our ML potentials (MACE ×4, MatterSim ×2). They each learned
  to imitate the master chef and cook in *seconds* instead of *hours*.
- **Validation** = for 10 known dishes, we let each cook make the dish, then compare
  their plate to the master chef's published photo. How close did they get?

If the fast cooks are consistently close, you can trust them for new dishes too — which
is the whole point of using a fast approximation.

## 3. The two properties we measure (and what they mean)

### (a) Equilibrium volume per atom — "what size does the crystal want to be?"
**Analogy: a memory-foam mattress finding its natural thickness.**
Every crystal has a preferred size where its atoms are most comfortable (lowest energy).
We let the ML potential "settle" the crystal (this is **relaxation** — see §5) and read
off the final volume per atom. Then we compare to MP's settled volume.

- Metric: **% volume deviation** = `100 × (ours − MP) / MP`.
- A `+2%` means our crystal came out 2% too big; `−2%` too small.

### (b) Bulk modulus — "how hard is it to squeeze?"
**Analogy: how stiff is a spring / how hard is the rubber.**
Bulk modulus (symbol *K*, units **GPa**) measures resistance to being compressed.
Diamond is very stiff (~440 GPa); table salt is soft (~24 GPa). We measure it by gently
squeezing and stretching the crystal and watching how the energy responds (the **EOS** —
see §6).

- Metric: **% bulk-modulus error** vs MP's DFT value.

## 4. The materials we chose (and why)

`Si, Al, Cu, Fe, MgO, NaCl, C(diamond), GaAs, TiO2, ZnO`

We deliberately picked a **spread of material types** so the test isn't accidentally
easy: metals (Al, Cu, Fe), a semiconductor (Si, GaAs), an ionic salt (NaCl), oxides
(MgO, TiO2, ZnO), and a covalent network (diamond). It's like testing a translator on
several languages, not just one.

> **Important subtlety — carbon.** If you ask "what's the ground state of carbon?" the
> real answer is **graphite**, not diamond. But graphite has weak van-der-Waals layers
> that universal ML potentials model poorly — testing on it would be an *unfair* gotcha.
> So we **pinned carbon to diamond** (`C:mp-66`) for a fair comparison. This kind of
> honest choice is exactly what good validation looks like.

## 5. What "relaxation" actually does (core concept)

**Analogy: a ball rolling to the bottom of a bowl.**
Atoms feel forces, like a ball feels gravity. "Relaxation" repeatedly nudges every atom
(and the cell shape/size) **downhill in energy** until the forces are nearly zero — the
ball has reached the bottom of the bowl and stops. That resting configuration is the
material's natural shape, and its volume is what we compare to MP.

- We stop when the largest leftover force is below **0.02 eV/Å** (`fmax`) — "close
  enough to the bottom of the bowl."
- We use the **exact same relaxation method the Materia app uses** (`FrechetCellFilter`
  + the `FIRE` optimizer), so we're validating the real product, not a toy.

## 6. What the "EOS" is (core concept for bulk modulus)

**EOS = Equation of State.** To find stiffness, you can't just look at one volume — you
need to see how the energy *changes* as you squeeze.

**Analogy: testing a spring by pushing it to several lengths.**
We take the relaxed crystal and make 7 copies at slightly different volumes (−5% to +5%),
measure each copy's energy, and get an energy-vs-volume curve. The **curvature** of that
curve at the bottom *is* the bulk modulus. We fit a standard physics formula to it
(the **Birch–Murnaghan** equation) to read off *K*.

- A **steep, narrow** curve = stiff material (high K).
- A **shallow, wide** curve = soft material (low K).

## 7. The results, in plain language

Across all **60 runs (6 models × 10 materials), every one converged**:

- **Mean volume error ≈ 2.65%** → the cooks get the *size* of the dish right to within a
  few percent. This is the trustworthy headline.
- **Mean bulk-modulus error ≈ 8.3%** → stiffness is harder and noisier.

### Three signals worth understanding (this is the "learning" part)

1. **Volumes are slightly too big, consistently.** Almost all models *over-expand*
   crystals by a small amount. That's a **known, well-documented bias** of universal ML
   potentials — not a Materia bug. A consistent bias is actually a *good* sign (it's
   predictable), versus random scatter.

2. **Bulk modulus is noisier than volume — and that's expected.** Volume is a single
   point (the bottom of the bowl). Bulk modulus is the *curvature* of a curve, and
   curvature amplifies tiny wiggles. Think of it like measuring a hill's *height*
   (easy) vs its *steepness at one exact spot* (sensitive to small bumps). So a model
   can nail the volume but still miss K.

3. **Iron (Fe) is the troublemaker.** Fe is **magnetic**, and magnetism makes the
   energy landscape tricky. One model (`mace-mp-0b3`) got Fe's bulk modulus badly wrong
   (60 GPa vs the true 207). This is a **real, publishable finding**: "be cautious using
   these potentials for magnetic systems' elastic properties." Validation didn't just
   produce a number — it produced *advice*.

### Is this overfitting or underfitting?
**Neither applies here, and it's worth knowing why.** Overfitting/underfitting are about
*training* a model on data. These 6 potentials were **already trained** by other teams;
we're testing them **zero-shot** (no training, no tuning) on materials they must handle
in the wild. So what we're really measuring is **transferability** — how well their
training generalises to our test set. Verdict: **good for geometry, fair for stiffness.**

## 8. The parity plots (how to read them)

Open `docs/validation_results/T1_volume_parity.png`.

**Analogy: a dartboard where the bullseye is a diagonal line.**
- The **x-axis** is the true (MP) value; the **y-axis** is our prediction.
- The dashed `y = x` line is "perfect."
- Each dot is one (model, material) prediction. **Dots on the line = perfect; above the
  line = we over-predicted; below = we under-predicted.**
- In the volume plot the dots **hug the line tightly** → strong agreement. In the
  bulk-modulus plot they scatter more → the noisier property.

## 9. The files that make T1 work

### `backend/scripts/validation/t1_mlp_accuracy.py` — the measurement engine
This is the script that *does the experiment*. Step by step, it:
1. **Reads the MP API key** from `backend/.env`.
2. For each material, **pulls the MP reference** (`fetch_mp_reference`): the ground-state
   structure, its volume/atom, and its DFT bulk modulus. (It picks the most stable
   polymorph automatically, unless we pin one like `C:mp-66`.)
3. For each model, **relaxes** the structure and runs the **EOS** (`relax_and_eos`) using
   the real app calculator (`get_calculator`) and the real relaxation method.
4. **Computes the deviations** (% volume, % bulk modulus) and writes a CSV + a basic
   markdown table.

Think of this file as the **lab technician** who runs every sample through the machine
and writes the raw numbers in a notebook (the CSV).

### `backend/scripts/validation/t1_analyze.py` — the report writer
This reads the raw CSV and turns it into something a human (or a paper reviewer) can
read: per-model averages, the "which model when" recommendation, and the two **parity
plots** (using matplotlib). It also writes the plain-language signals section.

Think of this file as the **analyst** who takes the technician's notebook and makes the
charts and the summary slide.

> Why split into two scripts? Running the experiment is **slow** (loads models, runs
> physics on the GPU). Making charts is **instant**. Splitting them means you can
> re-style the report or re-plot a hundred times without re-running the expensive physics.

### What they reuse from the real app (so we test the real thing)
- `app.services.simulation.calculator_factory.get_calculator` — loads the actual MACE /
  MatterSim potentials the product uses.
- `FrechetCellFilter` + `FIRE` — the actual relaxation recipe from
  `app/services/simulation/optimization.py`.

This matters: we're validating **Materia's real engine**, not a separate reimplementation
that might behave differently.

## 10. How to reproduce

```bash
cd backend
# Pilot (fast sanity check — 1 model, 3 materials):
../venv/bin/python scripts/validation/t1_mlp_accuracy.py --models mace --materials Si,Cu,MgO

# Full run (6 models × 10 materials):
../venv/bin/python scripts/validation/t1_mlp_accuracy.py \
  --models mace,mace-mpa,mace-omat,mace-matpes,mattersim,mattersim-v1.0.0-5M \
  --materials Si,Al,Cu,Fe,MgO,NaCl,C:mp-66,GaAs,TiO2,ZnO

# Build the report + parity plots from the CSV:
../venv/bin/python scripts/validation/t1_analyze.py
```

**Gotchas we already hit (so you don't have to):**
- The MatterSim-5M alias is `mattersim-v1.0.0-5M` (or `"mattersim 5m"` with a space),
  **not** `mattersim-5m`.
- `FrechetCellFilter` lives in `ase.filters` in this ASE version.
- A GPU (CUDA) makes each relaxation take ~0.1–1.3 s; on CPU it's slower but still fine.
