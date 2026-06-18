# Step 5.5 · Step 11 — Single Docker rebuild + smoke test (+ POTCAR runtime mount)

**Status:** ✅ Done (local x86 validation)

## Goal
Bake all of Step 5.5 into the deployable images **once** (after the per-step dev-venv checks), install
the one new dependency, and smoke-test the real container — including assembling a **real POTCAR** from
a licensed PAW library mounted at runtime.

## POTCAR: runtime mount, never baked in (license-safe)
VASP PAW/POTCAR files are licensed per group and must not be redistributed, so they are **mounted at
runtime**, not copied into the image and not committed. A small code change makes the mounted library
usable regardless of its version:

- **`config.py`** — new `pmg_vasp_functional` setting (env `PMG_VASP_FUNCTIONAL`, default `PBE_54`).
- **`potcar.py`** — uses that setting instead of a hardcoded `"PBE_54"`. The host's library is the
  unversioned `POT_GGA_PAW_PBE` set, so it is selected with `PMG_VASP_FUNCTIONAL=PBE`.

When `PMG_VASP_PSP_DIR` is unset, Materia still emits the safe `POTCAR.spec` (labels + ENCUT only).

### Deploy mount (api **and** worker)
```bash
-v /home/roy/POTCAR/vasp_POTCAR:/opt/vasp_psp:ro \
-e PMG_VASP_PSP_DIR=/opt/vasp_psp \
-e PMG_VASP_FUNCTIONAL=PBE
```
`/home/roy/POTCAR/vasp_POTCAR` is the pymatgen-ready root (it contains `POT_GGA_PAW_PBE/<El>/POTCAR`).
On Oracle, mount the equivalent host path there. Never `git add` the PAW folder.

## The rebuild
```bash
docker build -t materia-backend:dev backend/     # installs pymatgen-analysis-defects + new code
docker build -t materia-frontend:dev frontend/   # vite build incl. refreshed ToolStatus labels
```
> Note: this dev PC is **x86**; the Oracle production image is **ARM**. The local build validates "the
> code + new dep install and run" and the POTCAR mount; the authoritative ARM image is built at the
> Oracle deploy (or via `docker buildx --platform linux/arm64`).

## Smoke test (inside the freshly built backend image, with the PAW mount)
- `pymatgen-analysis-defects 2026.3.20` is installed in the image and imports. ✅
- `generate_vasp_inputs` static + `functional=hse06` → `LHFCALC` present in INCAR. ✅
- A **real POTCAR (196 KB)** was assembled from the mounted PAW library (header `PAW_PBE Si …`). ✅
- Frontend image builds (vite compiles the updated `ToolStatus.jsx`). ✅

## Not exercised here (needs a BYOK key)
The full chat → agent → tool path needs a user LLM key (Groq/Gemini). Tool *logic* was verified
directly (dev venv per step + in-image smoke test); the LLM-driven path is a runtime concern, not a
code change in this round.
