# Hetzner Deployment Plan

Last updated: 2026-06-13

## Scope

This document provides a **practical first-deployment plan** for DocsRAG on:

- **Hetzner VPS**
- **Ubuntu 24.04**
- **systemd**
- **nginx reverse proxy**
- **Let's Encrypt SSL**
- the **existing Python backend**
- the **existing Svelte frontend**

This plan is based on `docs/deployment_readiness.md` and the current repository structure.

Documentation only. No application code changes are included here.

---

## 1) Recommended server sizing

### Recommended first production size

Use:

- **Hetzner CPX31 or comparable**
- **4 vCPU**
- **8 GB RAM**
- **80 GB SSD**

Why this size:

- backend API is lightweight, but Qdrant needs memory headroom
- ingestion artifacts and Qdrant persistence need disk margin
- frontend build/runtime is small, but Node + Python + Qdrant on one host benefits from extra RAM
- leaves room for logs, backups, package updates, and future growth

### Minimum viable size

If traffic is very low and corpus remains modest:

- **2 vCPU**
- **4 GB RAM**
- **40 GB SSD**

Use this only for a small private launch.

---

## 2) Deployment architecture

Recommended first-production topology on one VPS:

1. **nginx** on public ports `80/443`
2. **frontend** running locally on `127.0.0.1:4173`
3. **backend** running locally on `127.0.0.1:8000`
4. **Qdrant** running locally on `127.0.0.1:6333`
5. **optional Redis** running locally only if explicitly enabled later

### Important current frontend constraint

The current frontend uses:

- SvelteKit
- `@sveltejs/adapter-auto`

That means there is **no explicit production adapter configured yet**.

For the first Hetzner deployment, the most realistic plan **without code changes** is:

- build frontend with `npm run build`
- serve it using `npm run preview -- --host 127.0.0.1 --port 4173`
- place nginx in front of it

This is acceptable for a **first controlled deployment**, but it is **not the ideal long-term production setup**. Later, switch to a dedicated SvelteKit production adapter.

---

## 3) Required Ubuntu packages

Install base packages:

```bash
sudo apt update
sudo apt install -y \
  nginx \
  certbot \
  python3-certbot-nginx \
  python3 \
  python3-venv \
  python3-pip \
  git \
  curl \
  rsync \
  unzip \
  ufw \
  logrotate
```

Install Node.js 20 LTS:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

Install Qdrant:

Option A — simplest operationally for first deploy: **Docker only for Qdrant**

```bash
sudo apt install -y docker.io
sudo systemctl enable --now docker
```

Option B — run Qdrant by another method if your team already has one.

This plan assumes **Option A** because the app itself is not Dockerized, but Qdrant is easiest to run reliably that way.

---

## 4) Recommended server directory layout

Use a stable layout under `/opt/docrag`:

```text
/opt/docrag/
├── app/
│   ├── current -> /opt/docrag/releases/2026-06-13_120000/
│   └── shared/
│       ├── backend.env
│       ├── frontend.env
│       ├── data/
│       │   ├── indexes/
│       │   └── docs_store.pkl
│       ├── logs/
│       └── backups/
└── releases/
    ├── 2026-06-13_120000/
    ├── 2026-06-20_101500/
    └── ...
```

### Why this layout

- supports clean updates
- supports fast rollback by switching symlink
- keeps secrets and persistent data outside release directories
- avoids losing `.env`, data, and logs on each deploy

---

## 5) Repo checkout and runtime setup

Example first-time setup:

```bash
sudo mkdir -p /opt/docrag/app/shared/{data/indexes,logs,backups}
sudo mkdir -p /opt/docrag/releases
sudo chown -R $USER:$USER /opt/docrag

cd /opt/docrag/releases
git clone /home/<you>/docrag 2026-06-13_120000
ln -sfn /opt/docrag/releases/2026-06-13_120000 /opt/docrag/app/current
```

Backend venv setup:

```bash
cd /opt/docrag/app/current
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Frontend setup:

```bash
cd /opt/docrag/app/current/frontend
npm ci
```

---

## 6) `.env` and secret handling

### Backend env file

Create:

- `/opt/docrag/app/shared/backend.env`

Recommended permissions:

```bash
chmod 600 /opt/docrag/app/shared/backend.env
```

Minimum initial content example:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=replace-me
ANTHROPIC_MODEL=claude-sonnet-4-6

OPENAI_API_KEY=replace-me
OPENAI_EMBED_MODEL=text-embedding-3-small

QDRANT_HOST=127.0.0.1
QDRANT_PORT=6333
QDRANT_COLLECTION=ai_docs

BM25_INDEX_PATH=/opt/docrag/app/shared/data/indexes/bm25_index.pkl
DOCS_STORE_PATH=/opt/docrag/app/shared/data/docs_store.pkl

CORS_ALLOWED_ORIGINS=https://your-domain.example
MAX_REQUEST_BODY_BYTES=10240
RATE_LIMIT_ENABLED=true

USE_REDIS_CACHE=false
USE_REDIS_SESSIONS=false
SESSION_TTL_SECONDS=3600
MAX_SESSIONS=50

RERANKER_BACKEND=nvidia
NVIDIA_API_KEY=replace-me-if-using-nvidia-reranker
RERANKER_NVIDIA_MODEL=nvidia/llama-nemotron-rerank-1b-v2
RERANKER_DEVICE=cpu

DEBUG_API_ERRORS=false
TELEMETRY_ENABLED=false
```

### Frontend env file

Create:

- `/opt/docrag/app/shared/frontend.env`

Content:

```dotenv
VITE_API_BASE_URL=https://your-domain.example/api
```

### Important notes

1. The frontend reads `VITE_API_BASE_URL` **at build time**.
2. The backend reads env vars from runtime/systemd.
3. Do not store secrets in the frontend env file.
4. Keep both env files **outside the git checkout**.

---

## 7) Qdrant deployment on the VPS

### Create persistent storage

```bash
sudo mkdir -p /opt/docrag/qdrant/storage
sudo chown -R 1000:1000 /opt/docrag/qdrant
```

### Start Qdrant container

```bash
sudo docker run -d \
  --name qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -v /opt/docrag/qdrant/storage:/qdrant/storage \
  qdrant/qdrant:latest
```

### Validate Qdrant

```bash
curl http://127.0.0.1:6333/collections
```

---

## 8) Initial ingestion/bootstrap procedure

This must happen **before** the backend is considered ready for users.

### Run ingestion once

```bash
cd /opt/docrag/app/current
source .venv/bin/activate
set -a
source /opt/docrag/app/shared/backend.env
set +a
python scripts/ingest_all.py
```

### Validate artifacts

Check that these exist:

- `/opt/docrag/app/shared/data/indexes/bm25_index.pkl`
- `/opt/docrag/app/shared/data/docs_store.pkl`

And verify Qdrant collection exists:

```bash
curl http://127.0.0.1:6333/collections/ai_docs
```

---

## 9) systemd service files

## 9.1 Backend service

Create `/etc/systemd/system/docrag-backend.service`:

```ini
[Unit]
Description=DocsRAG FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/docrag/app/current
EnvironmentFile=/opt/docrag/app/shared/backend.env
ExecStart=/opt/docrag/app/current/.venv/bin/python scripts/serve.py --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30
StandardOutput=append:/opt/docrag/app/shared/logs/backend.log
StandardError=append:/opt/docrag/app/shared/logs/backend.log

[Install]
WantedBy=multi-user.target
```

### Permissions note

Ensure `www-data` can read:

- current release directory
- backend env file
- shared data directory
- shared logs directory

Example:

```bash
sudo chgrp -R www-data /opt/docrag/app/shared
sudo chmod -R g+rX /opt/docrag/app/shared
sudo chmod -R g+w /opt/docrag/app/shared/logs
sudo chmod -R g+w /opt/docrag/app/shared/data
```

## 9.2 Frontend service

Because the frontend currently uses `adapter-auto`, this plan runs the built preview server behind nginx.

Create `/etc/systemd/system/docrag-frontend.service`:

```ini
[Unit]
Description=DocsRAG Svelte frontend preview server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/docrag/app/current/frontend
EnvironmentFile=/opt/docrag/app/shared/frontend.env
ExecStart=/usr/bin/npm run preview -- --host 127.0.0.1 --port 4173
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30
StandardOutput=append:/opt/docrag/app/shared/logs/frontend.log
StandardError=append:/opt/docrag/app/shared/logs/frontend.log

[Install]
WantedBy=multi-user.target
```

### Build step before starting frontend

Run this before enabling the frontend service:

```bash
cd /opt/docrag/app/current/frontend
set -a
source /opt/docrag/app/shared/frontend.env
set +a
npm ci
npm run build
```

### Important caveat

`npm run preview` is acceptable for a first controlled deployment, but it is **not** the ideal long-term production target for SvelteKit.

---

## 10) Enable and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable docrag-backend.service
sudo systemctl enable docrag-frontend.service

sudo systemctl start docrag-backend.service
sudo systemctl start docrag-frontend.service
```

Check status:

```bash
sudo systemctl status docrag-backend.service
sudo systemctl status docrag-frontend.service
```

Smoke test locally:

```bash
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:4173
```

---

## 11) nginx reverse proxy config

Create `/etc/nginx/sites-available/docrag.conf`:

```nginx
server {
    listen 80;
    server_name your-domain.example www.your-domain.example;

    client_max_body_size 1m;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:4173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
    }
}
```

### Why `/api/`

The frontend expects `VITE_API_BASE_URL=https://your-domain.example/api`.

Because nginx uses:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000/;
}
```

requests like:

- `/api/chat`
- `/api/chat/stream`

are correctly forwarded to backend routes:

- `/chat`
- `/chat/stream`

### Enable nginx site

```bash
sudo ln -s /etc/nginx/sites-available/docrag.conf /etc/nginx/sites-enabled/docrag.conf
sudo nginx -t
sudo systemctl reload nginx
```

---

## 12) SSL with Let's Encrypt

### Prerequisites

Before requesting certificates:

1. domain DNS points to the Hetzner VPS
2. nginx is serving on port 80
3. firewall allows `80` and `443`

### Obtain certificate

```bash
sudo certbot --nginx -d your-domain.example -d www.your-domain.example
```

Choose redirect to HTTPS when prompted.

### Verify renewal

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

---

## 13) Firewall and base host hardening

Basic UFW setup:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Recommended additional hardening:

- disable password SSH if possible
- use SSH keys only
- install security updates regularly
- keep Qdrant bound to localhost only
- keep backend/frontend bound to localhost only

---

## 14) Backup strategy

## What to back up

Back up all of the following:

1. `/opt/docrag/app/shared/data/`
2. `/opt/docrag/qdrant/storage/`
3. `/opt/docrag/app/shared/backend.env`
4. `/opt/docrag/app/shared/frontend.env`
5. release metadata / deploy logs

### What not to back up blindly

- `.venv/`
- `node_modules/`
- temporary scraper cache in `/tmp`

## Recommended backup schedule

- nightly file backup of shared data and env files
- nightly Qdrant storage snapshot/copy
- pre-release backup before each deployment
- weekly off-server copy if possible

## Simple backup directory example

```text
/opt/docrag/app/shared/backups/
├── daily/
├── weekly/
└── pre-release/
```

## Simple backup command pattern

Example using tar:

```bash
timestamp=$(date +%F_%H%M%S)
tar -czf /opt/docrag/app/shared/backups/pre-release/docrag_shared_${timestamp}.tar.gz \
  /opt/docrag/app/shared/data \
  /opt/docrag/app/shared/backend.env \
  /opt/docrag/app/shared/frontend.env \
  /opt/docrag/qdrant/storage
```

### Minimum retention recommendation

- 7 daily backups
- 4 weekly backups
- last 3 pre-release backups

---

## 15) Update procedure

This plan assumes a symlink-based release model.

### Step 1 — create pre-release backup

```bash
timestamp=$(date +%F_%H%M%S)
mkdir -p /opt/docrag/app/shared/backups/pre-release
tar -czf /opt/docrag/app/shared/backups/pre-release/docrag_pre_${timestamp}.tar.gz \
  /opt/docrag/app/shared/data \
  /opt/docrag/app/shared/backend.env \
  /opt/docrag/app/shared/frontend.env \
  /opt/docrag/qdrant/storage
```

### Step 2 — create new release directory

```bash
cd /opt/docrag/releases
git clone <YOUR_REPO_URL> 2026-06-20_101500
```

### Step 3 — install backend dependencies

```bash
cd /opt/docrag/releases/2026-06-20_101500
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4 — build frontend using production env

```bash
cd /opt/docrag/releases/2026-06-20_101500/frontend
set -a
source /opt/docrag/app/shared/frontend.env
set +a
npm ci
npm run build
```

### Step 5 — switch symlink

```bash
ln -sfn /opt/docrag/releases/2026-06-20_101500 /opt/docrag/app/current
```

### Step 6 — restart services

```bash
sudo systemctl restart docrag-backend.service
sudo systemctl restart docrag-frontend.service
```

### Step 7 — verify

```bash
curl https://your-domain.example/api/health
```

Also verify:

- homepage loads
- one `/chat` request works
- one `/chat/stream` request works

### Optional Step 8 — rerun ingestion when required

Only if documentation corpus / ingestion logic changed:

```bash
cd /opt/docrag/app/current
source .venv/bin/activate
set -a
source /opt/docrag/app/shared/backend.env
set +a
python scripts/ingest_all.py
```

---

## 16) Rollback procedure

### Fast rollback with symlink switch

1. identify previous known-good release
2. point `/opt/docrag/app/current` back to it
3. restart backend and frontend services

Example:

```bash
ln -sfn /opt/docrag/releases/2026-06-13_120000 /opt/docrag/app/current
sudo systemctl restart docrag-backend.service
sudo systemctl restart docrag-frontend.service
```

### Verify rollback

```bash
curl https://your-domain.example/api/health
```

Then verify:

- frontend renders
- one `/chat` request succeeds
- one `/chat/stream` request succeeds

### If data corruption is suspected

Restore from pre-release backup:

1. stop backend
2. stop frontend
3. stop Qdrant container
4. restore backed-up shared data and Qdrant storage
5. restart Qdrant
6. restart app services

---

## 17) Post-deploy verification checklist

- [ ] `systemctl status docrag-backend` is healthy
- [ ] `systemctl status docrag-frontend` is healthy
- [ ] `docker ps` shows Qdrant running
- [ ] `https://your-domain.example` loads
- [ ] `https://your-domain.example/api/health` returns 200
- [ ] `/chat` works
- [ ] `/chat/stream` works
- [ ] SSL certificate is valid
- [ ] certbot renewal dry-run succeeds
- [ ] backup path exists and is writable
- [ ] logs are being written

---

## 18) Known limitations of this first plan

1. Frontend uses `adapter-auto` and is served through `npm run preview`.
2. Backend still lacks native deployment auth strategy in code.
3. Health endpoint is basic and does not validate all dependencies.
4. Redis is not included by default.
5. This is a **single-node** plan; no HA/failover.

---

## Final recommendation

For the first Hetzner deployment, use:

- **Ubuntu 24.04**
- **4 vCPU / 8 GB RAM / 80 GB SSD**
- **nginx + Let's Encrypt**
- **systemd-managed backend and frontend**
- **Qdrant on the same host with persistent storage**
- **symlink-based releases for safe updates and rollback**

This is the most practical plan that fits the **current repository without code changes**.
