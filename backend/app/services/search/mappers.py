"""Raw provider records → unified `MaterialCard` (redesign §7).

The single place where each source's idiosyncratic fields are normalised:
energies to eV / eV-per-atom, missing values to ``None`` (never ``0`` or the
string ``"None"``), and identity to the canonical ``<source>-<id>`` form.
"""

from __future__ import annotations

import re

from app.domain.material_card import Dimensionality, MaterialCard, Source


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value) -> bool | None:
    """Coerce assorted truthy/falsey representations to a real bool or None.

    Fixes the C2DB bug where ``magnetic`` was stored as ``str(None)`` / ``"True"``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    if s in ("none", ""):
        return None
    return None


# ── Materials Project ─────────────────────────────────────────────────────────

def mp_doc_to_card(doc) -> MaterialCard:
    mid = str(doc.material_id)
    elements = [str(e) for e in (doc.elements or [])]
    return MaterialCard(
        id=mid,                                   # already "mp-19306"
        source=Source.MP,
        source_id=mid,
        formula=doc.formula_pretty or "",
        elements=elements,
        dimensionality=Dimensionality.BULK,
        band_gap_eV=_to_float(doc.band_gap),
        formation_energy_eV_per_atom=_to_float(doc.formation_energy_per_atom),
        energy_above_hull_eV_per_atom=_to_float(doc.energy_above_hull),
        energy_per_atom_eV=_to_float(doc.energy_per_atom),
        spacegroup_symbol=(doc.symmetry.symbol if doc.symmetry else None),
        source_url=f"https://materialsproject.org/materials/{mid}",
    )


# ── C2DB (local ASE db row) ───────────────────────────────────────────────────

def c2db_row_to_card(row) -> MaterialCard:
    kv = row.key_value_pairs or {}
    atoms = row.toatoms()
    elements = sorted(set(atoms.get_chemical_symbols()))
    uid = kv.get("uid")
    return MaterialCard(
        id=f"c2db-{row.id}",                      # row id round-trips to refetch
        source=Source.C2DB,
        source_id=str(row.id),
        formula=row.formula,
        elements=elements,
        n_atoms=row.natoms,
        dimensionality=Dimensionality.LAYERED,
        band_gap_eV=_to_float(kv.get("gap")),
        formation_energy_eV_per_atom=_to_float(kv.get("hform")),
        energy_above_hull_eV_per_atom=_to_float(kv.get("ehull")),
        spacegroup_symbol=kv.get("international"),
        magnetic=_to_bool(kv.get("is_magnetic")),
        source_url=(f"https://cmrdb.fysik.dtu.dk/c2db/row/{uid}" if uid else None),
    )


# ── OQMD (REST item) ──────────────────────────────────────────────────────────

def oqmd_item_to_card(item, fallback_formula: str | None = None) -> MaterialCard:
    entry_id = item.get("entry_id") or item.get("id") or ""
    name = item.get("name") or item.get("composition") or fallback_formula or ""
    elements = sorted(set(re.findall(r"[A-Z][a-z]?", name)))
    return MaterialCard(
        id=f"oqmd-{entry_id}",
        source=Source.OQMD,
        source_id=str(entry_id),
        formula=name,
        elements=elements,
        dimensionality=Dimensionality.BULK,
        band_gap_eV=_to_float(item.get("band_gap")),
        formation_energy_eV_per_atom=_to_float(item.get("delta_e")),
        energy_above_hull_eV_per_atom=_to_float(item.get("stability")),
        spacegroup_symbol=item.get("spacegroup") or item.get("space_group"),
        source_url=f"https://oqmd.org/materials/entry/{entry_id}",
    )
