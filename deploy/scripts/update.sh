#!/usr/bin/env bash

# Update helper for DocsRAG on Hetzner.
#
# This script follows the symlink-based update flow from
# docs/hetzner_deployment_plan.md.
#
# What it does:
# - creates a pre-release backup tarball
# - clones a new release
# - creates backend virtualenv and installs requirements
# - rebuilds the frontend using the shared frontend env file
# - switches the current symlink to the new release
# - restarts frontend and backend systemd services
# - optionally verifies the health endpoint if APP_DOMAIN is provided

set -euo pipefail

# ---- Configurable inputs ----------------------------------------------------
: "${DOC_RAG_ROOT:=/opt/docrag}"
: "${RELEASE_NAME:=$(date +%F_%H%M%S)}"
: "${REPO_URL:=}"
: "${BACKEND_ENV_FILE:=${DOC_RAG_ROOT}/app/shared/backend.env}"
: "${FRONTEND_ENV_FILE:=${DOC_RAG_ROOT}/app/shared/frontend.env}"
: "${APP_DOMAIN:=}"

if [[ -z "${REPO_URL}" ]]; then
  echo "ERROR: REPO_URL is required. Example:"
  echo "  REPO_URL=git@github.com:your-org/docrag.git sudo $0"
  exit 1
fi

RELEASE_DIR="${DOC_RAG_ROOT}/releases/${RELEASE_NAME}"
CURRENT_LINK="${DOC_RAG_ROOT}/app/current"
BACKUP_DIR="${DOC_RAG_ROOT}/app/shared/backups/pre-release"

echo "==> Creating pre-release backup"
mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date +%F_%H%M%S)"
tar -czf "${BACKUP_DIR}/docrag_pre_${TIMESTAMP}.tar.gz" \
  "${DOC_RAG_ROOT}/app/shared/data" \
  "${DOC_RAG_ROOT}/app/shared/backend.env" \
  "${DOC_RAG_ROOT}/app/shared/frontend.env" \
  "/opt/docrag/qdrant/storage"

echo "==> Cloning new release ${RELEASE_NAME}"
git clone "${REPO_URL}" "${RELEASE_DIR}"

echo "==> Installing backend dependencies"
cd "${RELEASE_DIR}"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "==> Building frontend with production env"
cd "${RELEASE_DIR}/frontend"
set -a
source "${FRONTEND_ENV_FILE}"
set +a
npm ci
npm run build

echo "==> Switching current symlink"
ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

echo "==> Restarting services"
systemctl restart docrag-backend.service
systemctl restart docrag-frontend.service

if [[ -n "${APP_DOMAIN}" ]]; then
  echo "==> Verifying health endpoint"
  curl --fail --silent --show-error "https://${APP_DOMAIN}/api/health" >/dev/null
  echo "Health check OK: https://${APP_DOMAIN}/api/health"
else
  echo "APP_DOMAIN not set; skipping HTTPS health verification"
fi

cat <<EOF

Update completed.

Current release:
  ${RELEASE_DIR}

Remember to rerun ingestion manually only if the documentation corpus or
ingestion logic changed:
  cd ${CURRENT_LINK}
  source .venv/bin/activate
  set -a && source ${BACKEND_ENV_FILE} && set +a
  python scripts/ingest_all.py
EOF
