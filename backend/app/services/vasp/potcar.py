"""POTCAR spec generation (redesign §9, "VASP completeness").

POTCAR files are licensed and must never be shipped, so by default this emits a
human-readable ``POTCAR.spec`` instead: per element it lists the recommended PBE
PAW potential label, its valence electron count (ZVAL) and recommended plane-wave
cutoff (ENMAX), plus the implied ``ENCUT`` floor for the set.

A *real* ``POTCAR`` is assembled only when the deployment configures
``settings.pmg_vasp_psp_dir`` (a licensed PAW library); in that case ENMAX/ZVAL
are read from the authoritative files rather than the curated table below.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Curated VASP recommended PBE PAW potentials: element → (label, zval, enmax_eV).
# Labels and valence counts follow the VASP recommended ("_sv"/"_pv"/"_d") set;
# ENMAX values are the recommended plane-wave cutoffs published for those
# potentials (rounded to whole eV). Elements absent here degrade gracefully
# (bare-symbol label, unknown zval/enmax) rather than failing.
_RECOMMENDED: dict[str, tuple[str, int, float]] = {
    "H":  ("H", 1, 250.0),    "He": ("He", 2, 479.0),
    "Li": ("Li_sv", 3, 499.0), "Be": ("Be", 2, 248.0),
    "B":  ("B", 3, 319.0),    "C":  ("C", 4, 400.0),
    "N":  ("N", 5, 400.0),    "O":  ("O", 6, 400.0),
    "F":  ("F", 7, 400.0),    "Ne": ("Ne", 8, 344.0),
    "Na": ("Na_pv", 7, 260.0), "Mg": ("Mg", 2, 200.0),
    "Al": ("Al", 3, 240.0),   "Si": ("Si", 4, 245.0),
    "P":  ("P", 5, 255.0),    "S":  ("S", 6, 280.0),
    "Cl": ("Cl", 7, 262.0),   "Ar": ("Ar", 8, 266.0),
    "K":  ("K_sv", 9, 259.0),  "Ca": ("Ca_sv", 10, 267.0),
    "Sc": ("Sc_sv", 11, 223.0), "Ti": ("Ti_sv", 12, 275.0),
    "V":  ("V_sv", 13, 264.0),  "Cr": ("Cr_pv", 12, 266.0),
    "Mn": ("Mn_pv", 13, 270.0), "Fe": ("Fe", 8, 268.0),
    "Co": ("Co", 9, 268.0),    "Ni": ("Ni", 10, 270.0),
    "Cu": ("Cu", 11, 295.0),   "Zn": ("Zn", 12, 277.0),
    "Ga": ("Ga_d", 13, 283.0), "Ge": ("Ge_d", 14, 310.0),
    "As": ("As", 5, 209.0),    "Se": ("Se", 6, 212.0),
    "Br": ("Br", 7, 216.0),    "Kr": ("Kr", 8, 185.0),
    "Rb": ("Rb_sv", 9, 220.0),  "Sr": ("Sr_sv", 10, 229.0),
    "Y":  ("Y_sv", 11, 203.0),  "Zr": ("Zr_sv", 12, 230.0),
    "Nb": ("Nb_sv", 13, 293.0), "Mo": ("Mo_sv", 14, 243.0),
    "Tc": ("Tc_pv", 13, 264.0), "Ru": ("Ru_pv", 14, 320.0),
    "Rh": ("Rh_pv", 15, 247.0), "Pd": ("Pd", 10, 251.0),
    "Ag": ("Ag", 11, 250.0),   "Cd": ("Cd", 12, 274.0),
    "In": ("In_d", 13, 240.0), "Sn": ("Sn_d", 14, 241.0),
    "Sb": ("Sb", 5, 172.0),    "Te": ("Te", 6, 175.0),
    "I":  ("I", 7, 176.0),     "Xe": ("Xe", 8, 153.0),
    "Cs": ("Cs_sv", 9, 220.0),  "Ba": ("Ba_sv", 10, 187.0),
    "La": ("La", 11, 219.0),   "Ce": ("Ce", 12, 273.0),
    "Hf": ("Hf_pv", 10, 220.0), "Ta": ("Ta_pv", 11, 224.0),
    "W":  ("W_sv", 14, 317.0),  "Re": ("Re", 7, 226.0),
    "Os": ("Os", 8, 228.0),    "Ir": ("Ir", 9, 211.0),
    "Pt": ("Pt", 10, 230.0),   "Au": ("Au", 11, 230.0),
    "Hg": ("Hg", 12, 233.0),   "Tl": ("Tl_d", 13, 237.0),
    "Pb": ("Pb_d", 14, 238.0), "Bi": ("Bi_d", 15, 243.0),
}

# Safety margin applied to the largest ENMAX to get a recommended ENCUT floor.
# 1.3× is the usual rule of thumb for cell relaxations (Pulay stress).
_ENCUT_MARGIN = 1.3


@dataclass
class PotcarEntry:
    element: str
    label: str
    zval: int | None
    enmax: float | None
    known: bool


@dataclass
class PotcarResult:
    entries: list[PotcarEntry] = field(default_factory=list)
    recommended_encut: int | None = None
    functional: str = "PBE"
    spec_path: str | None = None
    potcar_path: str | None = None   # set only if a real POTCAR was assembled
    warnings: list[str] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [e.label for e in self.entries]


def _ordered_elements(structure) -> list[str]:
    """Element symbols in POSCAR/POTCAR order (matches pymatgen's site grouping)."""
    seen: list[str] = []
    for site in structure:
        sym = site.specie.symbol if hasattr(site.specie, "symbol") else str(site.specie)
        if sym not in seen:
            seen.append(sym)
    return seen


def build_potcar_spec(structure) -> PotcarResult:
    """Resolve recommended potentials for a structure (curated table, no I/O)."""
    result = PotcarResult()
    for el in _ordered_elements(structure):
        rec = _RECOMMENDED.get(el)
        if rec:
            label, zval, enmax = rec
            result.entries.append(PotcarEntry(el, label, zval, enmax, known=True))
        else:
            result.entries.append(PotcarEntry(el, el, None, None, known=False))
            result.warnings.append(
                f"No curated PBE potential for '{el}'; using bare symbol "
                f"'{el}' and unknown ENMAX — verify ENCUT manually."
            )

    known_enmax = [e.enmax for e in result.entries if e.enmax is not None]
    if known_enmax:
        result.recommended_encut = int(math.ceil(max(known_enmax) * _ENCUT_MARGIN))
    return result


def _try_real_potcar(result: PotcarResult, dest_dir: Path) -> None:
    """If a licensed PAW dir is configured, assemble a real POTCAR and read ENMAX.

    Best-effort: any failure leaves the spec-only result untouched and records a
    warning. POTCAR contents are never logged.
    """
    psp_dir = settings.pmg_vasp_psp_dir
    if not psp_dir:
        return
    try:
        os.environ.setdefault("PMG_VASP_PSP_DIR", psp_dir)
        from pymatgen.io.vasp.inputs import Potcar

        functional = settings.pmg_vasp_functional or "PBE_54"
        result.functional = functional
        potcar = Potcar(symbols=result.labels, functional=functional)
        potcar.write_file(str(dest_dir / "POTCAR"))
        result.potcar_path = str(dest_dir / "POTCAR")

        # Override curated ENMAX/ZVAL with authoritative values from the files.
        for entry, single in zip(result.entries, potcar):
            if single.enmax:
                entry.enmax = round(float(single.enmax), 1)
            if single.zval:
                entry.zval = int(single.zval)
            entry.known = True
        enmax = [e.enmax for e in result.entries if e.enmax is not None]
        if enmax:
            result.recommended_encut = int(math.ceil(max(enmax) * _ENCUT_MARGIN))
    except Exception as exc:  # noqa: BLE001 - never let POTCAR assembly break gen
        logger.warning("Real POTCAR assembly failed (%s); emitting spec only.", exc)
        result.warnings.append(f"POTCAR assembly skipped: {exc}")


def _format_spec(result: PotcarResult) -> str:
    lines = [
        "# POTCAR.spec — recommended VASP PAW potentials (Materia)",
        f"# Functional: {result.functional}",
        "# NOTE: real POTCAR files are licensed and not included. Assemble them",
        "#       from your VASP PAW library using the labels below.",
        "",
        f"{'ELEMENT':<8}{'POTENTIAL':<12}{'ZVAL':<8}{'ENMAX(eV)':<12}",
        f"{'-'*7:<8}{'-'*9:<12}{'-'*4:<8}{'-'*9:<12}",
    ]
    for e in result.entries:
        zval = str(e.zval) if e.zval is not None else "?"
        enmax = f"{e.enmax:.1f}" if e.enmax is not None else "?"
        lines.append(f"{e.element:<8}{e.label:<12}{zval:<8}{enmax:<12}")
    lines.append("")
    if result.recommended_encut:
        lines.append(f"# Recommended ENCUT floor: {result.recommended_encut} eV "
                     f"(max ENMAX × {_ENCUT_MARGIN}).")
    for w in result.warnings:
        lines.append(f"# WARNING: {w}")
    return "\n".join(lines) + "\n"


def write_potcar_spec(structure, dest_dir: Path) -> PotcarResult:
    """Write ``POTCAR.spec`` (and a real ``POTCAR`` if configured) into `dest_dir`.

    Returns the resolved `PotcarResult` (entries, recommended ENCUT, file paths,
    warnings) so the VASP service can set ENCUT and report potentials.
    """
    result = build_potcar_spec(structure)
    _try_real_potcar(result, dest_dir)

    spec_path = dest_dir / "POTCAR.spec"
    spec_path.write_text(_format_spec(result))
    result.spec_path = str(spec_path)
    return result
