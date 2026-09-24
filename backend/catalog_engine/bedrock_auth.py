"""
Shared Bedrock authentication for KB build modules.

Tries multiple sources to get AWS credentials for Bedrock:
1. In-memory credential store (user's active SSO session)
2. SSO refresh token from postgres (exchange for fresh credentials)
3. Default IAM role (service account — may not have Bedrock access)
"""

import json
import logging

logger = logging.getLogger("genie.bedrock_auth")


def get_bedrock_client(config, db_pool=None):
    """
    Create an AsyncAnthropicBedrock client with the best available credentials.

    Returns (client, source_description) tuple.
    """
    from anthropic import AsyncAnthropicBedrock
    from connectors.credential_store import credential_store

    env = getattr(config, "BEDROCK_SSO_ENV", "np")
    region = getattr(config, "BEDROCK_REGION", "us-west-2")

    # 1. Try in-memory credential store (user's active SSO session)
    for sid, session in credential_store._sessions.items():
        creds = session.get_credentials(env)
        if creds and creds.minutes_remaining > 2:
            logger.info("Bedrock auth: using in-memory SSO credentials (%s, %d min remaining)", env, creds.minutes_remaining)
            return AsyncAnthropicBedrock(
                aws_access_key=creds.access_key_id,
                aws_secret_key=creds.secret_access_key,
                aws_session_token=creds.session_token,
                aws_region=region,
            ), f"sso_{env}"

    # 2. Try SSO refresh token from postgres
    if db_pool:
        try:
            import asyncio
            creds = asyncio.get_event_loop().run_until_complete(
                _refresh_sso_from_postgres(db_pool, env, region)
            )
            if creds:
                logger.info("Bedrock auth: refreshed SSO credentials from postgres (%s)", env)
                return AsyncAnthropicBedrock(
                    aws_access_key=creds["access_key_id"],
                    aws_secret_key=creds["secret_access_key"],
                    aws_session_token=creds["session_token"],
                    aws_region=region,
                ), f"sso_refresh_{env}"
        except Exception as e:
            logger.warning("Bedrock auth: SSO refresh failed: %s", e)

    # 3. Fallback to default IAM role (may not have Bedrock access)
    logger.warning("Bedrock auth: no SSO credentials found, falling back to IAM role")
    return AsyncAnthropicBedrock(aws_region=region), "iam_role"


async def get_bedrock_client_async(config, db_pool=None):
    """Async version of get_bedrock_client."""
    from anthropic import AsyncAnthropicBedrock
    from connectors.credential_store import credential_store

    env = getattr(config, "BEDROCK_SSO_ENV", "np")
    region = getattr(config, "BEDROCK_REGION", "us-west-2")

    # 1. Try in-memory credential store
    for sid, session in credential_store._sessions.items():
        creds = session.get_credentials(env)
        if creds and creds.minutes_remaining > 2:
            logger.info("Bedrock auth: using in-memory SSO credentials (%s, %d min remaining)", env, creds.minutes_remaining)
            return AsyncAnthropicBedrock(
                aws_access_key=creds.access_key_id,
                aws_secret_key=creds.secret_access_key,
                aws_session_token=creds.session_token,
                aws_region=region,
            ), f"sso_{env}"

    # 2. Try SSO refresh from postgres
    if db_pool:
        try:
            creds = await _refresh_sso_from_postgres(db_pool, env, region)
            if creds:
                logger.info("Bedrock auth: refreshed SSO credentials from postgres (%s)", env)
                return AsyncAnthropicBedrock(
                    aws_access_key=creds["access_key_id"],
                    aws_secret_key=creds["secret_access_key"],
                    aws_session_token=creds["session_token"],
                    aws_region=region,
                ), f"sso_refresh_{env}"
        except Exception as e:
            logger.warning("Bedrock auth: SSO refresh failed: %s", e)

    # 3. Fallback
    logger.warning("Bedrock auth: no SSO credentials found, falling back to IAM role")
    return AsyncAnthropicBedrock(aws_region=region), "iam_role"


async def _refresh_sso_from_postgres(db_pool, environment: str, region: str) -> dict | None:
    """Exchange SSO refresh token from postgres for fresh AWS credentials."""
    import boto3
    from botocore.config import Config as BotoConfig

    row = await db_pool.fetchrow("""
        SELECT session_id, data FROM credential_cache
        WHERE cred_type = 'sso_refresh' AND environment = $1 AND expires_at > NOW()
        ORDER BY created_at DESC LIMIT 1
    """, environment)

    if not row:
        return None

    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data)

    if not data.get("refresh_token"):
        return None

    # Exchange refresh token for access token
    oidc = boto3.client("sso-oidc", config=BotoConfig(region_name=region))
    token_resp = oidc.create_token(
        clientId=data["client_id"],
        clientSecret=data["client_secret"],
        grantType="refresh_token",
        refreshToken=data["refresh_token"],
    )

    access_token = token_resp["accessToken"]

    # Update refresh token if rotated
    new_refresh = token_resp.get("refreshToken")
    if new_refresh and new_refresh != data["refresh_token"]:
        data["refresh_token"] = new_refresh
        await db_pool.execute("""
            UPDATE credential_cache SET data = $1::jsonb
            WHERE session_id = $2 AND environment = $3 AND cred_type = 'sso_refresh'
        """, json.dumps(data), row["session_id"], environment)

    # Get role credentials
    sso = boto3.client("sso", config=BotoConfig(region_name=region))
    role_resp = sso.get_role_credentials(
        roleName=data["role_name"],
        accountId=data["account_id"],
        accessToken=access_token,
    )
    role_creds = role_resp["roleCredentials"]

    # Also inject into credential store for other modules
    from connectors.credential_store import credential_store, AWSCredentials
    session = credential_store.get_session(row["session_id"])
    session.set_credentials(environment, AWSCredentials(
        access_key_id=role_creds["accessKeyId"],
        secret_access_key=role_creds["secretAccessKey"],
        session_token=role_creds["sessionToken"],
        expires_at=role_creds["expiration"] / 1000,
    ))

    return {
        "access_key_id": role_creds["accessKeyId"],
        "secret_access_key": role_creds["secretAccessKey"],
        "session_token": role_creds["sessionToken"],
    }
