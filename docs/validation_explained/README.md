# Validation, Explained (for beginners)

This folder explains — in plain language, with analogies — **what "validation" means
for Materia, why we do it, and exactly what every file does.** If you have never run a
scientific validation before, start here, then read the per-tier files:

- [`T1_explained.md`](T1_explained.md) — ML-potential accuracy (the headline)
- [`T2_explained.md`](T2_explained.md) — structure-tool correctness
- [`T3_explained.md`](T3_explained.md) — VASP input fidelity

> The **plan** lives in `docs/VALIDATION_PLAN.md`. The **raw results** live in
> `docs/validation_results/`. This folder is the **teaching companion** to both.

---

## 1. What is "validation," really?

**Analogy: a new kitchen scale.**
You buy a scale and want to trust it. You don't just *hope* it's right — you put a
known **1 kg reference weight** on it and check that it reads 1 kg. If it reads 1.03 kg,
you now know it's off by 3% and can decide whether that's good enough.

Validation is exactly that, for software:

> Give the system inputs where we **already know the correct answer**, then measure
> **how far off** the system is.

Materia is a tool that (a) builds crystal structures, (b) writes input files for the
DFT simulation program VASP, and (c) runs **machine-learning potentials** (fast
approximations of physics) to predict material properties. For each of those jobs we
need a trustworthy "1 kg reference weight" to check against.

## 2. Where do we get the "correct answers" (the reference weights)?

This is the clever part of the plan. We use **three different sources of truth**, one
per tier:

| Tier | What we test | The "1 kg reference weight" (ground truth) |
|------|--------------|--------------------------------------------|
| **T1** | ML-potential predictions of real material properties | **Materials Project** — a giant public database of properties computed with slow, accurate DFT |
| **T2** | The structure-building tools (supercell, slab, vacuum…) | **pymatgen** — the trusted, widely-used materials-science library, used as an independent re-derivation |
| **T3** | The VASP input files we generate | **pymatgen's MPRelaxSet** — the field-standard recipe for VASP inputs |

**Key insight:** Materia does **not** run DFT itself (DFT is enormously expensive). So
we can't "check our DFT against real DFT." Instead we compare our **fast ML-potential
predictions** against DFT answers that **someone else already computed and published**
(Materials Project). That completely sidesteps the "we don't run DFT" limitation —
*for validation purposes we don't need to.*

## 3. The two kinds of test, and why they feel different

There are two flavours of validation here, and it helps to know which is which:

### (a) Deterministic checks — T2 and T3
**Analogy: checking a calculator's "2 + 2".**
There is exactly **one** right answer. If `make_supercell` doubles a cell, the atom
count **must** be exactly 2× — no "close enough." These are **pass/fail** unit tests.
A failure is a *definite bug*. We wrote these as a **pytest** suite (see below) so they
also become a permanent safety net: anyone who breaks a tool later gets an instant red ✗.

### (b) Accuracy measurements — T1
**Analogy: checking a weather forecast.**
There is no single "pass/fail" — a forecast of 21°C when it's actually 22°C isn't
"wrong," it's "off by 1°C." ML potentials *approximate* physics, so we don't expect
zero error; we **measure** the error and report it as a number (e.g. "2.65% average
volume error"). The goal is an honest, reproducible **number**, not a green checkmark.

## 4. The vocabulary you'll meet (quick glossary)

- **DFT (Density Functional Theory):** the slow, accurate "gold standard" physics
  simulation. Think: the meticulous master chef who takes 6 hours per dish.
- **ML potential (MLP):** a machine-learning model trained to *imitate* DFT, but
  ~1,000,000× faster. Think: a line cook who learned from the master and plates a dish
  in seconds — usually almost as good. Materia ships 6 of them (4 MACE + 2 MatterSim).
- **Materials Project (MP):** free public database of DFT-computed properties for
  ~150,000 materials. Our reference answers for T1/T3.
- **pymatgen:** the standard Python materials-science library. Our reference for T2/T3.
- **pytest:** a tool that runs lots of small `assert` checks and reports pass/fail.
  Our deterministic test runner.
- **Relaxation:** letting a structure "settle" into its lowest-energy shape, like a
  ball rolling to the bottom of a bowl. We compare the settled shape to MP's.
- **MAE (Mean Absolute Error):** average size of the mistakes, ignoring direction.
  "On average we're off by X."
- **Parity plot:** predicted-vs-true scatter plot. Perfect predictions land on the
  diagonal `y = x` line. The closer to the line, the better.

## 5. How it's organised on disk

```
docs/
├── VALIDATION_PLAN.md            ← the plan / strategy (what & why)
├── validation_results/           ← the OUTPUTS (numbers, tables, plots)
│   ├── T1_mlp_accuracy.md/.csv   ← 6-model × 10-material accuracy table
│   ├── T1_volume_parity.png      ← parity plots
│   ├── T1_bulkmod_parity.png
│   ├── T2_structure_tools.md     ← pass/fail summary
│   └── T3_vasp_inputs.md
└── validation_explained/         ← YOU ARE HERE (the teaching companion)

backend/
├── tests/validation/             ← the deterministic pytest suite (T2 + T3)
│   ├── conftest.py
│   ├── test_structure_tools.py   ← T2
│   └── test_vasp_inputs.py       ← T3
└── scripts/validation/           ← the runnable measurement harnesses (T1 + T3)
    ├── t1_mlp_accuracy.py        ← T1: relax + EOS + compare to MP
    ├── t1_analyze.py             ← T1: turn results into report + plots
    └── t3_potcar_mp_diff.py      ← T3: compare our POTCAR labels to MP's
```

**Why two different places (`tests/` vs `scripts/`)?**
- `tests/` = deterministic pass/fail → run with `pytest`, meant to run forever as a
  regression net.
- `scripts/` = measurements that take real compute (load models, run physics) → run
  by hand when you want fresh numbers.

## 6. How to run everything

```bash
# Deterministic checks (T2 + T3) — fast, no GPU needed:
cd backend && ../venv/bin/python -m pytest tests/validation/

# T1 accuracy measurement — needs the ML models + MP API key (already in backend/.env):
cd backend && ../venv/bin/python scripts/validation/t1_mlp_accuracy.py   # pilot
../venv/bin/python scripts/validation/t1_analyze.py                       # report+plots

# T3 POTCAR-vs-MP label diff:
cd backend && ../venv/bin/python scripts/validation/t3_potcar_mp_diff.py
```

Now read the per-tier files for the details. 👇
