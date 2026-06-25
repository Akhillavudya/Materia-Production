# Materia — Pre-Deployment Validation Plan

**Status:** In progress — **T1 ✅ + T2 ✅ + T3 ✅ done** (2026-06-25); T4/T5 pending
**Created:** 2026-06-25

**Progress log:**
- 2026-06-25 — T1 (ML-potential accuracy, HEADLINE): **6 models × 10 materials = 60
  relaxations, all converged.** Mean |volume deviation| = **2.65%**, mean |bulk-modulus
  error| = **8.3%** vs Materials Project DFT. Best geometry: mace-omat (2.38%); best
  bulk modulus: mattersim-1M (3.7%). Harness `backend/scripts/validation/t1_mlp_accuracy.py`
  + analysis `t1_analyze.py`; results + 2 parity plots in `docs/validation_results/T1_*`.
  (Pilot run first per user, then scaled.) Ran on GPU/CUDA (~0.1–1.3 s/relax).
- 2026-06-25 — T2 (structure-tool correctness): 23/23 pass, suite at
  `backend/tests/validation/test_structure_tools.py`, results in
  `docs/validation_results/T2_structure_tools.md`. **1 real bug found & fixed**
  (adsorbate buried in asymmetric slabs — see `docs/issues_solve/2026-06-25-adsorbate-buried-in-asymmetric-slab.md`).
- 2026-06-25 — T3 (VASP input fidelity): 21/21 pass, suite at
  `backend/tests/validation/test_vasp_inputs.py`, results in
  `docs/validation_results/T3_vasp_inputs.md`. ENCUT matches MPRelaxSet (520);
  POTCAR labels 69% match to MP (deviations are the intentional VASP-recommended set).
- Test net (Step-9-lite) now exists: `cd backend && ../venv/bin/python -m pytest tests/validation/` → 44 passed.
- pytest added to the venv. Next: T1 (ML-potential accuracy, needs MP_API_KEY — present in backend/.env).
**Purpose:** Produce original, reproducible validation evidence for Materia before public/lab deployment and as the experimental backbone of the Materia paper.

---

## 0a. Build-order decision (2026-06-25) — READ FIRST

**Question raised:** before building a desktop app for power users, do validation + production
steps 6–9 first, or build the desktop app now?

**Decision: do validation first, then only the hardening actually needed for the web launch.
Do NOT build the desktop app yet — it is LAST.**

Locked sequence:

| # | Do this | Why now |
|---|---------|---------|
| 1 | **Validation T1–T5** (this doc) | Blocks the paper; independent of everything else; surfaces tool/potential bugs before more is built on top |
| 2 | **Step 9 tests / CI** (at least Step-9-lite) | Validation T2 + T3 *are* these tests — built nearly for free while validating |
| 3 | **Production steps 6, 7, 8** (global error handling, health/observability, CORS/security headers) | Only for the surface actually launching — the **web** lab app |
| 4 | **Desktop app** | Last. On a validated + tested + hardened base |

**Rationale (3 reasons):**
1. **Paper is the critical path.** The launch is private/lab-only *because a paper is being
   published*. Only validation unblocks the paper; the desktop app contributes nothing to it.
2. **Desktop was already deferred** (decision 2026-06-18, memory `desktop-deferred-web-only` —
   stay web-only, defer local-compute). Nothing has changed that. It was always "eventually,"
   not a launch blocker.
3. **No test net yet.** A desktop app is a major architecture shift (compute moves from server
   to each user's machine). Building the biggest change with zero tests is the trap the
   production-readiness notes warned about ("build a minimal test net FIRST").

**Two key insights:**
- Steps 6–8 are **web-deployment** hardening (CORS, security headers, health, server error
  handling). Much of it changes or doesn't apply to a desktop target → hardening before desktop
  then building desktop = re-hardening a new surface. So desktop goes last.
- **Validation T2 + T3 ARE Step 9 tests.** Running structure-tool correctness + VASP-input
  fidelity checks simultaneously builds the test net → steps 1 and 2 above are largely the same
  work; do them together.

Cross-refs: memory `production-readiness-steps.md` (steps 6–10 definitions),
`desktop-deferred-web-only.md`.

---

## 0. Why this exists

Materia is a working system but has **no published validation numbers**. The two closest
reference tools — **Masgent** (single-agent VASP+MLP, *Digital Discovery* 2026) and
**ChatMat** (multi-agent autonomous DFT) — both report benchmarks, which is what makes
them credible. To be publishable and deployable with confidence, Materia needs its own
**independent** validation results.

> **Originality note:** Reusing the *method* ("validate ML potentials against Materials
> Project reference values") is standard scientific practice, NOT plagiarism. We generate
> our own numbers, our own materials set, our own tables. We do not copy any text,
> figures, or exact case-study setups from Masgent/ChatMat. See memory:
> `ref-paper-masgent.md`, `ref-paper-chatmat.md`.

### Key enabling insight
Materia does **not** run DFT itself (it generates VASP inputs + runs pretrained ML
potentials). We do **not** need to run DFT to validate: we compare our ML-potential
predictions against **already-published DFT / Materials Project reference values** (free
via the MP API). This sidesteps the "no DFT" limitation entirely for validation purposes.

---

## 1. Validation tiers (strongest → easiest)

| Tier | Validates | Method | Metric | Effort | Paper value |
|------|-----------|--------|--------|--------|-------------|
| **T1. ML-potential accuracy** ⭐ | The 6 potentials (MACE ×4, MatterSim 1M/5M) vs Materials Project | Pull MP reference structures + props via API; run each potential; compare | MAE (meV/atom), % volume deviation, bulk modulus error | Medium | **Headline** |
| **T2. Structure-tool correctness** | make_supercell / make_slab / add_vacuum / generate_sqs / add_adsorbate produce exactly what is claimed | Compare against pymatgen ground truth (deterministic) | Pass/fail, atom counts, layer counts, composition, vacuum thickness | Low | Supporting |
| **T3. VASP input fidelity** | Generated INCAR / KPOINTS / POTCAR are correct | Diff against pymatgen `MPRelaxSet` / `MPStaticSet`; check k-point density vs requested kppa | Match %, k-density error | Low | Supporting |
| **T4. Agent reliability** ⭐ | LLM picks the right tool with the right args from NL prompts | Curated prompt suite → inspect tool call + args | Tool-selection accuracy, task success rate, per-provider (Groq/Gemini/Ollama) | Medium | **Differentiator** |
| **T5. Performance / speedup** | MLP wall-time vs system size | Time runs at 8 → 1024 atoms | Speedup ratio, scaling curve | Low | Supporting |

⭐ = the two tiers where Materia can produce results the reference papers do **not** have.

---

## 2. Tier 1 — ML-potential accuracy (HEADLINE)

### 2.1 Materials set (proposed)
Simple, well-characterized systems with reliable MP reference data:
`Si, Al, Cu, Fe, MgO, NaCl, diamond C, GaAs, TiO2, ZnO` (expand to ~15–20 if time allows).
Include a spread: metals, semiconductors, ionic, oxides.

### 2.2 Properties to compare
1. **Equilibrium lattice constant / volume** (relax → compare to MP)
2. **Equation of state (EOS)** → bulk modulus (Birch–Murnaghan fit)
3. **Formation energy** (where MP reference exists)
4. **Elastic constants** (subset, reuse existing elastic tool)

### 2.3 Metrics (report per model, per material, + aggregate)
- Energy MAE in **meV/atom** (target context: Masgent reported <~100 meV/atom for MLPs, EOS within 0.05 eV/atom)
- **% volume deviation** (Masgent context: <1%)
- Bulk modulus % error vs MP/experiment

### 2.4 Deliverable
- A **6-model × N-material comparison table** (this is the novel artifact — neither
  reference paper benchmarks this many potentials side by side).
- One scatter/parity plot (predicted vs MP reference) per property.
- A short "which model to use when" recommendation paragraph.

### 2.5 Implementation notes
- Needs a **Materials Project API key** (free; register at materialsproject.org). CONFIRM AVAILABILITY before starting.
- Reuse existing `backend/app/services/simulation/` job code for relax/EOS/elastic.
- Harness location (proposed): `backend/scripts/validation/t1_mlp_accuracy.py` → emits CSV + markdown table to `docs/validation_results/`.

---

## 3. Tier 2 — Structure-tool correctness (quick wins)

Deterministic unit-test style checks against pymatgen ground truth:
- `make_supercell` → atom count == n × original; lattice scaled correctly
- `make_slab` → exact layer count (watch the `in_unit_planes` / `lll_reduce` gotcha), correct vacuum
- `add_vacuum` → vacuum thickness matches request
- `generate_sqs` (incl. partial substitution `Si->S:0.25`) → composition matches target
- `add_adsorbate` → adsorbate placed at correct site/height
- `convert_structure` → round-trip POSCAR↔CIF↔XYZ preserves structure

**Deliverable:** a pass/fail table + pytest suite at `backend/tests/validation/test_structure_tools.py`.

---

## 4. Tier 3 — VASP input fidelity

- Diff generated INCAR/KPOINTS/POTCAR against pymatgen `MPRelaxSet` / `MPStaticSet` for the Tier-1 materials.
- Verify `generate_kpoints` density (kppa Low/Med/High) matches the realized k-mesh.
- Verify POTCAR element ordering / functional selection matches POSCAR.

**Deliverable:** match-rate table; list of any intentional deviations (and why).

---

## 5. Tier 4 — Agent reliability (DIFFERENTIATOR)

The thing neither paper rigorously measures: does the **natural-language → correct-tool**
mapping actually work, and how does it vary across the free Groq → Gemini → Ollama stack?

### 5.1 Build a prompt benchmark
- ~30–50 curated NL prompts, each with a known-correct expected tool + key args.
- Mix: single-tool requests, multi-tool workflows (exercise the plan→confirm gate),
  ambiguous prompts (should ask for clarification), and adversarial/out-of-scope prompts.

### 5.2 Metrics
- **Tool-selection accuracy** (right tool chosen)
- **Argument correctness** (right args extracted)
- **Task success rate** (end-to-end produces valid output)
- Break down **per provider** (Groq vs Gemini vs Ollama) → supports the "free stack works" claim.

**Deliverable:** accuracy table per provider; failure taxonomy.

---

## 6. Tier 5 — Performance / speedup

- Time each potential on increasing supercell sizes (8 → 1024 atoms).
- Report wall-time scaling + speedup framing vs DFT cost estimates.

**Deliverable:** scaling curve + table.

---

## 7. Suggested execution order

1. **T2 + T3** first — fast, deterministic, builds confidence and catches regressions. (Low effort, do in one sitting.)
2. **T1** — the headline; needs MP API key. Allocate the most time here.
3. **T4** — the differentiator; build the prompt suite incrementally.
4. **T5** — quick, run last alongside T1 jobs.

---

## 8. Prerequisites / open items

- [ ] Materials Project API key available? (required for T1, T3 references)
- [ ] Decide final materials set size (10 vs 20)
- [ ] Confirm all 6 potentials currently runnable (MatterSim float32 fix already landed — see memory)
- [ ] Create `docs/validation_results/` for output tables/plots
- [ ] Create `backend/scripts/validation/` for harnesses

---

## 9. What this buys us vs the reference tools

- **vs Masgent:** neutralizes its main lead (published benchmarks) and adds a *broader*
  6-model comparison they don't have. (Still note: Masgent has SLURM script generation +
  ML training utilities we lack — separate roadmap items, not validation.)
- **vs ChatMat:** T4 agent-reliability numbers + the free-LLM-stack angle are original
  contributions; ChatMat's edge (actually running DFT) remains a roadmap item, not a
  validation gap.

> Cross-refs: memory `ref-paper-masgent.md`, `ref-paper-chatmat.md`, `production-readiness-steps.md`.
