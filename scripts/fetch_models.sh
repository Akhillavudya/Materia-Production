#!/usr/bin/env bash
# Provision the pre-trained ML potentials into ./pre_trained_models on a fresh server.
#
# These checkpoints (~398 MB) are deliberately NOT in git and NOT baked into the Docker
# image — docker-compose mounts ./pre_trained_models read-only into the containers.
# Run this once on a new machine before `docker compose up`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${PRE_TRAINED_MODELS_DIR:-$ROOT/pre_trained_models}"

# Expected layout (folder names the calculator factory looks for):
EXPECTED=(
  "mace_models/mace-mp-0b3-medium"
  "mace_models/mace-mpa-0-medium"
  "mace_models/mace-omat-0-medium"
  "mace_models/MACE-matpes-pbe-omat-ft"
  "matterSim_models/mattersim-v1.0.0-1M"
)

echo "Checking model checkpoints under: $DEST"
missing=0
for rel in "${EXPECTED[@]}"; do
  if [ -e "$DEST/$rel" ]; then
    echo "  ✓ $rel"
  else
    echo "  ✗ MISSING: $rel"
    missing=1
  fi
done

if [ "$missing" -eq 0 ]; then
  echo "All expected models are present."
  exit 0
fi

cat <<EOF

Some models are missing. Copy them into "$DEST" using one of:
  - rsync from your local machine:
      rsync -avz ./pre_trained_models/ user@server:$DEST/
  - or download from your model registry / HuggingFace mirror into the paths above.

(Replace this stub with your actual registry URLs once you choose one.)
EOF
exit 1
