#!/usr/bin/env bash

# Rollback helper for DocsRAG on Hetzner.
#
# This script follows the rollback flow from
# docs/hetzner_deployment_plan.md.
#
# Usage:
#   sudo ./rollback.sh /opt/docrag/releases/<known-good-release>
#
# What it does:
# - points /opt/docrag/app/current back to the specified release
# - restarts backend and frontend systemd services
# - optionally verifies the health endpoint if APP_DOMAIN is provided

set -euo pipefail

# ---- Configurable inputs ----------------------------------------------------
: "${DOC_RAG_ROOT:=/opt/docrag}"
: "${APP_DOMAIN:=}"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /opt/docrag/releases/<known-good-release>"
  exit 1
fi

TARGET_RELEASE="$1"
CURRENT_LINK="${DOC_RAG_ROOT}/app/current"

if [[ ! -d "${TARGET_RELEASE}" ]]; then
  echo "ERROR: Target release does not exist: ${TARGET_RELEASE}"
  exit 1
fi

echo "==> Switching current symlink back to ${TARGET_RELEASE}"
ln -sfn "${TARGET_RELEASE}" "${CURRENT_LINK}"

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

Rollback completed.

Current symlink now points to:
  ${TARGET_RELEASE}

If you suspect data corruption, follow the manual restore procedure from
docs/hetzner_deployment_plan.md and restore the shared data + Qdrant storage
from a pre-release backup before restarting services again.
EOF
