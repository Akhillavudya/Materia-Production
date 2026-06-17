"""Celery worker entrypoint.

Run a GPU-pinned worker (concurrency=1 so one long simulation runs at a time):

    cd backend
    celery -A app.jobs.worker:celery_app worker --loglevel=info --concurrency=1

Importing `runners` here registers the `jobs.optimize` / `jobs.md` tasks on the
shared `celery_app`.

CPU threading: the worker runs one simulation at a time (concurrency=1), so we
let MACE/torch use every core. The OpenMP/MKL env vars MUST be set before numpy
or torch is imported (their native libs read them at load time), which is why
this block runs at the very top, before any app import that pulls in torch.
"""

import os

# Give the single running simulation all available cores. `setdefault` lets an
# operator override via the container env (e.g. a smaller cap on shared hosts).
_CPU = str(os.cpu_count() or 4)
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_MAX_THREADS",
             "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, _CPU)

from app.jobs.queue import celery_app
from app.jobs import runners  # noqa: F401 — side effect: registers Celery tasks

# Belt-and-suspenders: also tell torch directly, in case it was imported with a
# stale thread count somewhere upstream.
try:
    import torch

    torch.set_num_threads(int(_CPU))
except Exception:  # noqa: BLE001 — threading is an optimisation, never fatal
    pass

__all__ = ["celery_app"]
