# Part C / C3 — Cross‑OS installers + auto‑update

**Status:** 🛠️ WIRED (Linux, local) — not yet release‑tested on a tag. Turns the
working local app (C1 + C2) into **clickable installers for Windows, macOS, and
Linux** that update themselves. Parent plan: `PART_C_DESKTOP_PLAN.md` §4.

---

## 🪜 Big picture (read this first if you're new)

Back to the **microwave** from C2.

- **C1** proved the microwave turns on and can cook one meal on our bench.
- **C2** made it usable by a stranger: it downloads its own recipe books and runs on
  your electricity (your AI key).
- **C3** is the **factory + delivery line**: we take that one hand‑built microwave and
  set up a process that **stamps out a boxed, shippable unit for every kind of kitchen**
  — a US‑plug model, a EU‑plug model, a UK‑plug model — and adds a little feature so the
  microwave can **update its own firmware** when we publish a new version.

In software terms, C3 turns "it runs when I launch it from my code folder" into
"anyone can download one file, double‑click it, and it installs — on their OS — and
quietly keeps itself up to date." Three concrete jobs:

1. **Package** the app into a real installer per operating system.
2. **Automate** building all three on a robot (GitHub Actions) when we tag a release.
3. **Auto‑update** installed copies from the published releases.

Plus one correctness fix that surfaced during testing: **make the simulations run on
the CPU**, so the app works on machines without a perfectly‑matched GPU stack.

---

## 📚 Core concepts (the new ideas, in plain words)

**What is an "installer"?**
The app is really a folder of many files (the Electron shell, the built web page, and
the frozen Python engine). An **installer** wraps all of that into one downloadable
file that, when opened, copies everything to the right place and makes a launch icon.
Each OS wants its own kind:
- **Linux → `.AppImage`** (a single self‑contained file you make executable and run),
- **macOS → `.dmg`** (the familiar "drag the app to Applications" disk image),
- **Windows → `.exe` / NSIS** (the classic Setup wizard).

**What is electron‑builder?**
The tool that produces those three installers from our app. We tell it (in
`electron-builder.yml`) the app's name, icon, which files go inside, and where to
publish. One config, three installers.

**`asar` vs `extraResources` (why the engine ships "outside" the app).**
Electron normally packs your app into a single compressed archive called **asar** —
neat for small text files (our JS + the web page). But the frozen Python backend is a
**multi‑GB folder of real executables and shared libraries**; those must stay as real
files on disk to be run and loaded. So we put the backend in **`extraResources`**,
which copies it *unpacked* next to the app, and our `backend.js` already knows to look
for it there (`process.resourcesPath/backend`). (Analogy: the recipe cards go in the
glovebox (asar); the spare engine block rides in the trunk, unwrapped, because you
can't run it while it's shrink‑wrapped.)

**Why a build "matrix" — and why no cross‑compiling.**
You **cannot** reliably build a Mac program on a Linux machine, especially one
containing PyTorch (it has compiled, OS‑specific machine code). So instead of one
build, GitHub Actions runs the same recipe on **three real machines at once** — an
Ubuntu runner, a macOS runner, and a Windows runner. Each freezes the backend *on its
own OS* and packages *its own* installer. That fan‑out is the **matrix**. (Analogy: to
sell US/EU/UK microwaves you build each on a line wired for that country's mains — you
don't try to fake a UK plug on the US line.)

**What is auto‑update (electron‑updater)?**
When we publish a new version, electron‑builder also uploads a tiny text file
(`latest.yml` / `latest-mac.yml` / `latest-linux.yml`) that says "newest version =
X, here's the file + checksum." The installed app reads that on launch, and if it's
behind, downloads the new version in the background and installs it next restart.
(Analogy: your phone app updating itself overnight — you just see the new version next
morning.)

**What is "tagging a release"?**
A **git tag** is a named bookmark on a commit, e.g. `v0.1.0`. Pushing a tag that
starts with `v` is the trigger: the robot wakes up, builds all three installers, and
attaches them to a **GitHub Release** page named for that tag. The app's version (in
`package.json`) should match the tag.

**Why "unsigned", and what that means for users.**
**Code signing** is a paid certificate that tells the OS "this app is from a known
publisher." We ship **unsigned for v1**, so on first launch the OS shows one scary‑
looking warning the user clicks through (macOS: right‑click → Open; Windows
SmartScreen: More info → Run anyway). It's safe — just unverified. One consequence:
**macOS auto‑update needs a signed app**, so Mac users update by re‑downloading the
`.dmg` for now; Windows and Linux auto‑update normally. Signing is deferred (C5).

**CPU vs GPU, and the "nvrtc" crash.**
The ML simulations use PyTorch, which can run on a **GPU** (fast, NVIDIA‑only) or the
**CPU** (works everywhere, slower). Our dev machine's bundled torch was the GPU
("CUDA") build, so on launch it tried to use the GPU and asked NVIDIA's runtime
compiler (**nvrtc**) to build a kernel on the fly — but the matching helper library
(`libnvrtc-builtins.so.13.0`) wasn't present in the bundle, so the job crashed. Since
desktop v1 promises "runs on any machine," we **pin the simulations to the CPU**. GPU
acceleration is the optional, later **C4** pack.

---

## What C3 had to add (and why)

C2 left two things for C3 (and testing surfaced a third):

1. **No installers yet** — you still had to run it from the source tree.
2. **No release automation / auto‑update.**
3. **(found in testing)** the app grabbed the GPU and crashed on `nvrtc`; v1 must run
   on CPU.

---

## 1. Packaging — electron‑builder

- **`desktop/electron-builder.yml`** (new): appId `ai.materia.desktop`, productName
  *Materia*; three targets — **AppImage / dmg / nsis**. The SPA + Electron shell go in
  the **asar** (`files`); the frozen backend ships **unpacked** via **`extraResources`**
  (`resources/backend → backend`), exactly where `backend.js` looks for it. `publish`
  points at the GitHub repo so releases + the update feed land there.
- **`desktop/package.json`** (edit): added `electron-builder` (dev) and
  `electron-updater` (runtime), plus scripts `pack` (local unpacked build, no publish)
  and `dist` (full installer). Lockfile regenerated.
- **`desktop/build-assets/icon.png`** (new): a 1024² placeholder icon; electron‑builder
  auto‑derives the platform `.icns`/`.ico` from it. Lives in `build-assets/` so it's
  committed (the `build/` dir is the git‑ignored PyInstaller scratch).

## 2. Automation — GitHub Actions matrix

- **`.github/workflows/desktop-release.yml`** (new). Trigger: push a **`v*`** tag (or
  run it manually via `workflow_dispatch` for a no‑publish **dry run** that uploads the
  installers as build artifacts). For each of **ubuntu / macos / windows**:
  1. install **CPU‑only torch** from the PyTorch CPU wheel index, then the rest with
     the legacy resolver — this mirrors `backend/Dockerfile` so the proven dependency
     combo holds and the bundle stays small (no 2.5 GB of unused CUDA libs);
  2. **freeze the backend** natively (`python scripts/build_backend.py`);
  3. **build the SPA** with a `file://`‑safe relative base;
  4. **`electron-builder --publish always`** packages + uploads the OS's installer to
     the GitHub Release.
- All steps use `shell: bash` so one script works on all three runners; `GH_TOKEN`
  comes from the built‑in `secrets.GITHUB_TOKEN`.

## 3. Auto‑update — electron‑updater

- **`desktop/electron/main.js`** (edit): a small `initAutoUpdate()` calls
  `autoUpdater.checkForUpdatesAndNotify()` **only when `app.isPackaged`** (a no‑op in
  dev, where there's no signed feed). It reads the `latest*.yml` published in step 2,
  downloads a newer version in the background, and installs on next launch
  (Windows/Linux; macOS needs signing first).

## 4. CPU pinning — the nvrtc fix

- **`backend/app/services/simulation/calculator_factory.py`** (edit): `_auto_device()`
  now honors a **`MATERIA_DEVICE`** env var (`cpu|cuda|mps`) before auto‑detecting, so
  the device is an explicit knob rather than "always grab CUDA if present."
- **`desktop/electron/backend.js`** (edit): the backend is spawned with
  **`MATERIA_DEVICE='cpu'`** *and* **`CUDA_VISIBLE_DEVICES=''`**. The empty
  `CUDA_VISIBLE_DEVICES` hides any GPU from the **already‑frozen** binary at launch (so
  the fix works without re‑freezing); `MATERIA_DEVICE='cpu'` is the explicit signal the
  re‑frozen backend reads. Together they make the heavy sims run on CPU and avoid the
  `libnvrtc-builtins` crash. (Re‑enabling the GPU is the deferred C4 pack.)

---

## Files touched (quick map)

| File | New? | What it does |
|------|------|--------------|
| `desktop/electron-builder.yml` | new | packaging: 3 targets, backend in extraResources, GitHub publish |
| `desktop/package.json` | edit | + electron‑builder / electron‑updater, `pack`/`dist` scripts |
| `desktop/package-lock.json` | edit | regenerated for the new deps |
| `desktop/build-assets/icon.png` | new | app icon (auto‑converted to .icns/.ico) |
| `desktop/electron/main.js` | edit | auto‑update check on launch (packaged only) |
| `.github/workflows/desktop-release.yml` | new | per‑OS matrix: CPU torch → freeze → SPA → publish |
| `desktop/electron/backend.js` | edit | pin sims to CPU (`MATERIA_DEVICE` + hide GPU) |
| `backend/app/services/simulation/calculator_factory.py` | edit | `_auto_device()` honors `MATERIA_DEVICE` |
| `desktop/README.md` | edit | C3 build/release steps + unsigned caveats |
| `docs/deployment_part_c/PART_C_DESKTOP_PLAN.md` | edit | C3 status |

---

## How to cut a release / test it

```bash
# local, single‑OS installer (no publish):
cd desktop
python scripts/build_backend.py     # freeze backend → resources/backend/
npm run build:spa                   # build SPA → resources/spa/
npm install
npm run pack                        # unpacked app in dist/

# all three OS via the robot:
#   bump desktop/package.json "version" to e.g. 0.1.0, then:
git tag v0.1.0 && git push prod v0.1.0     # CI builds + publishes 3 installers
# or run the workflow manually (workflow_dispatch) for a no‑publish dry run.
```

**Acceptance (the go/no‑go gate):** a tag produces 3 installers → each installs on its
OS and runs a local MACE job → publishing a newer tag auto‑updates an installed
Windows/Linux client.

---

## Not yet (→ C4 / C5)
- **C4 — GPU/CUDA pack:** an optional NVIDIA build for faster heavy jobs. CPU ships
  first and runs everywhere.
- **C5 — code signing + notarisation:** removes the OS warnings and unlocks macOS
  auto‑update.
