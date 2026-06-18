"""VASP input-set generation (redesign §9).

Single entry point that produces a complete (POSCAR + INCAR + KPOINTS +
POTCAR.spec) input package for a task and returns a `VaspInputSet` summary.
ENCUT is derived from the recommended potentials; a real POTCAR is emitted only
when a licensed PAW library is configured (see `potcar.py`).
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.domain.vasp import CellRelax, VaspInputSet, VaspTask
from app.services.vasp.incar import generate_incar
from app.services.vasp.kpoints import generate_kpoints, generate_line_kpoints
from app.services.vasp.poscar import write_poscar
from app.services.vasp.potcar import write_potcar_spec

logger = get_logger(__name__)

# User-facing VaspTask → internal INCAR template key.
_TASK_TO_TEMPLATE = {
    VaspTask.RELAXATION:   "optimization",
    VaspTask.STATIC:       "static",
    VaspTask.BAND:         "band",
    VaspTask.DOS:          "dos",
    VaspTask.AIMD:         "md_nvt",
    VaspTask.ELASTIC:      "elastic",
    VaspTask.PHONON_DFPT:  "phonon_dfpt",
    VaspTask.DIELECTRIC:   "dielectric",
    VaspTask.BADER:        "bader",
    VaspTask.ELF:          "elf",
    VaspTask.WORKFUNCTION: "workfunction",
}

# KPOINTS density (k-points per Å^-1) per task. DOS / dielectric / phonon want a
# denser mesh; AIMD uses a single Γ-point.
_DEFAULT_DENSITY = 40
_DOS_DENSITY = 60
_DENSE_DENSITY = 60

_DEFAULT_ENCUT = 520


class VaspService:
    def build_input_set(
        self,
        structure,
        task: VaspTask = VaspTask.RELAXATION,
        cell_relax: CellRelax = CellRelax.NONE,
        output_dir: Path | None = None,
        overrides: dict | None = None,
        modifiers: dict | None = None,
    ) -> VaspInputSet:
        """Write POSCAR + INCAR + KPOINTS + POTCAR.spec into `output_dir`.

        `modifiers` are the orthogonal knobs (functional/vdw/soc/hubbard_u/dipole/
        solvent/charge) layered on top of the task; ``charge`` is resolved here into
        a concrete ``NELECT`` from the POTCAR valence counts.
        """
        template = _TASK_TO_TEMPLATE.get(task)
        if template is None:
            raise ValueError(
                f"VASP task '{task.value}' is not available "
                f"(supported: {[t.value for t in _TASK_TO_TEMPLATE]})."
            )

        out_dir = Path(output_dir) if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        overrides = dict(overrides or {})
        modifiers = dict(modifiers or {})

        # POSCAR
        formula = structure.composition.reduced_formula
        write_poscar(structure, out_dir, name=formula)

        # POTCAR.spec (+ real POTCAR if a licensed PAW dir is configured) → ENCUT
        potcar = write_potcar_spec(structure, out_dir)
        encut = int(overrides.get("ENCUT")
                    or max(_DEFAULT_ENCUT, potcar.recommended_encut or 0))
        overrides["ENCUT"] = encut

        # charge → NELECT (needs the POTCAR valence counts), plus modifier warnings.
        charge = float(modifiers.pop("charge", 0.0) or 0.0)
        warnings = list(potcar.warnings)
        nelect = None
        if charge:
            nelect, neutral = _compute_nelect(structure, potcar, charge)
            if nelect is not None:
                overrides.setdefault("NELECT", f"{nelect:g}")
                warnings.append(
                    f"Charged cell: NELECT={nelect:g} (neutral={neutral:g}, "
                    f"charge={charge:+g} e). VASP adds a compensating uniform background.")
            else:
                warnings.append(
                    "charge was requested but NELECT could not be computed (unknown "
                    "ZVAL for some element); set NELECT manually.")
        warnings.extend(_modifier_warnings(modifiers))

        # INCAR — modifiers (functional/vdw/soc/hubbard_u/dipole/solvent) + overrides.
        incar_txt = generate_incar(
            structure, task=template, cell_relax=cell_relax.value,
            **modifiers, **overrides,
        )
        (out_dir / "INCAR").write_text(incar_txt)

        # KPOINTS — line-mode path for bands, Γ-only for AIMD, dense mesh for
        # DOS/dielectric/phonon, regular mesh otherwise.
        if task is VaspTask.BAND:
            kpoints_txt = generate_line_kpoints(structure)
            kmesh = None
        elif task is VaspTask.AIMD:
            kpoints_txt = generate_kpoints(structure, is_md=True)
            kmesh = [1, 1, 1]
        else:
            if task is VaspTask.DOS:
                density = _DOS_DENSITY
            elif task in (VaspTask.DIELECTRIC, VaspTask.PHONON_DFPT):
                density = _DENSE_DENSITY
            else:
                density = _DEFAULT_DENSITY
            kpoints_txt = generate_kpoints(structure, density=density)
            kmesh = self._kmesh(structure, density)
        (out_dir / "KPOINTS").write_text(kpoints_txt)

        files: dict[str, str] = {
            "poscar":  str(out_dir / "POSCAR"),
            "incar":   str(out_dir / "INCAR"),
            "kpoints": str(out_dir / "KPOINTS"),
        }
        if potcar.spec_path:
            files["potcar_spec"] = potcar.spec_path
        if potcar.potcar_path:
            files["potcar"] = potcar.potcar_path

        # Non-default modifiers actually applied (for the tool's response summary).
        applied = {k: str(v) for k, v in modifiers.items()
                   if v not in (None, False, "", "pbe", "none")}
        if charge:
            applied["charge"] = f"{charge:+g}"

        return VaspInputSet(
            task=task,
            cell_relax=cell_relax,
            encut=encut,
            kmesh=kmesh,
            elements=[str(e) for e in structure.composition.elements],
            files=files,
            formula=formula,
            n_sites=len(structure),
            potentials={e.element: e.label for e in potcar.entries},
            warnings=warnings,
            modifiers=applied,
            nelect=nelect,
        )

    @staticmethod
    def _kmesh(structure, density: int = _DEFAULT_DENSITY) -> list[int] | None:
        try:
            from pymatgen.io.vasp.inputs import Kpoints
            kpts = Kpoints.automatic_density(structure, kppa=density * 50)
            return [int(x) for x in kpts.kpts[0]]
        except Exception:
            return None


def _compute_nelect(structure, potcar, charge: float):
    """Return (nelect, neutral_electrons) for a charged cell, or (None, None).

    NELECT = Σ ZVAL over all atoms − charge (charge>0 ⇒ electrons removed).
    Returns (None, None) when any element's ZVAL is unknown.
    """
    zval = {e.element: e.zval for e in potcar.entries}
    total = 0.0
    for site in structure:
        sym = site.specie.symbol if hasattr(site.specie, "symbol") else str(site.specie)
        z = zval.get(sym)
        if z is None:
            return None, None
        total += z
    return total - charge, total


def _modifier_warnings(modifiers: dict) -> list[str]:
    """Human-facing cautions for the requested modifiers."""
    warns: list[str] = []
    if (modifiers.get("functional") or "").lower() == "hse06":
        warns.append("HSE06 is far costlier than PBE (hybrid exact exchange) — "
                     "expect long runtimes; consider a denser-but-small cell.")
    if (modifiers.get("functional") or "").lower() == "scan":
        warns.append("SCAN meta-GGA can be hard to converge; ALGO=All is set.")
    if modifiers.get("soc"):
        warns.append("Spin-orbit (noncollinear): MAGMOM must have 3 components per "
                     "atom — verify the magnetic configuration before running.")
    if modifiers.get("hubbard_u"):
        warns.append("DFT+U uses curated default U values for transition metals — "
                     "verify them against the literature for your system.")
    solvent = (modifiers.get("solvent") or "none").lower()
    if solvent != "none":
        warns.append(f"{solvent} implicit solvation requires the VASPsol-patched VASP "
                     "binary; the LSOL tags are ignored by a stock VASP build. For a "
                     "charged interface, combine with `charge` (sets NELECT).")
    return warns


# Module-level singleton.
vasp_service = VaspService()
