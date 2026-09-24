"""
AWS SSO authentication flow for Genie.

Implements the same device authorization flow as `aws sso login`:
1. Register OIDC client (one-time, cached)
2. Start device authorization → user gets a URL to approve in browser
3. Poll for token → exchange for role credentials
4. Store per-user, per-environment credentials

Each user authenticates independently. Their credentials are scoped to
their own IAM role and expire after the SSO session duration.
"""
import asyncio
import logging
import time

import boto3
from botocore.config import Config as BotoConfig
from fastapi import APIRouter, Request, HTTPException

from config import config
from connectors.credential_store import (
    AWSCredentials,
    credential_store,
)

logger = logging.getLogger("genie.auth")
router = APIRouter()

SSO_START_URL = "https://d-92670814d5.awsapps.com/start#/"
SSO_REGION = "us-west-2"

# Environment -> (account_id, role_name)
ENV_ROLES = {
    "np": {
        "account_id": "111111111111",
        "role_name": "DataNonProdReadRole",
    },
    "prd": {
        "account_id": "222222222222",
        "role_name": "DataProdReadOnlyRole",
    },
}

boto_config = BotoConfig(region_name=SSO_REGION)


def _get_sso_oidc_client():
    return boto3.client("sso-oidc", config=boto_config)


def _get_sso_client():
    return boto3.client("sso", config=boto_config)


def _ensure_client_registration():
    """Register an OIDC client if we don't have one or it's expired."""
    if credential_store.client_registered:
        return

    client = _get_sso_oidc_client()
    resp = client.register_client(
        clientName="JennieClient",
        clientType="public",
        scopes=["sso:account:access"],
    )
    credential_store._client_id = resp["clientId"]
    credential_store._client_secret = resp["clientSecret"]
    credential_store._client_expires_at = resp["clientSecretExpiresAt"]
    logger.info("Registered OIDC client (expires at %s)", resp["clientSecretExpiresAt"])


@router.post("/sso/start")
async def start_sso_auth(request: Request):
    """
    Start the SSO device authorization flow.

    Returns a verification URL the user opens in their browser to approve access.
    The frontend shows this URL and polls /sso/poll until complete.
    """
    body = await request.json()
    session_id = body.get("session_id", "")
    environment = body.get("environment", "np")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if environment not in ENV_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid environment: {environment}")

    try:
        def _start():
            _ensure_client_registration()
            client = _get_sso_oidc_client()
            return client.start_device_authorization(
                clientId=credential_store._client_id,
                clientSecret=credential_store._client_secret,
                startUrl=SSO_START_URL,
            )

        resp = await asyncio.to_thread(_start)

        device_code = resp["deviceCode"]
        credential_store._pending_auth[device_code] = {
            "session_id": session_id,
            "environment": environment,
            "interval": resp.get("interval", 5),
            "expires_at": time.time() + resp.get("expiresIn", 600),
        }

        return {
            "device_code": device_code,
            "verification_uri": resp["verificationUri"],
            "verification_uri_complete": resp["verificationUriComplete"],
            "user_code": resp["userCode"],
            "expires_in": resp.get("expiresIn", 600),
            "interval": resp.get("interval", 5),
        }

    except Exception as e:
        logger.error("SSO start failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sso/poll")
async def poll_sso_auth(request: Request):
    """
    Poll for SSO authorization completion.

    After the user approves in their browser, this exchanges the device code
    for an access token, then uses it to get role credentials.
    """
    body = await request.json()
    device_code = body.get("device_code", "")

    if not device_code or device_code not in credential_store._pending_auth:
        raise HTTPException(status_code=400, detail="Invalid or expired device_code")

    pending = credential_store._pending_auth[device_code]
    if time.time() > pending["expires_at"]:
        del credential_store._pending_auth[device_code]
        return {"status": "expired", "message": "Authorization request expired. Please start again."}

    session_id = pending["session_id"]
    environment = pending["environment"]
    env_config = ENV_ROLES[environment]

    oidc_client = _get_sso_oidc_client()

    try:
        token_resp = await asyncio.to_thread(
            oidc_client.create_token,
            clientId=credential_store._client_id,
            clientSecret=credential_store._client_secret,
            grantType="urn:ietf:params:oauth:grant-type:device_code",
            deviceCode=device_code,
        )

        access_token = token_resp["accessToken"]
        refresh_token = token_resp.get("refreshToken")

        # Store refresh token for auto-renewal
        if refresh_token:
            from connectors.credential_store import store_sso_refresh
            store_sso_refresh(environment, {
                "client_id": credential_store._client_id,
                "client_secret": credential_store._client_secret,
                "refresh_token": refresh_token,
                "account_id": env_config["account_id"],
                "role_name": env_config["role_name"],
            })
            logger.info("Stored SSO refresh token for %s", environment)

        # Get role credentials using the SSO access token
        sso_client = _get_sso_client()
        role_resp = await asyncio.to_thread(
            sso_client.get_role_credentials,
            roleName=env_config["role_name"],
            accountId=env_config["account_id"],
            accessToken=access_token,
        )

        role_creds = role_resp["roleCredentials"]

        creds = AWSCredentials(
            access_key_id=role_creds["accessKeyId"],
            secret_access_key=role_creds["secretAccessKey"],
            session_token=role_creds["sessionToken"],
            expires_at=role_creds["expiration"] / 1000,  # millis -> seconds
            account_id=env_config["account_id"],
            role_name=env_config["role_name"],
            profile=environment,
        )

        credential_store.set_credentials(session_id, environment, creds)

        # Clean up pending auth
        del credential_store._pending_auth[device_code]

        logger.info("SSO auth success for %s/%s", session_id, environment)
        return {
            "status": "authenticated",
            "environment": environment,
            "account_id": env_config["account_id"],
            "role_name": env_config["role_name"],
            "expires_in_minutes": creds.minutes_remaining,
        }

    except oidc_client.exceptions.AuthorizationPendingException:
        return {"status": "pending", "message": "Waiting for user to approve in browser..."}

    except oidc_client.exceptions.SlowDownException:
        return {"status": "slow_down", "message": "Polling too fast. Increase interval."}

    except oidc_client.exceptions.ExpiredTokenException:
        del credential_store._pending_auth[device_code]
        return {"status": "expired", "message": "Authorization request expired. Please start again."}

    except oidc_client.exceptions.InvalidGrantException as e:
        # Device code already redeemed — check if we already have valid creds
        existing_creds = credential_store.get_credentials(session_id, environment)
        if existing_creds and existing_creds.minutes_remaining > 0:
            # First poll succeeded, subsequent polls hit this — return success
            del credential_store._pending_auth[device_code]
            return {
                "status": "authenticated",
                "environment": environment,
                "account_id": env_config["account_id"],
                "role_name": env_config["role_name"],
                "expires_in_minutes": existing_creds.minutes_remaining,
            }
        # Token was redeemed but creds weren't stored — need to restart
        del credential_store._pending_auth[device_code]
        return {"status": "expired", "message": "Device code already used. Please start SSO again."}

    except Exception as e:
        error_str = str(e)
        logger.error("SSO poll failed: %s", error_str)

        # If role access failed, the token was redeemed but role is wrong — don't keep polling
        if "GetRoleCredentials" in error_str or "No access" in error_str or "ForbiddenException" in error_str:
            del credential_store._pending_auth[device_code]
            return {
                "status": "error",
                "message": f"SSO login succeeded but role '{env_config['role_name']}' on account {env_config['account_id']} is not accessible. Check your SSO role assignment.",
            }

        return {"status": "error", "message": error_str}


@router.get("/sso/status")
async def sso_status(session_id: str):
    """Check authentication status for a user session."""
    session = credential_store.get_session(session_id)
    environments = {}
    for env in ("np", "prd"):
        creds = session.get_credentials(env)
        if creds:
            environments[env] = {
                "authenticated": True,
                "role_name": creds.role_name,
                "account_id": creds.account_id,
                "expires_in_minutes": creds.minutes_remaining,
            }
        else:
            environments[env] = {"authenticated": False}

    return {
        "session_id": session_id,
        "environments": environments,
    }


@router.post("/sso/list-roles")
async def list_sso_roles(request: Request):
    """
    After SSO device auth, list available roles for each account.
    Helps diagnose which role_name to use.
    """
    body = await request.json()
    device_code = body.get("device_code", "")

    # We need a fresh SSO token — start a new device auth and use it
    # Instead, just try listing accounts/roles with an existing token
    def _list_roles():
        _ensure_client_registration()

        oidc_client = _get_sso_oidc_client()
        token_resp = oidc_client.create_token(
            clientId=credential_store._client_id,
            clientSecret=credential_store._client_secret,
            grantType="urn:ietf:params:oauth:grant-type:device_code",
            deviceCode=device_code,
        )
        access_token = token_resp["accessToken"]

        sso_client = _get_sso_client()

        # List accounts
        accounts_resp = sso_client.list_accounts(accessToken=access_token)
        accounts = accounts_resp.get("accountList", [])

        result = []
        for acct in accounts:
            account_id = acct["accountId"]
            roles_resp = sso_client.list_account_roles(
                accessToken=access_token,
                accountId=account_id,
            )
            roles = [r["roleName"] for r in roles_resp.get("roleList", [])]
            result.append({
                "account_id": account_id,
                "account_name": acct.get("accountName", ""),
                "roles": roles,
            })

        return {"accounts": result}

    try:
        return await asyncio.to_thread(_list_roles)
    except Exception as e:
        return {"error": str(e)}


_okta_mfa_state: dict = {}  # session_id -> MFA state


@router.post("/okta/start")
async def okta_start(request: Request):
    """
    Start Okta authentication. If MFA is required, returns MFA state
    for the frontend to show "Approve push notification" UI.
    """
    body = await request.json()
    session_id = body.get("session_id", "")
    username = body.get("username", "")
    password = body.get("password", "")

    if not session_id or not username or not password:
        raise HTTPException(400, "session_id, username, and password are required")

    from connectors.okta_mfa import okta_authenticate_with_mfa, okta_trigger_push

    result = await asyncio.to_thread(okta_authenticate_with_mfa, config.OKTA_IDP_HOST, username, password)

    if result["status"] == "SUCCESS":
        # No MFA needed — store creds and do SAML exchange
        from connectors.redshift import set_okta_credentials
        set_okta_credentials(session_id, username, password)

        saml_result = await asyncio.to_thread(_okta_saml_to_aws_creds, session_id, result["session_token"], "prd")
        if saml_result.get("error"):
            return {"status": "error", "error": f"Okta auth OK but SAML failed: {saml_result['error']}"}

        return {"status": "authenticated"}

    if result["status"] == "MFA_PUSH_SENT":
        # Trigger the push
        push_result = await asyncio.to_thread(okta_trigger_push, result["verify_url"], result["state_token"])

        if push_result["status"] == "SUCCESS":
            from connectors.redshift import set_okta_credentials
            set_okta_credentials(session_id, username, password)
            saml_result = await asyncio.to_thread(_okta_saml_to_aws_creds, session_id, push_result["session_token"], "prd")
            if saml_result.get("error"):
                return {"status": "error", "error": f"Okta auth OK but SAML failed: {saml_result['error']}"}
            return {"status": "authenticated"}

        if push_result["status"] in ("MFA_CHALLENGE", "WAITING"):
            _okta_mfa_state[session_id] = {
                "username": username,
                "password": password,
                "state_token": push_result.get("state_token", result["state_token"]),
                "poll_url": push_result.get("poll_url", result["verify_url"]),
            }
            return {
                "status": "mfa_push_sent",
                "message": "Approve the Okta Verify push notification on your device.",
            }

        return {"status": "error", "error": push_result.get("error", "Push failed")}

    return {"status": "error", "error": result.get("error", "Authentication failed")}


def _okta_saml_to_aws_creds(session_id: str, session_token: str, environment: str = "prd") -> dict:
    """
    Exchange Okta session token → SAML assertion → AssumeRoleWithSAML → AWS creds.
    Caches the result so Redshift connections don't re-auth.
    """
    import base64
    import re
    import xml.etree.ElementTree as ET

    app_id = config.OKTA_APP_ID_PRD if environment == "prd" else config.OKTA_APP_ID_NP

    # Get SAML assertion — try multiple Okta app URL patterns
    import requests as http_requests
    saml_b64 = None
    for url_template in [
        f"https://{config.OKTA_IDP_HOST}/app/amazon_aws_redshift/{app_id}/sso/saml",
        f"https://{config.OKTA_IDP_HOST}/home/amazon_aws_redshift/{app_id}/272",
        f"https://{config.OKTA_IDP_HOST}/app/amazon_aws/{app_id}/sso/saml",
        f"https://{config.OKTA_IDP_HOST}/home/amazon_aws/{app_id}/272",
        f"https://{config.OKTA_IDP_HOST}/app/amazon_aws_sso/{app_id}/sso/saml",
        f"https://{config.OKTA_IDP_HOST}/home/amazon_aws_sso/{app_id}/272",
        f"https://{config.OKTA_IDP_HOST}/app/{app_id}/sso/saml",
    ]:
        url = url_template
        resp = http_requests.get(url, params={"sessionToken": session_token}, timeout=15, allow_redirects=True)
        match = re.search(r'name="SAMLResponse"\s+value="([^"]+)"', resp.text)
        if match:
            saml_b64 = match.group(1)
            logger.info("SAML assertion obtained via: %s", url)
            break

    # Also try the Okta sessionToken → app embed flow (how JDBC does it)
    if not saml_b64:
        try:
            # Create Okta session from token
            session_resp = http_requests.post(
                f"https://{config.OKTA_IDP_HOST}/api/v1/sessions",
                json={"sessionToken": session_token},
                headers={"Content-Type": "application/json"}, timeout=10)
            if session_resp.status_code == 200:
                okta_session_id = session_resp.json().get("id")
                # Get user's app links to find the exact embed URL
                apps_resp = http_requests.get(
                    f"https://{config.OKTA_IDP_HOST}/api/v1/users/me/appLinks",
                    headers={"Cookie": f"sid={okta_session_id}", "Accept": "application/json"}, timeout=10)
                if apps_resp.status_code == 200:
                    for app in apps_resp.json():
                        link = app.get("linkUrl", "")
                        if app_id in link or "redshift" in app.get("appName", "").lower() or "redshift" in app.get("label", "").lower():
                            # Found it — fetch SAML from the exact link
                            saml_resp = http_requests.get(link, headers={"Cookie": f"sid={okta_session_id}"}, timeout=15, allow_redirects=True)
                            import re
                            match = re.search(r'name="SAMLResponse"\s+value="([^"]+)"', saml_resp.text)
                            if match:
                                saml_b64 = match.group(1)
                                logger.info("SAML assertion obtained via app link: %s", app.get("label"))
                                break
        except Exception as e:
            logger.warning("App link discovery failed: %s", e)

    if not saml_b64:
        tried = ", ".join([
            f"amazon_aws_redshift/{app_id}", f"home/amazon_aws_redshift/{app_id}/272",
            f"amazon_aws/{app_id}", f"home/amazon_aws/{app_id}/272",
            f"amazon_aws_sso/{app_id}", f"home/amazon_aws_sso/{app_id}/272",
            f"{app_id}",
        ])
        # Also try to get user's app links to find the right URL
        try:
            session_resp = http_requests.post(
                f"https://{config.OKTA_IDP_HOST}/api/v1/sessions",
                json={"sessionToken": session_token},
                headers={"Content-Type": "application/json"}, timeout=10)
            if session_resp.status_code == 200:
                sid = session_resp.json().get("id")
                apps_resp = http_requests.get(
                    f"https://{config.OKTA_IDP_HOST}/api/v1/users/me/appLinks",
                    headers={"Cookie": f"sid={sid}", "Accept": "application/json"}, timeout=10)
                if apps_resp.status_code == 200:
                    redshift_apps = [
                        a for a in apps_resp.json()
                        if "redshift" in a.get("label", "").lower()
                        or "redshift" in a.get("appName", "").lower()
                        or "aws" in a.get("label", "").lower()
                    ]
                    if redshift_apps:
                        app_info = "; ".join(
                            f"{a.get('label')}={a.get('linkUrl','?')}" for a in redshift_apps
                        )
                        return {"error": f"SAML failed with patterns [{tried}]. Found Okta apps: {app_info}"}
        except Exception:
            pass
        return {"error": f"Could not get SAML assertion. Tried patterns: [{tried}]. Check OKTA_APP_ID for {environment}."}

    # Parse roles from SAML
    saml_xml = base64.b64decode(saml_b64).decode("utf-8")
    root = ET.fromstring(saml_xml)
    roles = []
    for attr in root.iter():
        if attr.get("Name") == "https://aws.amazon.com/SAML/Attributes/Role":
            for val in attr:
                if val.text and "," in val.text:
                    parts = val.text.split(",")
                    role_arn = [p.strip() for p in parts if ":role/" in p]
                    principal_arn = [p.strip() for p in parts if ":saml-provider/" in p]
                    if role_arn and principal_arn:
                        roles.append((role_arn[0], principal_arn[0]))

    if not roles:
        return {"error": "No AWS roles in SAML assertion"}

    role_arn, principal_arn = roles[0]

    # AssumeRoleWithSAML
    import boto3 as _boto3
    sts = _boto3.client("sts", region_name="us-west-2")
    assume_resp = sts.assume_role_with_saml(
        RoleArn=role_arn,
        PrincipalArn=principal_arn,
        SAMLAssertion=saml_b64,
        DurationSeconds=3600,
    )
    temp = assume_resp["Credentials"]

    aws_creds = {
        "access_key": temp["AccessKeyId"],
        "secret_key": temp["SecretAccessKey"],
        "token": temp["SessionToken"],
        "expires": temp["Expiration"].timestamp(),
        "role_arn": role_arn,
    }

    from connectors.redshift import set_okta_aws_creds
    set_okta_aws_creds(session_id, aws_creds)
    # Also cache for the other environment (same SAML, different app)
    logger.info("Cached AWS creds for %s via SAML role %s", session_id, role_arn)

    return {"status": "ok", "role_arn": role_arn}


@router.post("/okta/poll")
async def okta_poll(request: Request):
    """Poll for Okta MFA push approval."""
    body = await request.json()
    session_id = body.get("session_id", "")

    state = _okta_mfa_state.get(session_id)
    if not state:
        return {"status": "error", "error": "No pending MFA. Start again."}

    from connectors.okta_mfa import okta_poll_push

    result = await asyncio.to_thread(okta_poll_push, state["poll_url"], state["state_token"])

    if result["status"] == "SUCCESS":
        # MFA approved — store credentials and do SAML flow
        from connectors.redshift import set_okta_credentials
        set_okta_credentials(session_id, state["username"], state["password"])

        # Exchange session token for AWS creds via SAML
        saml_result = await asyncio.to_thread(_okta_saml_to_aws_creds, session_id, result["session_token"], "prd")
        if saml_result.get("error"):
            logger.warning("SAML exchange failed: %s (Okta creds still stored for retry)", saml_result["error"])

        del _okta_mfa_state[session_id]
        return {"status": "authenticated"}

    if result["status"] == "WAITING":
        return {"status": "waiting", "message": "Waiting for push approval..."}

    if result["status"] in ("REJECTED", "TIMEOUT"):
        del _okta_mfa_state[session_id]
        return {"status": "error", "error": result.get("error", "Push rejected or timed out")}

    del _okta_mfa_state[session_id]
    return {"status": "error", "error": result.get("error", "Unknown error")}


@router.post("/redshift/from-airflow")
async def redshift_from_airflow(request: Request):
    """
    Fetch Redshift connection credentials from MWAA Airflow connection.
    Uses the existing SSO session to query Airflow's connection API.
    """
    body = await request.json()
    session_id = body.get("session_id", "")
    environment = body.get("environment", "np")
    conn_id = body.get("conn_id", "redshift_default")

    if not session_id:
        raise HTTPException(400, "session_id required")

    from catalog_engine.mwaa_fetcher import _get_boto3_session, _get_mwaa_env_name, _get_session_info, _call_api

    try:
        def _fetch_airflow_conn():
            env_name = _get_mwaa_env_name(environment)
            boto_session = _get_boto3_session(environment, session_id)
            host, session_cookie = _get_session_info(boto_session, env_name)

            if not host or not session_cookie:
                return {"_error": f"Could not authenticate to MWAA {env_name}"}

            # Fetch connection details via Airflow CLI (REST API masks passwords)
            import base64 as _b64
            import requests as _requests

            mwaa_client = boto_session.client("mwaa", region_name="us-west-2")
            cli_token = mwaa_client.create_cli_token(Name=env_name)
            cli_host = cli_token["WebServerHostname"]
            cli_tok = cli_token["CliToken"]

            cli_resp = _requests.post(
                f"https://{cli_host}/aws_mwaa/cli",
                headers={"Authorization": f"Bearer {cli_tok}", "Content-Type": "text/plain"},
                data=f"connections get {conn_id} -o json",
                timeout=30,
            )

            if cli_resp.status_code != 200:
                return {"_error": f"MWAA CLI failed: HTTP {cli_resp.status_code}: {cli_resp.text[:300]}"}

            # MWAA CLI returns base64-encoded stdout in the response
            import json as _json
            try:
                cli_output = _b64.b64decode(cli_resp.json().get("stdout", "")).decode("utf-8")
                return _json.loads(cli_output)
            except Exception:
                # Try raw response
                return cli_resp.json()

        resp = await asyncio.to_thread(_fetch_airflow_conn)
        if isinstance(resp, dict) and resp.get("_error"):
            return {"status": "error", "error": resp["_error"]}

        if not resp or "host" not in resp:
            return {"status": "error", "error": f"Could not parse connection '{conn_id}' from MWAA CLI"}

        conn_host = resp.get("host", "")
        conn_port = resp.get("port")
        conn_login = resp.get("login", "")
        conn_password = resp.get("password", "")
        conn_schema = resp.get("schema", "")  # database name in Airflow
        conn_extra = resp.get("extra", "")
        conn_type = resp.get("conn_type", "")

        logger.info(
            "Airflow connection '%s': type=%s host=%s port=%s login=%s schema=%s has_password=%s extra=%s",
            conn_id, conn_type, conn_host, conn_port, conn_login, conn_schema,
            bool(conn_password), conn_extra[:200] if conn_extra else "",
        )

        if not conn_host:
            return {"status": "error", "error": f"Connection '{conn_id}' has no host. Full response: type={conn_type}, login={conn_login}, schema={conn_schema}"}

        # Store direct credentials
        from connectors.redshift import _direct_creds
        _direct_creds[environment] = {
            "host": conn_host or (config.REDSHIFT_PRD_HOST if environment == "prd" else config.REDSHIFT_NP_HOST),
            "port": int(conn_port) if conn_port else (config.REDSHIFT_PRD_PORT if environment == "prd" else config.REDSHIFT_NP_PORT),
            "database": conn_schema or (config.REDSHIFT_PRD_DATABASE if environment == "prd" else config.REDSHIFT_NP_DATABASE),
            "user": conn_login,
            "password": conn_password,
        }

        if not conn_password:
            return {
                "status": "error",
                "error": f"Connection '{conn_id}' has no password (MWAA may have masked it). User={conn_login}, host={conn_host}",
            }

        # Test the connection
        try:
            from connectors.redshift import test_connection
            test = await test_connection(environment, session_id)
            return {
                "status": "connected",
                "environment": environment,
                "conn_id": conn_id,
                "host": conn_host,
                "user": conn_login,
                "database": conn_schema,
                "test": test,
            }
        except Exception as e:
            return {
                "status": "credentials_stored",
                "environment": environment,
                "conn_id": conn_id,
                "host": conn_host,
                "user": conn_login,
                "database": conn_schema,
                "test_error": str(e),
            }

    except Exception as e:
        logger.error("Failed to fetch Airflow connection: %s", e)
        return {"status": "error", "error": str(e)}


@router.post("/redshift/credentials")
async def store_redshift_credentials(request: Request):
    """
    Store Redshift credentials securely in postgres.
    Tests the connection immediately. Never logs the password.
    """
    body = await request.json()
    session_id = body.get("session_id", "")
    environment = body.get("environment", "np")
    username = body.get("username", "")
    password = body.get("password", "")

    if not session_id or not username or not password:
        raise HTTPException(400, "session_id, username, and password required")

    # Host/port/database from UI (override config defaults)
    if environment == "prd":
        host = body.get("host", "") or config.REDSHIFT_PRD_HOST
        port = body.get("port", 0) or config.REDSHIFT_PRD_PORT
        database = body.get("database", "") or config.REDSHIFT_PRD_DATABASE
    else:
        host = body.get("host", "") or config.REDSHIFT_NP_HOST
        port = body.get("port", 0) or config.REDSHIFT_NP_PORT
        database = body.get("database", "") or config.REDSHIFT_NP_DATABASE

    pool = request.app.state.db_pool

    # Store in postgres — includes host/port/database so they persist
    # NEVER log the password
    import json as _json
    cred_data = _json.dumps({
        "username": username, "password": password,
        "host": host, "port": port, "database": database,
    })
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    expires = _dt.now(_tz.utc) + _td(days=365)

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ($1, $2, 'redshift_direct', $3::jsonb, $4)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $3::jsonb, expires_at = $4, created_at = NOW()
    """, session_id, environment, cred_data, expires)

    # Also store in memory for immediate use
    from connectors.redshift import _direct_creds
    _direct_creds[environment] = {
        "host": host, "port": int(port), "database": database,
        "user": username, "password": password,
    }

    logger.info("Stored Redshift credentials for %s/%s (user=%s)", session_id, environment, username)

    # Test connection
    try:
        from connectors.redshift import test_connection
        test = await test_connection(environment)
        if test.get("status") == "connected":
            return {"status": "connected", "user": test.get("user")}
        return {"status": "error", "error": test.get("error", "Connection test failed")}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/kb-storage")
async def store_kb_storage(request: Request):
    """Configure S3 bucket for KB persistence."""
    body = await request.json()
    bucket = body.get("bucket", "").strip()
    prefix = body.get("prefix", "knowledge/").strip()
    if not bucket:
        raise HTTPException(400, "S3 bucket name required")

    pool = request.app.state.db_pool
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    cred_data = _json.dumps({"bucket": bucket, "prefix": prefix})
    expires = _dt.now(_tz.utc) + _td(days=3650)

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ('global', 'kb', 'kb_s3_storage', $1::jsonb, $2)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $1::jsonb, expires_at = $2, created_at = NOW()
    """, cred_data, expires)

    from connectors.kb_storage import configure as configure_kb_s3
    configure_kb_s3(bucket, prefix)

    return {"status": "configured", "bucket": bucket, "prefix": prefix}


@router.get("/kb-storage/status")
async def kb_storage_status(request: Request):
    """Check KB S3 storage config."""
    from connectors.kb_storage import is_configured, _s3_bucket, _s3_prefix
    if is_configured():
        return {"configured": True, "bucket": _s3_bucket, "prefix": _s3_prefix}
    # Fallback: read from postgres (handles multi-pod and post-restart before lifespan loads)
    try:
        row = await request.app.state.db_pool.fetchrow("""
            SELECT data->>'bucket' as bucket, data->>'prefix' as prefix
            FROM credential_cache WHERE cred_type = 'kb_s3_storage' AND expires_at > NOW() LIMIT 1
        """)
        if row and row["bucket"]:
            from connectors.kb_storage import configure as configure_kb_s3
            configure_kb_s3(row["bucket"], row["prefix"] or "knowledge/")
            return {"configured": True, "bucket": row["bucket"], "prefix": row["prefix"] or "knowledge/"}
    except Exception:
        pass
    return {"configured": False, "bucket": "", "prefix": "knowledge/"}


@router.post("/github/token")
async def store_github_token(request: Request):
    """Store GitHub personal access token. Used for repo cloning and MCP."""
    body = await request.json()
    token = body.get("token", "").strip()
    if not token:
        raise HTTPException(400, "GitHub token required")

    pool = request.app.state.db_pool
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    cred_data = _json.dumps({"token": token})
    expires = _dt.now(_tz.utc) + _td(days=365)

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ('global', 'github', 'github_token', $1::jsonb, $2)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $1::jsonb, expires_at = $2, created_at = NOW()
    """, cred_data, expires)

    # Apply immediately
    config.GITHUB_TOKEN = token

    logger.info("GitHub token stored via UI")
    return {"status": "connected"}


@router.get("/github/status")
async def github_status(request: Request):
    """Check if GitHub token is configured."""
    return {"configured": bool(config.GITHUB_TOKEN)}


@router.post("/repo-url")
async def store_repo_url(request: Request):
    """Store the data platform repo URL (replaces REPO_URL env var)."""
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "url required")

    pool = request.app.state.db_pool
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    cred_data = _json.dumps({"url": url})
    expires = _dt.now(_tz.utc) + _td(days=3650)  # 10 years

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ('global', 'config', 'repo_url', $1::jsonb, $2)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $1::jsonb, expires_at = $2, created_at = NOW()
    """, cred_data, expires)

    config.REPO_URL = url
    logger.info("REPO_URL stored via UI: %s", url)
    return {"status": "saved", "url": url}


@router.get("/repo-url/status")
async def repo_url_status(request: Request):
    """Check current repo URL."""
    return {"configured": bool(config.REPO_URL), "url": config.REPO_URL or ""}


@router.post("/domo/credentials")
async def store_domo_credentials(request: Request):
    """Store DOMO client credentials (same as Airflow DAGs use). Admin only."""
    body = await request.json()
    client_id = body.get("client_id", "").strip()
    client_secret = body.get("client_secret", "").strip()

    if not client_id or not client_secret:
        raise HTTPException(400, "client_id and client_secret required")

    pool = request.app.state.db_pool
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    cred_data = _json.dumps({"client_id": client_id, "client_secret": client_secret})
    expires = _dt.now(_tz.utc) + _td(days=365)

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ('global', 'domo', 'domo_oauth', $1::jsonb, $2)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $1::jsonb, expires_at = $2, created_at = NOW()
    """, cred_data, expires)

    # Configure client immediately
    from connectors.domo_client import configure
    configure(client_id, client_secret)

    # Test connection
    from connectors.domo_client import is_configured
    if is_configured():
        from connectors.domo_client import get_dataset_metadata
        # Quick test with a known dataset ID from the DOMO catalog
        logger.info("DOMO credentials stored and client initialized")
        return {"status": "connected"}
    return {"status": "error", "error": "pydomo client initialization failed"}


@router.post("/statsig/credentials")
async def store_statsig_credentials(request: Request):
    """Store Statsig Console API key."""
    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(400, "Console API key required")

    pool = request.app.state.db_pool
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    cred_data = _json.dumps({"api_key": api_key})
    expires = _dt.now(_tz.utc) + _td(days=365)

    await pool.execute("""
        INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
        VALUES ('global', 'statsig', 'statsig_api', $1::jsonb, $2)
        ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
            data = $1::jsonb, expires_at = $2, created_at = NOW()
    """, cred_data, expires)

    from catalog_engine.statsig_client import configure
    configure(api_key)

    # Quick test — sync HTTP call, keep it off the event loop
    from catalog_engine.statsig_client import list_experiments
    test = await asyncio.to_thread(list_experiments, limit=1)
    if isinstance(test, dict) and "error" in test:
        return {"status": "error", "error": test["error"]}

    return {"status": "connected"}


@router.get("/statsig/status")
async def statsig_status(request: Request):
    """Check if Statsig is configured."""
    from catalog_engine.statsig_client import is_configured
    return {"configured": is_configured()}


@router.get("/domo/status")
async def domo_status(request: Request):
    """Check if DOMO is configured."""
    from connectors.domo_client import is_configured
    return {"configured": is_configured()}


@router.get("/redshift/status")
async def redshift_cred_status(session_id: str, environment: str = "np", request: Request = None):
    """Check if Redshift credentials are stored (without exposing them)."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("""
        SELECT data->>'username' as username, data->>'host' as host,
               (data->>'port')::int as port, data->>'database' as database
        FROM credential_cache
        WHERE session_id = $1 AND environment = $2 AND cred_type = 'redshift_direct'
          AND expires_at > NOW()
    """, session_id, environment)
    if row:
        # Return connection details (never password)
        default_host = config.REDSHIFT_PRD_HOST if environment == "prd" else config.REDSHIFT_NP_HOST
        default_port = config.REDSHIFT_PRD_PORT if environment == "prd" else config.REDSHIFT_NP_PORT
        default_db = config.REDSHIFT_PRD_DATABASE if environment == "prd" else config.REDSHIFT_NP_DATABASE
        return {
            "stored": True,
            "user": row["username"],
            "host": row["host"] or default_host,
            "port": row["port"] or default_port,
            "database": row["database"] or default_db,
        }
    # Return defaults when no creds stored
    if environment == "prd":
        return {"stored": False, "host": config.REDSHIFT_PRD_HOST, "port": config.REDSHIFT_PRD_PORT, "database": config.REDSHIFT_PRD_DATABASE}
    return {"stored": False, "host": config.REDSHIFT_NP_HOST, "port": config.REDSHIFT_NP_PORT, "database": config.REDSHIFT_NP_DATABASE}


@router.get("/ai/provider")
async def get_ai_provider():
    """Get current AI provider config."""
    return {
        "provider": config.AI_PROVIDER,
        "model": config.BEDROCK_MODEL if config.AI_PROVIDER == "bedrock" else config.CLAUDE_MODEL,
    }


@router.post("/ai/provider")
async def set_ai_provider(request: Request):
    """Switch AI provider at runtime (no restart needed)."""
    body = await request.json()
    provider = body.get("provider", "")
    if provider not in ("anthropic", "bedrock"):
        raise HTTPException(400, "provider must be 'anthropic' or 'bedrock'")

    config.AI_PROVIDER = provider

    # Re-create the Claude client with new provider
    from engine.claude_client import _create_client, ClaudeClient
    # Update the singleton used by chat
    import engine.claude_client as cc_module
    new_client = _create_client()
    model = config.BEDROCK_MODEL if provider == "bedrock" else config.CLAUDE_MODEL

    logger.info("Switched AI provider to %s (model=%s)", provider, model)
    return {
        "provider": provider,
        "model": model,
    }


@router.get("/mwaa/environments")
async def list_mwaa_environments(session_id: str, environment: str = "np"):
    """List MWAA environments in the account (for debugging)."""
    from catalog_engine.mwaa_fetcher import _get_boto3_session

    def _list_envs():
        boto_session = _get_boto3_session(environment, session_id)
        mwaa = boto_session.client("mwaa", region_name="us-west-2")
        return mwaa.list_environments()

    try:
        result = await asyncio.to_thread(_list_envs)
        return {"environments": result.get("Environments", [])}
    except Exception as e:
        return {"environments": [], "error": str(e)}


@router.post("/okta/test-jdbc")
async def okta_test_jdbc(request: Request):
    """
    Test Okta connection using the exact same method as DataGrip JDBC driver.
    Uses redshift_connector's built-in OktaCredentialsProvider.
    """
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    environment = body.get("environment", "np")

    if not username or not password:
        raise HTTPException(400, "username and password required")

    import redshift_connector

    if environment == "prd":
        host = config.REDSHIFT_PRD_HOST
        port = config.REDSHIFT_PRD_PORT
        database = config.REDSHIFT_PRD_DATABASE
        cluster_id = config.REDSHIFT_PRD_CLUSTER_ID
        app_id = config.OKTA_APP_ID_PRD
    else:
        host = config.REDSHIFT_NP_HOST
        port = config.REDSHIFT_NP_PORT
        database = config.REDSHIFT_NP_DATABASE
        cluster_id = config.REDSHIFT_NP_CLUSTER_ID
        app_id = config.OKTA_APP_ID_NP

    def _try_connect():
        # Try multiple app_name values — the Okta app type might not be 'amazon_aws_redshift'
        last_error = None
        conn = None
        # Try combinations: app_name × group_federation
        configs = [
            ("amazon_aws", False, username),       # V1 with db_user (most likely how DataGrip works)
            ("amazon_aws", True, None),             # V2 without db_user
            ("amazon_aws_redshift", False, username),
            ("amazon_aws_redshift", True, None),
            ("amazon_aws_sso", False, username),
        ]
        for app_name, group_fed, db_user in configs:
            try:
                logger.info("Trying Okta: app_name=%s group_federation=%s db_user=%s", app_name, group_fed, db_user)
                connect_args = dict(
                    iam=True,
                    host=host,
                    port=port,
                    database=database,
                    cluster_identifier=cluster_id,
                    region="us-west-2",
                    credentials_provider="OktaCredentialsProvider",
                    idp_host=config.OKTA_IDP_HOST,
                    app_id=app_id,
                    app_name=app_name,
                    user=username,
                    password=password,
                    group_federation=group_fed,
                    ssl=True,
                    timeout=30,
                )
                if db_user:
                    connect_args["db_user"] = db_user
                conn = redshift_connector.connect(**connect_args)
                logger.info("Connected with app_name=%s group_federation=%s", app_name, group_fed)
                break
            except Exception as e:
                last_error = e
                logger.warning("app_name=%s gf=%s failed: %s", app_name, group_fed, str(e)[:100])
                continue

        if not conn:
            raise last_error or Exception("All app_name variants failed")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT CURRENT_USER, CURRENT_DATABASE()")
            return cursor.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        row = await asyncio.to_thread(_try_connect)

        # Store creds for future use
        from connectors.redshift import set_okta_credentials
        set_okta_credentials(body.get("session_id", ""), username, password)

        return {"status": "connected", "user": row[0], "database": row[1], "method": "okta_jdbc"}
    except Exception as e:
        logger.error("Okta JDBC test failed: %s", e)
        return {"status": "error", "error": str(e)}


@router.get("/okta/status")
async def okta_status(session_id: str):
    """Check if Okta credentials are stored for this session."""
    from connectors.redshift import get_okta_credentials
    creds = get_okta_credentials(session_id)
    return {
        "connected": creds is not None,
        "username": creds["username"] if creds else None,
    }


@router.post("/sso/logout")
async def sso_logout(request: Request):
    """Clear credentials for a session."""
    body = await request.json()
    session_id = body.get("session_id", "")
    environment = body.get("environment")  # None = logout all

    session = credential_store.get_session(session_id)
    if environment:
        session.credentials.pop(environment, None)
    else:
        session.credentials.clear()

    return {"status": "logged_out"}
