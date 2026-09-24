# Deployment Guide

## Architecture

```
                    ┌─────────────┐
                    │   Frontend  │
                    │  (Nginx)    │ ← Static React app + API proxy
                    │  Port 80    │
                    └──────┬──────┘
                           │ /api/*
                    ┌──────▼──────┐
                    │   Backend   │
                    │  (FastAPI)  │ ← AI agents, KB builder, auth
                    │  Port 8000  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼───┐  ┌────▼────┐
        │ RDS Postgres│ │ AWS   │  │ Redshift│
        │ (managed)   │ │ MWAA  │  │ (np/prd)│
        └─────────────┘ └───────┘  └─────────┘
```

## Prerequisites

- Docker + Docker Compose
- RDS PostgreSQL instance (accessible from app)
- AWS SSO access (for MWAA + Bedrock)
- GitHub token (for repo KB source + MCP GitHub server)
- **Node.js** (installed in backend Docker image for MCP server subprocess)

## Quick Start (Production)

### 1. Configure Environment

Create `.env` in the project root:

```bash
# Required
DATABASE_URL=postgresql://genie:YOUR_PASSWORD@your-rds-host.us-west-2.rds.amazonaws.com:5432/genie

# AI Provider (choose one)
AI_PROVIDER=bedrock
BEDROCK_MODEL=us.anthropic.claude-opus-4-6-v1
BEDROCK_REGION=us-west-2
# OR
# AI_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...

# Git Repo for KB
REPO_URL=https://github.com/your-org/data-platform-dags
GITHUB_TOKEN=ghp_...

# Okta SSO (optional — enables "Sign in with Okta")
OKTA_CLIENT_ID=0oa...
OKTA_CLIENT_SECRET=...
OKTA_ISSUER=https://your-org.okta.com/oauth2/default
APP_URL=https://genie.example.com
```

### 2. Initialize Database

Connect to RDS and run the schema:

```bash
psql $DATABASE_URL -f db/init.sql
```

### 3. Build & Deploy

```bash
# Build production images
docker compose -f docker-compose.prod.yml build

# Start services
docker compose -f docker-compose.prod.yml up -d

# Verify
curl http://localhost:8000/api/health
```

### 4. First Login

1. Navigate to `https://genie.example.com`
2. Login with `admin@example.com` (any password on first login sets it)
3. You're the default admin

### 5. Post-Deploy Setup

1. **Settings → Connection** — Connect AWS SSO (nonprod + prod)
2. **Settings → Connection** — Set Redshift credentials (nonprod + prod)
3. **Settings → Knowledge Base** — Build KB (select MWAA + Repo)
4. **Settings → Users** — Add team members

## Container Images

| Image | Dockerfile | Base | Size (approx) |
|-------|-----------|------|---------------|
| Backend | `Dockerfile.backend` | python:3.11-slim + Node.js (for MCP). Note: `pydomo` SDK removed — DOMO uses direct REST API. | ~350MB |
| Frontend | `Dockerfile.frontend` | nginx:alpine | ~30MB |

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://genie:pass@rds-host:5432/genie` |

### AI Provider (choose one)

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_PROVIDER` | `bedrock` or `anthropic` | `bedrock` |
| `BEDROCK_MODEL` | Bedrock model ID | `us.anthropic.claude-opus-4-6-v1` |
| `BEDROCK_REGION` | AWS region | `us-west-2` |
| `ANTHROPIC_API_KEY` | Anthropic API key (if using anthropic) | |

### Okta SSO (optional)

| Variable | Description |
|----------|-------------|
| `OKTA_CLIENT_ID` | OIDC app client ID from Okta admin |
| `OKTA_CLIENT_SECRET` | OIDC app client secret |
| `OKTA_ISSUER` | Okta issuer URL (default: `https://your-org.okta.com/oauth2/default`) |
| `APP_URL` | Production URL (default: `https://genie.example.com`) |

### Git / KB

| Variable | Description |
|----------|-------------|
| `REPO_URL` | GitHub repo URL |
| `GITHUB_TOKEN` | GitHub PAT (repo scope + SAML SSO for your-org). Also used by MCP GitHub server. |

### Statsig (optional)

| Variable | Description |
|----------|-------------|
| `STATSIG_CONSOLE_API_KEY` | Statsig Console API key (read-only). Enables experiment/feature gate lookups and prd_statsig exposure table queries. |

### DOMO (optional — prefer Settings > Connection)

| Variable | Description |
|----------|-------------|
| `DOMO_CLIENT_ID` | DOMO OAuth client ID (same as Airflow DOMO_REFRESH DAGs) |
| `DOMO_CLIENT_SECRET` | DOMO OAuth client secret |
| `DOMO_VERIFY_SSL` | SSL verification for DOMO API (default: `true`, set `false` for local dev behind corporate proxy) |

### Redshift

| Variable | Description |
|----------|-------------|
| `REDSHIFT_NP_HOST` | Nonprod cluster hostname |
| `REDSHIFT_PRD_HOST` | Prod cluster hostname |
| `REDSHIFT_NP_USER` / `_PASSWORD` | Direct creds (optional, can set in-app) |
| `REDSHIFT_PRD_USER` / `_PASSWORD` | Direct creds (optional, can set in-app) |

## Persistent Volumes

| Volume | Path | Purpose |
|--------|------|---------|
| `repo_data` | `/app/data-repo` | Workbench git clone (user edits) |
| `repo_kb` | `/app/data-repo-kb` | KB builder clone (always main) |
| `repo_worktrees` | `/app/data-repo-worktrees` | Per-user git worktrees |
| `knowledge_data` | `/app/knowledge` | KB files (catalog, transforms, lineage) |

## Health Checks

| Service | Endpoint | Expected |
|---------|----------|----------|
| Backend | `GET /api/health` | `{"status": "ok"}` |
| Frontend | `GET /` | HTTP 200 |

## K8s Deployment

For Kubernetes deployments, each container has specific configuration requirements.

### Frontend Container

| Config | Description |
|--------|-------------|
| `BACKEND_URL` | Backend service URL for nginx proxy (e.g., `http://backend-svc:8000`). In **proxy mode**, nginx forwards `/api/*` to this URL. In **static mode** (no `BACKEND_URL`), the frontend serves files only and the client calls the backend directly. |
| `VITE_API_BASE` | Runtime API base URL injected into the browser via `start-nginx.sh`. The entrypoint script writes `window.__ENV__ = { VITE_API_BASE: "..." }` into `/usr/share/nginx/html/env.js`, which the app loads at startup. This avoids baking the backend URL into the Docker image at build time. |

The frontend image uses a custom `start-nginx.sh` entrypoint that:
1. Reads `VITE_API_BASE` from the pod environment
2. Writes it to `env.js` as `window.__ENV__`
3. Starts nginx

Health probe: `GET /` on port 80 (HTTP 200).

### Backend Container

| Config | Required | Description |
|--------|----------|-------------|
| `DATABASE_URL` | **Yes** | PostgreSQL connection string. Only required env var — everything else is configurable from the Settings UI. |
| `GITHUB_TOKEN` | No | Can be set via Settings > Connection |
| `REPO_URL` | No | Can be set via Settings > Connection (no env var needed) |
| `DOMO_CLIENT_ID` / `DOMO_CLIENT_SECRET` | No | Can be set via Settings > Connection |
| `STATSIG_CONSOLE_API_KEY` | No | Can be set via Settings > Connection |
| S3 storage config | No | Persists across pods via postgres fallback |

Health probe: `GET /api/health` on port 8000 (returns `{"status": "ok"}`).

### Signed HMAC Auth Tokens

Auth tokens are signed using an HMAC key derived from `DATABASE_URL`. This means:
- Tokens are **consistent across all pods** sharing the same database — no sticky sessions required.
- Tokens **survive pod restarts** — users stay logged in as long as `DATABASE_URL` doesn't change.
- No separate `SECRET_KEY` env var needed.

### KB Builds

Knowledge base builds are **non-blocking** — all sync steps (MWAA fetch, repo clone, Redshift metadata) run via `asyncio.to_thread`, so the event loop stays responsive. A 90-minute KB build will not block health probes, chat requests, or other API calls. Configure liveness/readiness probes with generous timeouts but they will not be affected by long-running builds.

### Database Initialization

Run `db/init.sql` against the database before first deploy:

```bash
psql $DATABASE_URL -f db/init.sql
```

The script creates 23 tables, all using `IF NOT EXISTS` — safe to re-run on every deploy or as an init container.

### Health Endpoints

| Service | Endpoint | Port | Expected |
|---------|----------|------|----------|
| Backend | `GET /api/health` | 8000 | `{"status": "ok"}` |
| Frontend | `GET /` | 80 | HTTP 200 |

### Example K8s Manifests

```yaml
# Backend Deployment (excerpt)
containers:
  - name: backend
    image: your-org/jennie-backend:1.0.0
    ports:
      - containerPort: 8000
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: genie-secrets
            key: database-url
    livenessProbe:
      httpGet:
        path: /api/health
        port: 8000
      initialDelaySeconds: 10
      periodSeconds: 30
    readinessProbe:
      httpGet:
        path: /api/health
        port: 8000
      initialDelaySeconds: 5
      periodSeconds: 10

# Frontend Deployment (excerpt)
containers:
  - name: frontend
    image: your-org/jennie-frontend:1.0.0
    ports:
      - containerPort: 80
    env:
      - name: BACKEND_URL
        value: "http://backend-svc:8000"
      - name: VITE_API_BASE
        value: "https://genie.example.com"
    livenessProbe:
      httpGet:
        path: /
        port: 80
      initialDelaySeconds: 5
      periodSeconds: 30
```

## K8s Deployment

For Kubernetes environments (EKS, ECS, etc.), the app is designed to run as stateless pods with an external RDS database.

### Frontend Container

| Setting | Description |
|---------|-------------|
| Image | `Dockerfile.frontend` (nginx:alpine) |
| Port | `80` |
| Health probe | `GET /` → HTTP 200 |
| `BACKEND_URL` | **Proxy mode** (default): set to `http://backend-service:8000`. Nginx proxies `/api/*` to backend. **Static mode**: omit `BACKEND_URL`, frontend calls backend directly (requires CORS + ingress routing). |
| `VITE_API_BASE` | Runtime injection via `start-nginx.sh`. The entrypoint script writes `window.__ENV__ = { VITE_API_BASE: "..." }` into `/usr/share/nginx/html/env-config.js` at container startup, so the React app picks up the backend URL without a rebuild. |

### Backend Container

| Setting | Description |
|---------|-------------|
| Image | `Dockerfile.backend` (python:3.11-slim + Node.js) |
| Port | `8000` |
| Health probe | `GET /api/health` → `{"status": "ok"}` |
| `DATABASE_URL` | **Required**. PostgreSQL connection string. All other state (sessions, credentials, KB metadata) lives here. |
| UI-configurable | GitHub token, DOMO credentials, Statsig API key, REPO_URL, S3 storage config — all settable from Settings UI at runtime. No env vars needed for these. |

### Signed HMAC Auth Tokens

Auth tokens are HMAC-signed using a key derived from `DATABASE_URL`. This means:
- Tokens are valid across all pods sharing the same database (no sticky sessions needed).
- Sessions survive pod restarts and rolling deployments.
- No separate `SECRET_KEY` env var required — the database URL is the shared secret.

### KB Builds

KB builds run as non-blocking background tasks using `asyncio.to_thread` for all synchronous steps (MWAA fetches, repo clones, Redshift metadata). This means:
- Builds can take up to 90 minutes without affecting the event loop.
- Health probes (`/api/health`) continue responding during builds.
- No special liveness/readiness probe configuration needed.
- Build progress is tracked in postgres (`kb_builds` table) and pollable via API.

### Database Initialization

Run `init.sql` against your RDS instance before first deploy:

```bash
psql $DATABASE_URL -f db/init.sql
```

The schema defines 23 tables, all using `CREATE TABLE IF NOT EXISTS` — safe to re-run on every deploy without data loss. Can be used as a Kubernetes init container or a Helm pre-install hook.

### Health Endpoints

| Service | Endpoint | Port | Expected |
|---------|----------|------|----------|
| Backend | `GET /api/health` | 8000 | `{"status": "ok"}` |
| Frontend | `GET /` | 80 | HTTP 200 |

Use these for both liveness and readiness probes. The backend health endpoint does not depend on external services (Redshift, MWAA, etc.), so it will not flap during outages of upstream dependencies.

### Example K8s Resource Hints

```yaml
# Backend
resources:
  requests: { cpu: 250m, memory: 512Mi }
  limits:   { cpu: "1", memory: 2Gi }
livenessProbe:
  httpGet: { path: /api/health, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /api/health, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 10

# Frontend
resources:
  requests: { cpu: 50m, memory: 64Mi }
  limits:   { cpu: 200m, memory: 128Mi }
livenessProbe:
  httpGet: { path: /, port: 80 }
  periodSeconds: 30
```

## Scaling Notes

- Backend: stateless (except in-memory SSO creds). Can run 2+ workers via `--workers N`.
- Frontend: fully static. Scale horizontally behind ALB.
- PostgreSQL: single RDS instance sufficient for <100 users.
- Knowledge base files: stored on persistent volume, loaded into memory at startup.

## Monitoring

- Backend logs: `docker compose -f docker-compose.prod.yml logs -f backend`
- Usage tracking: `SELECT * FROM usage_events ORDER BY created_at DESC LIMIT 20`
- KB builds: `SELECT * FROM kb_builds ORDER BY id DESC LIMIT 5`
- Active sessions: check `credential_cache` table for SSO token expiry

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Backend won't start | Check `DATABASE_URL` — must be accessible from container |
| Chat returns error | Check AI provider config — SSO connected for Bedrock? Check MCP server started (Node.js required). |
| KB build fails | Check SSO credentials — may have expired |
| Login loop | Clear browser localStorage (`genie_auth_token`) |
| Okta callback fails | Verify `APP_URL` matches the redirect URI registered in Okta |
