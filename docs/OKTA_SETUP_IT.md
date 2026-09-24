# Okta OIDC Setup — IT Configuration Guide

**Requested by:** Data Platform team (Jennie)  
**Purpose:** Enable employees to connect Genie's MCP servers to claude.ai using the organization's corporate SSO (Okta). Users click "Connect" in claude.ai → Okta popup → auto-close. One-time per user.

---

## What We Need

One new Okta OIDC application registered in the the organization Okta tenant. This is a standard OAuth 2.0 / OpenID Connect Authorization Code flow with PKCE.

---

## Step-by-Step: Create the Okta OIDC Application

### 1. Log in to Okta Admin Console

- URL: `https://your-org-admin.okta.com` (or your admin console URL)
- Role required: Okta Administrator

---

### 2. Create a New Application

1. Navigate to **Applications → Applications**
2. Click **Create App Integration**
3. Select:
   - **Sign-in method:** OIDC – OpenID Connect
   - **Application type:** Web Application
4. Click **Next**

---

### 3. Configure the Application

**General Settings:**

| Field | Value |
|-------|-------|
| App integration name | `Jennie MCP` |
| Logo | *(optional — use Genie logo if available)* |

**Grant type:**
- Check: **Authorization Code**
- Check: **Refresh Token** *(required for long-lived MCP sessions)*

**Sign-in redirect URIs** (add all of these):
```
https://claude.ai/api/mcp/auth_callback
https://dev-apis.example.com/genie/oauth/callback
http://localhost:8000/oauth/callback
```

> `claude.ai/api/mcp/auth_callback` is Anthropic's standard OAuth callback for MCP connectors.  
> The `/genie/oauth/callback` is Genie's own backend callback (handles token exchange).  
> `localhost` is for local developer testing only.

**Sign-out redirect URIs:**
```
https://claude.ai
https://dev-apis.example.com/genie
```

**Assignments:**
- Select: **Limit access to selected groups**
- Add group: `Everyone` (or restrict to a specific data team group if preferred)

Click **Save**.

---

### 4. Configure Token Settings

After saving, go to the **Sign On** tab of the new application:

**OpenID Connect ID Token:**
- Groups claim filter: `Starts with` → `your-org` *(optional — for role mapping)*

**Refresh Token:**
- Rotation: **Rotate token after every use**
- Lifetime: **90 days** (recommended)
- Grace period: **30 seconds**

---

### 5. Collect Credentials for the Data Platform Team

Once the app is created, share the following with the data platform team (Sri Maru):

| Item | Where to find it | Example |
|------|-----------------|---------|
| **Client ID** | Application → General tab → Client Credentials | `0oa1b2c3d4e5f6g7h8i9` |
| **Client Secret** | Application → General tab → Client Secrets → Click to reveal | `abc123xyz...` |
| **Okta Issuer URL** | Security → API → Authorization Servers → `default` → Issuer URI | `https://your-org.okta.com/oauth2/default` |

> **Security note:** Share Client Secret via 1Password or a secure channel — not email or Slack.

---

### 6. Verify the Well-Known Endpoint

Confirm the OIDC discovery document is accessible (no auth required):

```
https://your-org.okta.com/oauth2/default/.well-known/openid-configuration
```

Should return JSON with `authorization_endpoint`, `token_endpoint`, `jwks_uri`, etc.

---

## What the Data Platform Team Will Do With These Credentials

The three values (Client ID, Client Secret, Issuer URL) are stored in **AWS Secrets Manager** and injected into the Genie backend pod as environment variables:

```
OKTA_CLIENT_ID=<client-id>
OKTA_CLIENT_SECRET=<client-secret>
OKTA_ISSUER=https://your-org.okta.com/oauth2/default
```

These are never hardcoded in source code and never logged.

---

## User Experience After Setup

Once configured, connecting Genie to claude.ai takes ~10 seconds per user:

1. Employee opens **claude.ai → Settings → Connectors → Add connector**
2. Enters the MCP URL: `https://dev-apis.example.com/genie/mcp`
3. A popup appears with the Okta login page
4. If the employee is already logged into Okta (typical on a corporate machine), the popup auto-closes
5. Genie shows as "Connected" — done

No IT involvement required per user. The Okta app assignment (`Everyone` group) handles all employees automatically.

---

## Scope of Access

The Okta application requests only standard OIDC scopes:

| Scope | What it provides |
|-------|-----------------|
| `openid` | User identity (sub claim) |
| `profile` | Display name |
| `email` | Email address (used as user identifier in Genie) |
| `offline_access` | Refresh token (keeps session alive without re-login) |

**No data access is granted through Okta.** Okta only authenticates the user's identity. Genie's own authorization layer controls what data each user can access based on their role.

---

## Timeline

| Step | Owner | Est. time |
|------|-------|-----------|
| Create Okta OIDC app | IT | 30 min |
| Share credentials securely | IT → Sri Maru | Same day |
| Store credentials in Secrets Manager | Data Platform | 1 hour |
| Deploy to dev K8s + test | Data Platform | 1 hour |
| Validate end-to-end with claude.ai | Data Platform + 1 tester | 30 min |

---

## Questions?

Contact: Sri Maru (data platform team) or open a ticket with the Okta app details above.
