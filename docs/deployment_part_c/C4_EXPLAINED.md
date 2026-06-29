# Part C / C4 — GPU / CUDA pack

**Status:** 🛠️ WIRED (Linux, local) — not yet release‑tested on a tag. Adds an
**optional, faster GPU edition** of the desktop app alongside the CPU edition that
C1–C3 shipped. Parent plan: `PART_C_DESKTOP_PLAN.md` §5.

---

## 🪜 Big picture (read this first if you're new)

Back to the **microwave** one more time.

- **C1** proved the microwave turns on and can cook a meal on our bench.
- **C2** made it usable by a stranger (downloads its own recipe books, runs on your power).
- **C3** built the **factory line** that boxes a shippable unit for every kind of kitchen
  and lets it update its own firmware.
- **C4** adds a **second model on the same line: a "Pro" microwave with a turbo burner**.
  Same microwave, same recipes — but if your kitchen has the special high‑power outlet
  (an **NVIDIA GPU**), the Pro model cooks *much* faster. If you plug the Pro model into a
  normal outlet, it still works — it just cooks at normal speed instead of crashing.

In software terms: the heavy simulations (MACE / MatterSim molecular dynamics, relaxations,
NEB…) are big number‑crunching jobs. On a **CPU** they're correct but slow. On a **GPU**
(a graphics card built for exactly this kind of math) they can be **5–20× faster**. C4 lets
users who own an NVIDIA GPU get that speed‑up, without forcing the much larger GPU download
onto everyone else.

---

## 📚 Core concepts (the new ideas, in plain words)

**What is a GPU, and why does it matter here?**
A CPU has a handful of very smart cores; a GPU has *thousands* of simpler cores. The math
inside an ML‑potential (multiplying big grids of numbers) is the kind of work you can split
across thousands of cores at once — so a GPU eats it for breakfast. That's the whole reason
"do the simulation locally" is attractive: your own gaming/workstation GPU can rival a small
server.

**What is CUDA?**
CUDA is NVIDIA's toolkit that lets programs (here, PyTorch) actually *use* an NVIDIA GPU.
"CUDA torch" = a build of PyTorch that includes the GPU machinery. It's bigger (extra GPU
libraries) and only useful on NVIDIA cards. "CPU torch" is the smaller build that runs
anywhere but only on the CPU. **A single download can't be both** — you pick one when you
build. That single fact is the reason C4 exists as a *separate installer*.

**Why two installers instead of one clever app?**
Three honest options were on the table:
1. **One app that auto‑detects** → would force the big CUDA download (~2× size) on *everyone*,
   including the majority who have no NVIDIA GPU.
2. **Download the GPU pack after install** → nicest in theory, but means swapping PyTorch
   inside a frozen app at runtime: fiddly and fragile.
3. **Two installers** (what we did) → the user picks "CPU" or "GPU" on the download page.
   Slightly more to publish; by far the most robust. The GPU build *still* falls back to CPU
   if there's no GPU, so a wrong choice is slow, never broken.

**Auto‑update channels.**
electron‑updater decides "is there a newer version?" by reading a small `*.yml` file on the
GitHub Release. If both editions wrote the *same* file they'd fight, and a GPU user might be
"updated" to a CPU build. So the GPU edition publishes on its own **channel** (`gpu-*.yml`)
and the CPU edition on the default channel (`latest-*.yml`). Each edition only ever sees its
own kind of update.

---

## 🔧 What actually changed (the diff, explained)

### 1. Backend — one switch, one window

**`app/services/simulation/calculator_factory.py`**
- `_auto_device()` already picked `cuda > mps > cpu`, and (from C3) honours a `MATERIA_DEVICE`
  override. C4 adds **`device_info()`**: a small function that reports the *resolved* device
  plus what torch can actually see (`cuda_available`, `gpu_name`, `torch_version`). It's the
  single source of truth for "GPU or CPU?", so the API and the UI never disagree.

**`app/api/system.py`** (new) — `GET /api/system`
- Returns `{ variant, device, cuda_available, gpu_name, torch_version }`.
- **Gated on `enable_heavy_tools`** exactly like `/api/models`: only the desktop edition runs
  sims locally, so on the lite web edition this **404s** and the UI badge hides itself.
- `variant` (cpu|gpu) comes from an env var the Electron shell stamps in, so the UI can tell
  *why* a build is on CPU: "this is the CPU build" vs "GPU build, but no GPU found".

### 2. Electron shell — pick the device per build

**`desktop/electron/backend.js`**
- New `buildVariant()` reads `materiaVariant` from `package.json` (CI stamps `gpu`; default `cpu`).
- The backend env is now conditional:
  - **CPU build** → `MATERIA_DEVICE=cpu` + `CUDA_VISIBLE_DEVICES=''` (pin CPU, hide any GPU so a
    stray CUDA torch can't nvrtc‑JIT‑crash — the bug we fixed in C3).
  - **GPU build** → leaves `MATERIA_DEVICE` *unset* so the backend auto‑detects `cuda > mps > cpu`.
    **This is the graceful fallback**: GPU build on a GPU‑less machine simply lands on CPU.
- Also passes `MATERIA_VARIANT` through so `/api/system` can report it.

**`desktop/package.json`** — adds `"materiaVariant": "cpu"` (the default any local/dev build uses).

### 3. The build line — two flavours per release

**`.github/workflows/desktop-release.yml`**
- The matrix gains a `variant: [cpu, gpu]` dimension, with **macOS excluded from `gpu`** (no CUDA
  on Macs). That's **5 jobs** per release: CPU on Win/mac/Linux + GPU on Win/Linux.
- The *only* build difference is the torch wheel index:
  `…/whl/cpu` for CPU, `…/whl/cu124` (CUDA 12.4) for GPU. Everything downstream (freeze, SPA,
  package) is identical.
- The GPU job overrides three electron‑builder settings so the two editions coexist on one
  Release and update independently:
  - `productName=Materia-GPU` → distinct app name + filenames (`Materia-GPU-<ver>-<arch>.*`),
  - `appId=ai.materia.desktop.gpu` → installs side‑by‑side with the CPU app,
  - `publish.channel=gpu` → its own `gpu-*.yml` update feed.

### 4. The UI — show the user what they got

**`frontend/src/api/system.js`** (new) — thin client for `/api/system`.

**`frontend/src/features/models/ModelSetup.jsx`** — a **device badge** at the top of the
Simulation Models screen, in three states:
- ⚡ **Running on GPU** — `NVIDIA GeForce …` (cuda) or Apple GPU (mps).
- ◧ **Running on CPU** — *GPU build, but no compatible GPU detected* (check NVIDIA drivers).
- ▣ **Running on CPU** — *for NVIDIA acceleration, install the GPU build.*

So a user can **confirm at a glance** that the GPU edition is really using the GPU — and isn't
silently crawling on CPU.

---

## ✅ How it was verified (local, Linux, RTX A4000)

- `device_info()` → `{device: cuda, cuda_available: true, gpu_name: "NVIDIA RTX A4000", …}`.
- `GET /api/system` with `ENABLE_HEAVY_TOOLS=true` → **200** with the full device payload;
  with `ENABLE_HEAVY_TOOLS=false` → **404** (web edition stays clean).
- `app.main` imports with the new router; `ruff --select F,E9` clean; `npm run build` OK.

## ⏳ Remaining go/no‑go (needs a real runner — can't be done on this box)
- Push a `v*` tag (or run the dispatch dry‑run) and confirm **5 green jobs** and **5 artifacts**,
  with **no filename collision** between `Materia-*` and `Materia-GPU-*` on the Release.
- On a real NVIDIA Windows/Linux box: install **Materia-GPU**, run a MACE job, confirm the badge
  says **Running on GPU** and the job is faster than the CPU build.
- Confirm a `gpu-linux.yml` / `gpu.yml` (and Windows equivalents) appear next to `latest-*.yml`.

## 🧭 Trade‑offs we accepted
- **Bigger GPU artifact** (~2× the CPU one — CUDA libraries) and **one extra build per OS**.
- **Two downloads on the Release page** instead of one (README explains which to pick).
- Still **unsigned** (signing is C5); GPU build inherits the same one‑time OS warning.
