#!/usr/bin/env bash

# First-time deployment helper for DocsRAG on Hetzner.
#
# This script follows docs/hetzner_deployment_plan.md as closely as possible
# without changing application code.
#
# What it does:
# - creates the release/shared directory layout
# - clones a release into /opt/docrag/releases/<release_name>
# - creates the Python virtualenv and installs backend requirements
# - installs frontend dependencies and builds the frontend
# - switches /opt/docrag/app/current to the new release
#
# What it does NOT do:
# - create secrets for you
# - provision Qdrant
# - install systemd or nginx files into /etc
# - obtain TLS certificates

set -euo pipefail

# ---- Configurable inputs ----------------------------------------------------
# Export these before running, or override them inline.
: "${DOC_RAG_ROOT:=/opt/docrag}"
: "${RELEASE_NAME:=$(date +%F_%H%M%S)}"
: "${REPO_URL:=}"
: "${BACKEND_ENV_FILE:=${DOC_RAG_ROOT}/app/shared/backend.env}"
: "${FRONTEND_ENV_FILE:=${DOC_RAG_ROOT}/app/shared/frontend.env}"

if [[ -z "${REPO_URL}" ]]; then
  echo "ERROR: REPO_URL is required. Example:"
  echo "  REPO_URL=git@github.com:your-org/docrag.git $0"
  exit 1
fi

RELEASE_DIR="${DOC_RAG_ROOT}/releases/${RELEASE_NAME}"
CURRENT_LINK="${DOC_RAG_ROOT}/app/current"
SHARED_DIR="${DOC_RAG_ROOT}/app/shared"

echo "==> Creating shared directory layout"
mkdir -p "${SHARED_DIR}/data/indexes" "${SHARED_DIR}/logs" "${SHARED_DIR}/backups" "${DOC_RAG_ROOT}/releases"

echo "==> Verifying required env files exist"
if [[ ! -f "${BACKEND_ENV_FILE}" ]]; then
  echo "ERROR: Missing backend env file: ${BACKEND_ENV_FILE}"
  exit 1
fi
if [[ ! -f "${FRONTEND_ENV_FILE}" ]]; then
  echo "ERROR: Missing frontend env file: ${FRONTEND_ENV_FILE}"
  exit 1
fi

echo "==> Cloning release ${RELEASE_NAME}"
git clone "${REPO_URL}" "${RELEASE_DIR}"

echo "==> Creating backend virtualenv"
cd "${RELEASE_DIR}"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "==> Installing frontend dependencies and building frontend"
cd "${RELEASE_DIR}/frontend"
set -a
source "${FRONTEND_ENV_FILE}"
set +a
npm ci
npm run build

echo "==> Switching current symlink"
ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

cat <<EOF

Deployment files prepared successfully.

Next manual steps from the deployment plan:
  1. Provision/start Qdrant separately.
  2. Run ingestion once:
       cd ${CURRENT_LINK}
       source .venv/bin/activate
       set -a && source ${BACKEND_ENV_FILE} && set +a
       python scripts/ingest_all.py
  3. Install systemd units from deploy/systemd/.
  4. Install nginx config from deploy/nginx/.
  5. Start services and obtain Let's Encrypt certificates.

Release directory:
  ${RELEASE_DIR}

Current symlink:
  ${CURRENT_LINK}
EOF
