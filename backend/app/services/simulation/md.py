"""
backend/app/services/md_service.py
====================================
ASE-based Molecular Dynamics service (NVT and NPT).

Ensembles
---------
  NVT — constant Number, Volume, Temperature
        Thermostat: Langevin (default) or NoséHoover (Andersen)
  NPT — constant Number, Pressure, Temperature
        Thermostat: NPTBerendsen or Bussi

Outputs per run
---------------
  trajectory.traj  — full ASE binary trajectory
  trajectory.xyz   — multi-frame extXYZ for 3Dmol.js viewer
  md.log           — step, time_fs, energy_eV, temperature_K, [pressure_GPa]
  md_energy.csv    — step, time_fs, energy_eV
  md_temp.csv      — step, time_fs, temperature_K
  CONTCAR          — final structure in VASP POSCAR format
  INCAR            — VASP INCAR for equivalent VASP-MD run
  KPOINTS          — VASP KPOINTS

Usage
-----
    from app.services.md_service import run_md

    result = run_md(
        poscar_path = "/path/to/POSCAR",
        output_dir  = "/path/to/session_dir",
        ensemble    = "nvt",
        temperature = 300,
        nsw         = 10000,
        timestep    = 1.0,
        thermostat  = "langevin",
        calculator  = {"type": "mace"},
    )
"""

import csv
import time
from pathlib import Path
from typing import Optional

from app.services.simulation.calculator_factory import get_calculator
from app.services.vasp.incar import generate_incar
from app.services.vasp.kpoints import generate_kpoints


# ── Public API ────────────────────────────────────────────────────────────────

def run_md(
    poscar_path:          str,
    output_dir:           str,
    ensemble:             str           = "nvt",
    temperature:          float         = 300.0,
    nsw:                  int           = 10000,
    timestep:             float         = 1.0,
    thermostat:           str           = "langevin",
    pressure:             float         = 0.0,        # GPa, NPT only
    friction:             float         = 0.01,       # ps^-1, Langevin
    log_interval:         int           = 10,
    calculator:           Optional[dict] = None,
    generate_vasp_inputs: bool          = True,
) -> dict:
    """
    Run ASE Molecular Dynamics.

    Parameters
    ----------
    poscar_path          : Path to input POSCAR / CONTCAR.
    output_dir           : Output directory.
    ensemble             : "nvt" | "npt"
    temperature          : Target temperature [K]. Default 300.
    nsw                  : Total MD steps. Default 10000.
    timestep             : Timestep [fs]. Default 1.0.
    thermostat           : NVT: "langevin" | "nose-hoover"
                           NPT: "berendsen" | "bussi"
    pressure             : Target pressure [GPa], NPT only. Default 0 (1 atm).
    friction             : Langevin friction coefficient [ps^-1]. Default 0.01.
    log_interval         : Log every N steps. Default 10.
    calculator           : dict for get_calculator(). Default MACE.
    generate_vasp_inputs : Also write INCAR + KPOINTS.

    Returns
    -------
    {
      "status":          "success" | "error",
      "message":         str,
      "steps_completed": int,
      "total_time_fs":   float,
      "formula":         str,
      "n_sites":         int,
      "final_energy":    float,
      "mean_temperature": float,
      "files": {
          "trajectory_traj": str,
          "trajectory_xyz":  str,
          "log":             str,
          "energy_csv":      str,
          "temp_csv":        str,
          "contcar":         str,
          "incar":           str | None,
          "kpoints":         str | None,
      }
    }
    """
    try:
        from ase.io import read, write
    except ImportError as e:
        return {"status": "error", "message": f"ASE not installed: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Read input structure ───────────────────────────────────────────────
    try:
        atoms = read(str(poscar_path), format="vasp")
    except Exception as e:
        return {"status": "error", "message": f"Failed to read POSCAR: {e}"}

    formula = atoms.get_chemical_formula(mode="hill")

    # ── 2. Attach calculator ──────────────────────────────────────────────────
    try:
        calc_cfg   = calculator or {"type": "mace"}
        atoms.calc = get_calculator(calc_cfg)
    except Exception as e:
        return {"status": "error", "message": f"Calculator error: {e}"}

    # ── 3. Convert units ──────────────────────────────────────────────────────
    from ase import units
    timestep_ase = timestep * units.fs          # fs → ASE time units
    temperature_K = float(temperature)
    friction_ase  = friction / units.fs         # ps^-1 → ASE units

    # ── 4. Build thermostat/dynamics object ───────────────────────────────────
    traj_path = out_dir / "trajectory.traj"
    log_path  = out_dir / "md.log"

    try:
        dyn = _make_dynamics(
            ensemble    = ensemble.lower(),
            thermostat  = thermostat.lower(),
            atoms       = atoms,
            temperature = temperature_K,
            timestep    = timestep_ase,
            pressure    = pressure,
            friction    = friction_ase,
            traj_path   = str(traj_path),
            log_path    = str(log_path),
        )
    except Exception as e:
        return {"status": "error", "message": f"Dynamics setup error: {e}"}

    # ── 5. Logging callbacks ──────────────────────────────────────────────────
    energy_log: list[dict] = []
    temp_log:   list[dict] = []

    def _log_step():
        step    = len(energy_log) * log_interval
        time_fs = step * timestep
        try:
            e   = atoms.get_potential_energy()
            T   = atoms.get_temperature()
        except Exception:
            e, T = float("nan"), float("nan")

        energy_log.append({"step": step, "time_fs": round(time_fs, 3), "energy_eV": round(e, 6)})
        temp_log.append(  {"step": step, "time_fs": round(time_fs, 3), "temperature_K": round(T, 3)})

    dyn.attach(_log_step, interval=log_interval)

    # ── 6. Run ────────────────────────────────────────────────────────────────
    t0 = time.time()
    steps_done = 0
    try:
        dyn.run(nsw)
        steps_done = nsw
    except Exception as e:
        # Partial run — save what we have
        steps_done = len(energy_log) * log_interval
        print(f"[MD] Run interrupted at step {steps_done}: {e}")

    elapsed = round(time.time() - t0, 1)

    # ── 7. Write CONTCAR ──────────────────────────────────────────────────────
    contcar_path = out_dir / "CONTCAR"
    try:
        write(str(contcar_path), atoms, format="vasp", direct=True)
    except Exception as e:
        print(f"[MD] CONTCAR write error: {e}")

    # ── 8. Write XYZ trajectory for 3Dmol.js ─────────────────────────────────
    xyz_path = out_dir / "trajectory.xyz"
    try:
        from ase.io import Trajectory as TrajReader
        frames = list(TrajReader(str(traj_path)))
        write(str(xyz_path), frames, format="extxyz")
    except Exception:
        xyz_path = None

    # ── 9. Write CSV files ────────────────────────────────────────────────────
    energy_csv_path = out_dir / "md_energy.csv"
    temp_csv_path   = out_dir / "md_temp.csv"

    try:
        with open(energy_csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["step", "time_fs", "energy_eV"])
            w.writeheader(); w.writerows(energy_log)
    except Exception:
        energy_csv_path = None

    try:
        with open(temp_csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["step", "time_fs", "temperature_K"])
            w.writeheader(); w.writerows(temp_log)
    except Exception:
        temp_csv_path = None

    # ── 10. VASP input files ──────────────────────────────────────────────────
    incar_path   = None
    kpoints_path = None
    if generate_vasp_inputs:
        try:
            from pymatgen.io.ase import AseAtomsAdaptor
            structure    = AseAtomsAdaptor.get_structure(atoms)
            task_key     = "md_nvt" if ensemble.lower() == "nvt" else "md_npt"
            incar_str    = generate_incar(
                structure, task=task_key,
                temperature=int(temperature), nsw=nsw, timestep=timestep
            )
            kpoints_str  = generate_kpoints(structure, is_md=True)
            incar_path   = out_dir / "INCAR"
            kpoints_path = out_dir / "KPOINTS"
            incar_path.write_text(incar_str)
            kpoints_path.write_text(kpoints_str)
        except Exception as e:
            print(f"[MD] VASP input warning: {e}")

    # ── 11. Summary stats ─────────────────────────────────────────────────────
    import statistics
    mean_T    = statistics.mean(r["temperature_K"] for r in temp_log) if temp_log else None
    final_E   = energy_log[-1]["energy_eV"] if energy_log else None
    total_fs  = steps_done * timestep

    message = (
        f"MD ({ensemble.upper()}) completed {steps_done} steps "
        f"({total_fs:.1f} fs) at {temperature_K} K. "
        f"Mean T = {mean_T:.1f} K, Final E = {final_E} eV. "
        f"Wall time: {elapsed}s."
    )
    print(f"[MD] {message}")

    return {
        "status":            "success",
        "message":           message,
        "steps_completed":   steps_done,
        "total_time_fs":     total_fs,
        "formula":           formula,
        "n_sites":           len(atoms),
        "final_energy":      final_E,
        "mean_temperature":  round(mean_T, 2) if mean_T else None,
        "ensemble":          ensemble,
        "thermostat":        thermostat,
        "calculator":        calc_cfg,
        "elapsed_s":         elapsed,
        "files": {
            "trajectory_traj": str(traj_path),
            "trajectory_xyz":  str(xyz_path)         if xyz_path         else None,
            "log":             str(log_path),
            "energy_csv":      str(energy_csv_path)  if energy_csv_path  else None,
            "temp_csv":        str(temp_csv_path)    if temp_csv_path    else None,
            "contcar":         str(contcar_path),
            "incar":           str(incar_path)        if incar_path        else None,
            "kpoints":         str(kpoints_path)      if kpoints_path      else None,
        },
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _make_dynamics(
    ensemble:    str,
    thermostat:  str,
    atoms,
    temperature: float,
    timestep:    float,
    pressure:    float,
    friction:    float,
    traj_path:   str,
    log_path:    str,
):
    """Build the ASE dynamics object for the requested ensemble/thermostat."""
    from ase import units

    traj_kwargs = {"trajectory": traj_path, "logfile": log_path}

    if ensemble == "nvt":
        if thermostat in ("langevin", ""):
            from ase.md.langevin import Langevin
            return Langevin(
                atoms,
                timestep   = timestep,
                temperature_K = temperature,
                friction   = friction,
                **traj_kwargs,
            )
        elif thermostat in ("nose-hoover", "nosehoover", "andersen"):
            from ase.md.andersen import Andersen
            return Andersen(
                atoms,
                timestep          = timestep,
                temperature_K     = temperature,
                andersen_prob     = 0.01,
                **traj_kwargs,
            )
        else:
            raise ValueError(
                f"Unknown NVT thermostat '{thermostat}'. Use: langevin | nose-hoover"
            )

    elif ensemble == "npt":
        if thermostat in ("berendsen", ""):
            from ase.md.nptberendsen import NPTBerendsen
            # Convert GPa → bar (1 GPa = 10000 bar)
            pressure_bar = pressure * 10000 if pressure != 0 else 1.01325  # 1 atm
            return NPTBerendsen(
                atoms,
                timestep       = timestep,
                temperature_K  = temperature,
                pressure_au    = pressure_bar * units.bar,
                taut           = 100 * timestep,
                taup           = 1000 * timestep,
                compressibility_au = 4.57e-5 / units.bar,
                **traj_kwargs,
            )
        elif thermostat in ("bussi", "csvr"):
            # Canonical Sampling through Velocity Rescaling
            # Falls back to Berendsen if not available
            try:
                from ase.md.bussi import Bussi
                return Bussi(
                    atoms,
                    timestep      = timestep,
                    temperature_K = temperature,
                    taut          = 100 * timestep,
                    **traj_kwargs,
                )
            except ImportError:
                print("[MD] Bussi not available in this ASE version; using NPTBerendsen.")
                from ase.md.nptberendsen import NPTBerendsen
                return NPTBerendsen(
                    atoms,
                    timestep       = timestep,
                    temperature_K  = temperature,
                    pressure_au    = 1.01325 * units.bar,
                    taut           = 100 * timestep,
                    taup           = 1000 * timestep,
                    compressibility_au = 4.57e-5 / units.bar,
                    **traj_kwargs,
                )
        else:
            raise ValueError(
                f"Unknown NPT thermostat '{thermostat}'. Use: berendsen | bussi"
            )
    else:
        raise ValueError(f"Unknown ensemble '{ensemble}'. Use: nvt | npt")