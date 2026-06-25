# T2 — Structure-Tool Correctness, Explained

**The "does the machine build exactly what it claims?" tier.**

> Read [`README.md`](README.md) first if you haven't. Raw output:
> `docs/validation_results/T2_structure_tools.md`. Test code:
> `backend/tests/validation/test_structure_tools.py`.

---

## 1. The one-sentence idea

> For each structure-building tool (make a supercell, cut a slab, add vacuum, …), build
> something with a **known correct answer** and assert the tool produced **exactly** that.

## 2. Why this is different from T1 (deterministic vs measured)

T1 *measured* an error (a forecast can be "off by 1°C"). T2 is **pass/fail** — there's
only one right answer.

**Analogy: checking a photocopier's "enlarge to 200%".**
If you copy a page at 200%, the result **must** be exactly twice as wide and twice as
tall. "Roughly double" is a defect. Structure tools are the same: if you ask for a 2×2×2
supercell of an 8-atom cell, you **must** get exactly 64 atoms. So these checks are
binary: ✅ correct or ❌ bug. No grey area.

## 3. What is the "ground truth" here?

We use **pymatgen** — the standard, battle-tested materials library — as an independent
referee. Two ways:
1. **Math we can compute by hand.** A 2×2×1 supercell *must* have 4× the atoms — we just
   assert that number directly.
2. **pymatgen's own functions.** For round-trips and slab geometry we parse the result
   back with pymatgen and check it matches.

It's like checking your arithmetic two ways: once in your head, once on a calculator you
trust.

## 4. The tools we check, with analogies

| Tool | What it does | Analogy | What we assert |
|------|--------------|---------|----------------|
| `make_supercell` | tiles the crystal into a bigger block | stacking identical LEGO bricks into a wall | atom count = n× original; cell vectors scaled correctly |
| `add_vacuum` | adds empty space above a surface | leaving headroom above a sandwich in a lunchbox | the empty gap equals *exactly* the thickness asked for |
| `make_slab` | cuts a thin surface slice from the bulk | slicing a precise number of layers off a block of cheese | **exactly** the requested number of atomic layers |
| `add_adsorbate` | places a molecule onto a surface | setting a cup *on top of* a table (not inside it) | molecule sits **above** the surface, never buried |
| `generate_sqs` | turns an ordered crystal into a realistic random alloy recipe | mixing two colours of sand in a set ratio | the resulting composition matches the target fractions |
| `convert_structure` | saves the crystal in different file formats | saving a doc as PDF, then Word, then back | the structure survives the round-trip unchanged |

## 5. A few core concepts you'll see

### "Supercell" and why atom count is the giveaway
A crystal is a tiny repeating unit tiled infinitely. A **supercell** just bundles several
copies into one bigger box. If you bundle a 2×2×1 block, you have `2×2×1 = 4` copies, so
**4× the atoms**. Counting atoms is the simplest, most reliable correctness check.

### "Slab" and "layers" (the tricky one)
To study a *surface*, you slice the infinite crystal and leave vacuum on top — that slice
is a **slab**. Users think in **atomic layers** ("give me a 4-layer slab"). Counting
layers correctly is surprisingly fiddly (atoms can wrap around the box edge), so we
explicitly assert that a requested 4-layer slab really has 4 distinct atomic planes.

### "Adsorbate" (where we found a bug — see §6)
An **adsorbate** is a molecule stuck onto a surface (e.g. CO on copper — the heart of
catalysis). The molecule must sit **on top** of the surface at a sensible height.

### "SQS" (Special Quas-random Structure)
Real alloys mix elements randomly on the same sites — but a computer cell needs each site
to be one definite element. An **SQS** is a clever small cell that *statistically mimics*
true randomness. We check the substitution math (e.g. "replace 25% of the Si") produces
the right composition. (The full SQS search needs special tools that only live in the
Docker image, so locally we test just the math part.)

## 6. The bug we caught (this is why validation pays off)

**Symptom:** when we placed a CO molecule on a copper slab, the carbon atom ended up at
height 13.77 Å — but the slab's *top* was at 14.42 Å. **The molecule was buried *inside*
the metal**, like setting a cup *through* a table instead of on it.

**Why it happened:** our `make_slab` trims layers off the top, which makes the slab
**lopsided** (top and bottom surfaces differ). The placement code asked pymatgen for
candidate spots and just took "the first one" — but that list wasn't sorted by height, so
"the first one" could be a spot on the *bottom* face. Result: buried molecule.

**The fix:** sort the candidate spots by height and always take the **topmost** one. Now
the molecule reliably lands on top.

**The lesson (and the whole point of T2):** this bug would have silently produced wrong
surface-chemistry inputs for *every* adsorption study. A human eyeballing one result
might not notice. An automated check that asserts "molecule must be above the surface"
catches it instantly — and forever, because the test stays in the suite.

> Full write-up: `docs/issues_solve/2026-06-25-adsorbate-buried-in-asymmetric-slab.md`.

## 7. The files that make T2 work

### `backend/tests/validation/test_structure_tools.py` — the checks
A **pytest** file: a collection of small functions, each named `test_...`, each ending in
one or more `assert` statements ("this must be true"). pytest runs them all and prints a
green dot for each pass, a red ✗ for each fail. We have **23 checks** here. Example logic:
"make a 2× supercell of copper → assert the atom count is exactly 8× the original."

### `backend/tests/validation/conftest.py` — shared setup
`conftest.py` is a pytest convention: a place for **shared fixtures** (reusable test
ingredients). Ours does two things:
1. Adds the backend folder to the import path so `import app...` works.
2. Provides ready-made reference crystals (`cu_fcc`, `si_diamond`, `nacl`) that many
   tests reuse — like prepping common ingredients once instead of in every recipe.

**Analogy:** `conftest.py` is the *mise en place* (pre-chopped ingredients) and
`test_structure_tools.py` is the recipe cards that use them.

## 8. How to run it

```bash
cd backend
../venv/bin/python -m pytest tests/validation/test_structure_tools.py -v
```

You'll see 23 checks pass. Because these are deterministic and fast, they double as a
permanent **regression net**: if someone later changes a structure tool and breaks it,
this suite turns red immediately — before the bug ever reaches a user.
