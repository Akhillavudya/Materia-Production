"""T3 helper — diff Materia's curated POTCAR labels against pymatgen MPRelaxSet.

Materia follows the *VASP-recommended* PAW set; the Materials Project uses its own
historical choices for database consistency. This prints a per-element match table
and an overall match rate so the deviations are documented (not hidden).

Run:  cd backend && ../venv/bin/python scripts/validation/t3_potcar_mp_diff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymatgen.io.vasp.sets import MPRelaxSet  # noqa: E402

from app.services.vasp.potcar import _RECOMMENDED  # noqa: E402

# Tier-1 + common elements (docs/VALIDATION_PLAN.md §2.1, plus a metal/oxide spread).
ELEMENTS = ["Si", "Al", "Cu", "Fe", "Mg", "O", "Na", "Cl", "C", "Ga", "As",
            "Ti", "Zn", "Ni", "Co", "Mn"]


def main() -> None:
    mp = MPRelaxSet.CONFIG["POTCAR"]
    rows, n_match = [], 0
    for el in ELEMENTS:
        materia = _RECOMMENDED.get(el, (el,))[0]
        mp_label = mp.get(el, "?")
        ok = materia == mp_label
        n_match += ok
        rows.append((el, materia, mp_label, "match" if ok else "DEVIATION"))

    w = max(max(len(r[1]) for r in rows), len("Materia")) + 2
    print(f"{'EL':<4}{'Materia':<{w}}{'MP':<{w}}STATUS")
    print("-" * (8 + 2 * w))
    for el, m, p, status in rows:
        print(f"{el:<4}{m:<{w}}{p:<{w}}{status}")
    print("-" * (8 + 2 * w))
    print(f"Match rate: {n_match}/{len(rows)} = {100*n_match/len(rows):.0f}%")
    print("\nDeviations are intentional: Materia uses the VASP-recommended PAW set,")
    print("MP uses its own (often *_pv) choices for database self-consistency.")


if __name__ == "__main__":
    main()
