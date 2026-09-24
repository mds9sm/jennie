# Security Model

## Okta OIDC Authentication

### Flow
1. User clicks "Sign in with Okta" on the login page.
2. Frontend redirects to Okta's `/authorize` endpoint with PKCE challenge.
3. User authenticates through Okta (supports Okta MFA, Okta Verify, etc.).
4. Okta redirects back to `/api/auth/okta/callback` with an authorization code.
5. Backend exchanges the code for tokens (ID token + access token) using the client secret.
6. Backend validates the ID token: signature (Okta JWKS), issuer, audience, expiry.
7. User identity (email, name) is extracted from ID token claims.
8. A Genie session token is issued (same as password-based login).

### Feature Flag
- Okta login is **feature-flagged** via the `OKTA_CLIENT_ID` environment variable.
- When `OKTA_CLIENT_ID` is not set, the Okta button is hidden and password login is the only option.
- When set, both Okta and password login are available (password remains as fallback).

### Configuration
| Variable | Description |
|----------|-------------|
| `OKTA_CLIENT_ID` | OIDC client ID from Okta admin console |
| `OKTA_CLIENT_SECRET` | OIDC client secret (stored securely, never exposed to frontend) |
| `OKTA_ISSUER` | Okta org issuer URL (e.g., `https://your-org.okta.com/oauth2/default`) |

### First-Time Okta Users
- New users authenticated via Okta are presented with an onboarding screen.
- Onboarding collects: name (pre-filled from Okta), team, persona, pillar.
- A user record is created with a default role (viewer). Admins can upgrade the role.

### Role Change Requests
- Users can request a role change from Settings.
- The request creates an admin notification and a feedback ticket.
- Admins review and approve/deny via Settings > Users or Settings > Feedback.

### Token Security
- `OKTA_CLIENT_SECRET` is server-side only — never sent to the frontend or included in API responses.
- ID tokens are validated server-side and not stored after session creation.
- Session tokens follow the same 7-day expiry as password-based sessions.

### HMAC-Signed Auth Tokens
- Auth tokens are **HMAC-signed (SHA256)** using a secret derived from `DATABASE_URL`. This replaces the previous opaque token system.
- Each token encodes `user_id`, `email`, `role`, and `expiry` — the backend validates tokens statelessly by verifying the signature. No server-side session storage is required.
- Tokens **expire after 7 days**. After expiry, the user must re-authenticate.
- Because validation is stateless (signature-based), tokens work across **multiple pod replicas** without sticky sessions or shared session state. Any replica that shares the same `DATABASE_URL` can validate any token.

---

## Endpoint Authentication

All API endpoints require authentication (P0/P1 security fixes completed 2026-03-29). Every route checks the `X-Auth-Token` header and redirects unauthenticated requests to `/login`. A **150-test suite** covers auth enforcement, query safety, KB build, agent tools, and API endpoints.

## Query Safety

All SQL queries pass through `validate_query_safety()` before execution. This is enforced at the connection level — there is no code path that bypasses it.

### Allowed Statements
- `SELECT` — read data
- `EXPLAIN` — query plan analysis
- `ANALYZE` — update planner statistics (does not modify data)
- `SET` — session configuration (e.g., statement_timeout)
- `SHOW` — display settings
- `WITH` — common table expressions (CTEs, always followed by SELECT)

### Blocked Statements
- `CREATE`, `DROP`, `ALTER` — schema modifications
- `INSERT`, `UPDATE`, `DELETE`, `MERGE` — data modifications
- `TRUNCATE` — data deletion
- `GRANT`, `REVOKE` — permission changes
- `COPY`, `UNLOAD` — data movement

### Enforcement Points
1. `execute_real_query()` — validates before every user/Claude query
2. `_run_profile()` — validates profile SQL before execution
3. Table ops job runner — only accepts `analyze` and `profile` operations

## Credential Management

### Storage
- Credentials stored in PostgreSQL `credential_cache` table
- PostgreSQL provides encryption at rest when configured
- Credentials keyed by (session_id, environment, cred_type)

### What Is Never Exposed
- Passwords are **never logged** (only username is logged)
- Passwords are **never in Claude's context** (KnowledgeBase has no credential access)
- Passwords are **never in .env** if set via the app UI
- Passwords are **never in API responses** (only connection status returned)
- Passwords are **never in the Git repo** (.env is gitignored)

### Credential Types
| Type | Storage | Lifetime |
|------|---------|----------|
| AWS SSO access tokens | postgres + in-memory | ~4 hours (SSO session) |
| AWS SSO refresh tokens | postgres + in-memory | Until revoked or expired (~12 hours) |
| Redshift direct | postgres + in-memory | Until manually changed |

### SSO Refresh Token Persistence
- SSO refresh tokens are now saved to the `credential_cache` table in postgres (previously held in memory only).
- On backend restart, refresh tokens are auto-restored from postgres. This means SSO sessions survive container restarts and overnight maintenance windows.
- Access tokens are refreshed automatically 10 minutes before expiry using the persisted refresh token.
- This prevents scheduled reports and background jobs from failing due to SSO expiry after backend restarts.

### Restoration
On backend restart, all credentials (including SSO refresh tokens) are restored from postgres automatically. No re-authentication needed unless the refresh token itself has expired.

## Data Flow & External Boundaries

### Outbound Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Genie App (Docker Network)                       │
│                                                                      │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐                    │
│  │ Frontend │────▶│ Backend  │────▶│ Postgres │                    │
│  │ (nginx)  │     │ (FastAPI)│     │   (DB)   │                    │
│  └──────────┘     └────┬─────┘     └──────────┘                    │
│                        │ OUTBOUND ONLY (app initiates all calls)    │
└────────────────────────┼───────────────────────────────────────────-┘
                         │
          ┌──────────────┼──────────────────────────────────┐
          │              │                                   │
          ▼              ▼                                   ▼
┌──────────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────┐
│ AWS Bedrock  │ │ AWS Services │ │ GitHub API │ │   DOMO API   │
│              │ │              │ │            │ │              │
│ Receives:    │ │ Receives:    │ │ Receives:  │ │ Receives:    │
│ • System     │ │ • SSO creds  │ │ • Search   │ │ • OAuth      │
│   prompt     │ │ • API calls  │ │   queries  │ │   token      │
│ • User       │ │   (read-     │ │ • File     │ │ • Dataset    │
│   question   │ │    only)     │ │   paths    │ │   IDs        │
│ • Tool       │ │              │ │            │ │              │
│   results    │ │ Services:    │ │ No KB data │ │ READ-ONLY    │
│   (KB data)  │ │ MWAA, S3,   │ │ sent       │ │ No data sent │
│              │ │ CloudWatch,  │ │            │ │ to DOMO      │
│ Your AWS     │ │ Glue, ECS   │ │            │ │              │
│ account —    │ │              │ │            │ │              │
│ data not     │ │              │ │            │ │              │
│ used for     │ │              │ │            │ │              │
│ training     │ │              │ │            │ │              │
└──────────────┘ └──────────────┘ └────────────┘ └──────────────┘
```

### What Flows Where

| Destination | Trigger | Data Sent | Sensitivity | Data Policy |
|---|---|---|---|---|
| **AWS Bedrock** | User asks a question | System prompt + user message + tool results (KB snippets, table names, SQL) | **Medium** — contains platform metadata | Your AWS account. [Not used for training](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html) |
| **AWS MWAA/S3/CloudWatch** | KB build or `aws_lookup` | SSO creds + read-only API calls | Low — metadata queries only | Your AWS account |
| **GitHub API** | MCP tools or repo clone | Search queries, file paths, repo names | Low — code search terms | GitHub Enterprise (the organization org) |
| **DOMO API** | DOMO tools (when configured) | OAuth token + dataset IDs | Low ��� metadata only, read-only | the organization DOMO instance |
| **Statsig Console API** | Statsig tools (when configured) | Read-only API key + experiment/gate IDs | Low — metadata only, read-only | Statsig (read-only Console API) |
| **Anthropic API** | Only if `AI_PROVIDER=anthropic` | Same as Bedrock | **Medium** | Anthropic. Not used for training on API plan |

### Swagger Event Schemas

The 558 ProductApp event schemas are served from a static JSON file (`knowledge/event_schemas.json`) bundled at build time. **No external API calls** are made at runtime to serve event schema data. The Swagger spec was imported once during development and is maintained as a static asset.

### What NEVER Leaves the App

- **Redshift passwords** — encrypted in postgres, never in prompts, never logged
- **DOMO client secret** — never logged, never in prompts
- **Statsig API key** — stored encrypted in postgres, never in prompts, never logged
- **User passwords** — hashed (PBKDF2), never reversible
- **Raw query result data** — stays in SSE stream to browser, not persisted externally
- **Uploaded documents** — text extracted in-memory, not stored on disk after processing

### What Does NOT Happen

- **No telemetry** — zero analytics, tracking pixels, or usage reporting to third parties
- **No unsolicited outbound calls** — the app never phones home
- **No data sharing** — KB data is not shared with model providers for training
- **No third-party services** — no SaaS dependencies beyond AWS, GitHub, DOMO, Statsig (all the organization-controlled)

### The Bedrock Tradeoff

The core tradeoff: KB metadata (table names, DAG configs, view SQL, lineage) flows to AWS Bedrock for AI inference. This is required for the AI to answer questions. Mitigations:
- Runs in **your AWS account** (not Anthropic's infrastructure)
- AWS Bedrock [does not use customer data for model training](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html)
- **Credentials are excluded** — query safety, credential isolation, and prompt construction ensure passwords/secrets never enter AI context
- To eliminate this flow entirely, you would need to run a self-hosted model (not currently supported)

## Network Security

- Backend container mounts `~/.aws:ro` (read-only) for fallback AWS profiles
- All Redshift connections use SSL by default
- MWAA API accessed via HTTPS with session cookies
- Frontend proxies all API calls through nginx (no direct backend exposure needed)
- DOMO API: `DOMO_VERIFY_SSL=true` in prod (IT injects corporate CA cert), `false` in local dev
- No inbound ports exposed except 3333 (nginx) and 8000 (backend, internal only in prod)

## RBAC (Implemented)

Role-based access control with 4 roles and 22 granular permissions:

| Role | Access |
|------|--------|
| **viewer** | Chat and catalog read-only |
| **analyst** | + query execution, glossary contributions |
| **engineer** | + pipeline building, git operations, table ops |
| **admin** | + ANALYZE on prod, credential management, schedule config, KB builds |

Settings tabs are role-gated — users only see tabs their role permits.

## Document Upload Security

- Uploads limited to **5MB** maximum file size
- **Text-only extraction** — no executable content is processed or stored. Binary formats (.pdf, .docx) are parsed for text only.
- AI extraction runs through the **same Claude API provider** configured for chat (Anthropic direct or Bedrock). No additional external services involved.
- Uploaded document text is stored **only in the feedback ticket description** (first 500 characters for context). The raw uploaded file is not persisted on disk or in the database after extraction completes.
- Extracted glossary terms go through the standard feedback review workflow before entering the knowledge base.

## Multi-User Isolation

- **Per-user git worktrees**: Each user gets an isolated worktree at `/app/data-repo-worktrees/{user_id}`, preventing branch/commit conflicts between users.
- **User-scoped chat sessions**: Sessions are filtered by `user_id` — users can only see their own conversations.
- **User-scoped settings**: Preferences (persona, system prompt, user context) are keyed by `user_id` and persist across login sessions.
- **Auth token on every request**: `fetchJSON` sends an `X-Auth-Token` header on every API call for user identification.
