# Step 9 — A minimum test net + automated checks (CI)

## The one-sentence purpose
Write a small set of automated tests for the **critical paths**, and have a robot
(GitHub Actions) run them on every push — so the instant you break something that
used to work, you find out in seconds instead of from a frustrated student.

## The analogy
You're about to install **8 new power tools, one by one** (k-points, defects,
phonons, NEB…). Without tests, adding each one is like **renovating with the lights
off** — you won't notice you nicked the plumbing until water's on the floor. The
tests are **tripwires** that beep the moment something that used to work breaks; CI
is the **robot inspector** that trips those wires automatically on every change,
before it ever reaches the lab.

This is the single thing that turns "add 8 tools" from *scary* into *routine*: add a
tool → push → the robot re-runs every tripwire → if an old one breaks, you know
immediately and exactly which.

## What we test (the critical paths only)
A "minimum" net — fast, no network, no GPU, no ML models — covering the things that
would hurt most if they silently broke:

| Test file | Guards | Tripwire for |
|---|---|---|
| `tests/unit/test_auth.py` | Password hash round-trips; wrong password fails; tampered / expired JWT is rejected | **Login** (Step 1) |
| `tests/unit/test_caps.py` | Optimizer/MD step counts over the cap are rejected by the contract | **Compute caps** (Step 4) |
| `tests/unit/test_path_safety.py` | Absolute paths, `..` traversal, and cross-user/wrong-session access all 403 | **File isolation** — one user can't read another's files |
| `tests/unit/test_encryption.py` | A stored API key is real ciphertext and decrypts back exactly | **BYOK key-at-rest** (Step 1) |
| `tests/unit/test_config.py` | Production refuses to boot on weak secret / no Postgres / wildcard CORS / bad signup config | **Boot guards** (Steps 1, 3, 5, 8) |
| `tests/unit/test_health.py` | `/health` answers `ok` and every response carries the hardening headers + request id | **Health & headers** (Steps 7, 8) |
| `tests/validation/test_structure_tools.py`<br>`tests/validation/test_vasp_inputs.py` | (Pre-existing) the 5 structure transforms + VASP input generation produce exactly what they claim | **The tools themselves** (T2/T3) |
| `frontend/src/api/client.test.js` | Token/user round-trip through `localStorage`; logout clears; corrupt data doesn't crash | **Frontend session** handling |

Total: **66 backend tests + 4 frontend tests**, all green, running in ~13 s + <1 s.

## 📁 Files that changed & why

**New — the test net**
- `backend/tests/conftest.py` — makes `import app…` work from anywhere and forces
  development mode for the default run (the *production* guards are tested
  explicitly in `test_config.py`).
- `backend/tests/unit/*.py` — the six unit modules above.
- `frontend/src/api/client.test.js` — the frontend token-handling tests.

**New — the tooling**
- `backend/pyproject.toml` — configures **pytest** (test discovery, quiet output,
  silence third-party warnings) and **ruff** (the fast Python linter). Ruff is
  scoped to **real bugs only** (`F` = undefined names / bad imports, `E9` = syntax)
  so it catches genuine breakage without drowning CI in style nitpicks.
- `backend/requirements-test.txt` — a **slim** dependency set (no torch / MACE /
  MatterSim / phonopy — the web process and these tests never import them). CI
  installs this and runs the whole suite in well under a minute instead of building
  the ~4 GB ML image just to run pytest.
- `.github/workflows/ci.yml` — the robot inspector. **Backend job:** ruff + pytest.
  **Frontend job:** install, lint (advisory for now), vitest, production build.
  Runs on every push to `main` and every PR; a newer push cancels an in-flight run.

**Changed — dead code the linter caught (clean-code pass)**
Wiring up ruff surfaced 10 genuine unused imports / variables across the codebase;
all were removed (per the project's clean-code rule): `app/agent/graph.py`,
`app/api/chat.py`, `app/repositories/user_repository.py`,
`app/services/simulation/neb_path.py`, `app/services/simulation/optimization.py`,
`app/services/structure/adsorption.py`, `app/tools/material_tools.py`.

**Changed — frontend test setup**
- `frontend/package.json` — adds `vitest` + `jsdom` devDeps and a `test` script.
- `frontend/vite.config.js` — adds the Vitest block (`environment: 'jsdom'` so the
  token helpers get a real `localStorage`).
- `frontend/package-lock.json` — regenerated for the new devDeps.

## How to run it yourself
```bash
# Backend (from backend/, with the venv active)
pytest                       # the whole suite
ruff check app tests --select F,E9

# Frontend (from frontend/)
npm run test
```

## How it was verified
- `pytest` → **66 passed** (22 new unit + 44 existing validation).
- `ruff check app tests --select F,E9` → **All checks passed** (after the dead-code
  cleanup).
- `npm run test` → **4 passed**; `npm run build` → succeeds.

## Known follow-ups (intentionally deferred)
- The frontend **lint** step is advisory: the existing components carry ~16
  `react-hooks` violations that predate this step. Clean those, then flip the step
  to blocking.
- Ruff is deliberately scoped to `F,E9`. Widen to import-sorting/style later once
  the codebase is formatted.
