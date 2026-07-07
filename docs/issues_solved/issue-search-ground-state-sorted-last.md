# issue-search-ground-state-sorted-last

## Symptom
A formula search in Materia returned the right polymorphs but in the **wrong order**
compared with the Materials Project website. For `LiCoO2`, MP lists the ground state
`mp-22526` (energy above hull = 0) **first**; Materia listed it **last** (position 8–9
of 9). The results table also showed a **formation energy** column, whereas the user
wanted MP's **Energy Above Hull (eV/atom)** column.

## Root cause (why the bug came)
Two separate problems:

1. **Falsy-zero sort bug.** The MP provider sorted polymorphs by stability with:

   ```python
   docs_sorted = sorted(docs, key=lambda d: d.energy_above_hull or 999)
   ```

   In Python `0.0 or 999` evaluates to `999` because `0.0` is falsy. The ground
   state has `energy_above_hull == 0.0` exactly, so its sort key became `999` and it
   was pushed to the **end** of the list — the opposite of "most stable first". Every
   material with a nonzero hull sorted ahead of the true ground state.

2. **Wrong display column.** The agent system prompt instructed the model to render
   the search table with columns `(id, formula, crystal system, source, band gap,
   formation energy)`. The data already carried `energy_above_hull_eV_per_atom`, but
   the prompt never asked for it, so the model showed formation energy instead — not
   matching MP.

## How we fixed it
1. Explicit `None` check in the sort key so a real `0.0` keeps its value and only a
   truly missing hull falls back to `999`:

   ```python
   docs_sorted = sorted(
       docs,
       key=lambda d: (d.energy_above_hull
                      if d.energy_above_hull is not None else 999))
   ```

2. Updated the search-formatting instruction in the system prompt to show
   `band gap (eV), energy above hull (eV/atom)` using the
   `energy_above_hull_eV_per_atom` field (0 = on the convex hull), to keep the tool's
   stability order, and to **not** show formation energy — mirroring Materials Project.

The full-polymorphs CSV was left unchanged: it still records **both** the hull and the
formation energy, so nothing is lost for users who want formation energy.

## Files changed
- `backend/app/services/search/providers/mp.py` — fixed the falsy-zero sort key.
- `backend/app/agent/graph.py` — search-table column instruction now uses energy
  above hull instead of formation energy.

## How to verify
- Unit-level: sorting the screenshot's hull values
  `[0.0, 0.005, 0.04, 0.04, 0.05, 0.09, 0.21, 1.51, None]` now puts the `0.0` entry
  **first** and the `None` entry **last** (previously the `0.0` entry landed at
  position 8).
- End-to-end: search `LiCoO2`. The table is ordered `mp-22526 (0)` →
  `mp-849273 (~0)` → `mp-853240 (0.04)` → … and shows an **Energy above hull
  (eV/atom)** column, matching the MP Materials Explorer order.

## Lesson
Never use `x or default` to supply a fallback for a numeric value that can legitimately
be `0` (or `0.0`, or an empty string) — `0` is falsy, so the fallback fires when the
value is actually the most meaningful one. Use `x if x is not None else default`. Here
the "most stable" material is exactly the one with hull `0.0`, so the falsy-zero trap
silently inverted the ranking the user cares about most.
