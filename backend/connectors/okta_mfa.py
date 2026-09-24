"""
Okta MFA-aware authentication for Redshift SAML.

Handles the Okta Verify Push flow:
1. POST /api/v1/authn with username/password
2. If status=MFA_REQUIRED, find the Okta Verify push factor
3. POST /api/v1/authn/factors/{factorId}/verify to trigger push
4. Poll until status=SUCCESS or timeout
5. Return sessionToken for SAML assertion
"""

import json
import logging
import time

import requests

logger = logging.getLogger("genie.okta_mfa")

OKTA_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def okta_authenticate_with_mfa(
    idp_host: str,
    username: str,
    password: str,
    poll_timeout: int = 60,
    poll_interval: int = 3,
) -> dict:
    """
    Authenticate to Okta with MFA support.

    Returns:
        {
            "status": "SUCCESS" | "MFA_PUSH_SENT" | "MFA_TIMEOUT" | "error",
            "session_token": str | None,
            "state_token": str | None,   # for polling
            "factor_id": str | None,
            "verify_url": str | None,
            "error": str | None,
        }
    """
    url = f"https://{idp_host}/api/v1/authn"
    payload = {"username": username, "password": password}

    try:
        resp = requests.post(url, json=payload, headers=OKTA_HEADERS, timeout=15)
    except Exception as e:
        return {"status": "error", "error": f"Okta request failed: {e}"}

    if resp.status_code == 401:
        return {"status": "error", "error": "Invalid username or password"}
    if resp.status_code != 200:
        return {"status": "error", "error": f"Okta returned HTTP {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    status = data.get("status")

    if status == "SUCCESS":
        return {
            "status": "SUCCESS",
            "session_token": data["sessionToken"],
        }

    if status == "MFA_REQUIRED":
        state_token = data.get("stateToken")
        factors = data.get("_embedded", {}).get("factors", [])

        # Find Okta Verify Push factor
        push_factor = None
        for f in factors:
            if f.get("factorType") == "push" and f.get("provider") == "OKTA":
                push_factor = f
                break

        if not push_factor:
            # No push factor — list available factors
            factor_types = [f"{f.get('provider')}:{f.get('factorType')}" for f in factors]
            return {
                "status": "error",
                "error": f"No Okta Verify Push factor found. Available: {factor_types}",
            }

        factor_id = push_factor["id"]
        verify_url = push_factor.get("_links", {}).get("verify", {}).get("href", "")

        if not verify_url:
            verify_url = f"https://{idp_host}/api/v1/authn/factors/{factor_id}/verify"

        return {
            "status": "MFA_PUSH_SENT",
            "state_token": state_token,
            "factor_id": factor_id,
            "verify_url": verify_url,
        }

    return {"status": "error", "error": f"Unexpected Okta status: {status}"}


def okta_trigger_push(verify_url: str, state_token: str) -> dict:
    """Trigger Okta Verify Push and return initial response."""
    payload = {"stateToken": state_token}
    try:
        resp = requests.post(verify_url, json=payload, headers=OKTA_HEADERS, timeout=15)
        data = resp.json()
        status = data.get("status")

        if status == "SUCCESS":
            return {"status": "SUCCESS", "session_token": data["sessionToken"]}

        if status == "MFA_CHALLENGE":
            return {
                "status": "MFA_CHALLENGE",
                "state_token": data.get("stateToken", state_token),
                "poll_url": data.get("_links", {}).get("next", {}).get("href", verify_url),
            }

        return {"status": "error", "error": f"Unexpected status after push: {status}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def okta_poll_push(poll_url: str, state_token: str) -> dict:
    """Poll for push approval. Returns status."""
    payload = {"stateToken": state_token}
    try:
        resp = requests.post(poll_url, json=payload, headers=OKTA_HEADERS, timeout=15)
        data = resp.json()
        status = data.get("status")

        if status == "SUCCESS":
            return {"status": "SUCCESS", "session_token": data["sessionToken"]}

        if status == "MFA_CHALLENGE":
            result = data.get("factorResult", "")
            if result == "REJECTED":
                return {"status": "REJECTED", "error": "Push was rejected"}
            if result == "TIMEOUT":
                return {"status": "TIMEOUT", "error": "Push timed out"}
            # WAITING — keep polling
            return {"status": "WAITING"}

        return {"status": "error", "error": f"Unexpected: {status}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def okta_get_saml_assertion(
    idp_host: str,
    app_id: str,
    session_token: str,
) -> str:
    """
    Exchange Okta session token for SAML assertion.
    Hits the Okta app embed link with the session token.
    """
    url = f"https://{idp_host}/app/amazon_aws_redshift/{app_id}/sso/saml"
    params = {"sessionToken": session_token}

    resp = requests.get(url, params=params, headers=OKTA_HEADERS, timeout=15, allow_redirects=True)

    if resp.status_code != 200:
        raise Exception(f"SAML assertion request failed: HTTP {resp.status_code}")

    # Extract SAML response from the HTML form
    import re
    match = re.search(r'name="SAMLResponse"\s+value="([^"]+)"', resp.text)
    if not match:
        raise Exception("Could not extract SAMLResponse from Okta response")

    return match.group(1)
