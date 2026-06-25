# Materia backend image — used by BOTH the API service and the Celery worker.
# Built on the server (Oracle ARM64) or locally (amd64); python:3.12-slim is multi-arch.
FROM python:3.12-slim

# Predictable, quiet Python; no pip cache to keep the image small.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build/runtime libraries some scientific wheels (pymatgen/ase/mattersim) need.
# Installed in one layer and the apt lists are removed to stay slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc g++ \
        make \
        curl \
        libgomp1 \
        tcsh \
    && rm -rf /var/lib/apt/lists/*

# ── ATAT (corrdump / getclus / mcsqs) for the SQS tool (Step 5.7) ────────────
# ATAT is compiled C++ from source (no apt/pip package). We pin a version and
# install the binaries to /usr/local/bin so the worker finds them on PATH.
# NOTE: if the upstream URL/version changes, update ATAT_URL/ATAT_VERSION below.
# This is its own layer so it caches independently of the Python deps.
ARG ATAT_VERSION=3.50
ARG ATAT_URL=https://axelvandewalle.github.io/www-avdw/atat/atat3_50.tar.gz
RUN curl -fsSL "$ATAT_URL" -o /tmp/atat.tar.gz \
    && mkdir -p /opt/atat \
    && tar -xzf /tmp/atat.tar.gz -C /opt/atat --strip-components=1 \
    && sed -i 's|^BINDIR=.*|BINDIR=/usr/local/bin|; s|^PREFIX=.*|PREFIX=/usr/local|' /opt/atat/makefile \
    && make -C /opt/atat \
    && make -C /opt/atat install \
    && rm -f /tmp/atat.tar.gz \
    # ATAT installs some scripts (e.g. getclus) as 0750 root-owned; the image runs
    # as non-root appuser, so make every ATAT binary world-readable/executable —
    # otherwise shutil.which() returns None for appuser and SQS silently degrades.
    && chmod -R a+rX /usr/local/bin \
    # Fail the build if any required ATAT binary is missing, rather than silently
    # shipping an image where generate_sqs can never run. (foolproof.sh needs tcsh.)
    && test -x /usr/local/bin/mcsqs \
    && test -x /usr/local/bin/corrdump \
    && test -x /usr/local/bin/getclus

# Install Python deps FIRST (own layer) so code edits don't re-download everything.
COPY requirements.txt .
# CPU-only PyTorch: the Oracle target is CPU-only (ARM). Install the whole torch family
# (torch + torchvision + torchaudio) together from the CPU wheel index BEFORE the rest.
# Why all three: mattersim pulls in torchvision, and a torchvision built against a
# different torch ABI fails at runtime with "operator torchvision::nms does not exist".
# Installing them together guarantees matching +cpu builds, and means mace-torch/mattersim
# reuse them instead of pulling ~2.5 GB of unused NVIDIA CUDA libraries.
RUN pip install --upgrade pip \
    && pip install --retries 5 --timeout 120 \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision torchaudio \
    && pip install --retries 5 --timeout 120 \
        --use-deprecated=legacy-resolver -r requirements.txt

# Now copy the application code.
COPY . .
RUN chmod +x docker-entrypoint.sh

# Run as a non-root user (least privilege).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe used by docker-compose healthcheck (Step 7).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
# Default command = API server. The worker service overrides this in docker-compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
