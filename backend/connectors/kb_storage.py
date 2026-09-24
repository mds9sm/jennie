"""
KB Storage — S3-backed persistent storage with local cache.

Pattern:
- KB build writes to local + uploads to S3
- Container startup downloads from S3 to local (if local is empty/stale)
- Agent queries always read from local (zero S3 calls during chat)

Config:
- KB_S3_BUCKET: S3 bucket name (e.g., "genie-kb-bucket")
- KB_S3_PREFIX: prefix in bucket (e.g., "knowledge/")
- Uses SSO credentials from credential_store
"""

import logging
import os
import json
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("genie.kb_storage")

_s3_bucket: str = os.environ.get("KB_S3_BUCKET", "")
_s3_prefix: str = os.environ.get("KB_S3_PREFIX", "knowledge/")


def configure(bucket: str, prefix: str = "knowledge/"):
    """Set S3 bucket from UI."""
    global _s3_bucket, _s3_prefix
    _s3_bucket = bucket
    _s3_prefix = prefix
    logger.info("KB S3 storage configured: s3://%s/%s", bucket, prefix)

# Files to sync between local and S3
KB_FILES = [
    "catalog.json",
    "transforms_index.json",
    "lineage.json",
    "metrics.json",
    "domo_catalog.json",
    "event_schemas.json",
    "statsig.json",
    "metadata_dags.json",
    "coverage.json",
    "knowledge_summary.json",
    "enrichment_report.json",
    "mwaa_environments.json",
    "glossary.yaml",
    "CLAUDE.md",
]

# Directories to sync
KB_DIRS = ["transforms", "views"]


def is_configured() -> bool:
    return bool(_s3_bucket)


def _get_s3_client():
    """Get S3 client using SSO credentials or default chain."""
    import boto3
    try:
        from connectors.credential_store import credential_store
        for sid, session in credential_store._sessions.items():
            creds = session.get_credentials("np") or session.get_credentials("prd")
            if creds:
                return boto3.client(
                    "s3",
                    aws_access_key_id=creds.access_key_id,
                    aws_secret_access_key=creds.secret_access_key,
                    aws_session_token=creds.session_token,
                    region_name="us-west-2",
                )
    except Exception:
        pass
    # Fallback to default credential chain
    import boto3
    return boto3.client("s3", region_name="us-west-2")


def upload_kb_to_s3(knowledge_dir: str) -> dict:
    """Upload local KB files to S3 after a build. Called at end of KB build."""
    if not _s3_bucket:
        return {"status": "skipped", "reason": "KB_S3_BUCKET not configured"}

    knowledge_path = Path(knowledge_dir)
    s3 = _get_s3_client()
    uploaded = 0
    errors = []

    # Upload individual files
    for filename in KB_FILES:
        local_path = knowledge_path / filename
        if local_path.exists():
            s3_key = f"{_s3_prefix}{filename}"
            try:
                s3.upload_file(str(local_path), _s3_bucket, s3_key)
                uploaded += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)[:100]}")

    # Upload directories
    for dirname in KB_DIRS:
        dir_path = knowledge_path / dirname
        if dir_path.is_dir():
            for file_path in dir_path.glob("*.json"):
                s3_key = f"{_s3_prefix}{dirname}/{file_path.name}"
                try:
                    s3.upload_file(str(file_path), _s3_bucket, s3_key)
                    uploaded += 1
                except Exception as e:
                    errors.append(f"{dirname}/{file_path.name}: {str(e)[:100]}")

    # Write a manifest with build timestamp
    manifest = {
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "file_count": uploaded,
        "files": KB_FILES + [f"{d}/*.json" for d in KB_DIRS],
    }
    try:
        s3.put_object(
            Bucket=_s3_bucket,
            Key=f"{_s3_prefix}_manifest.json",
            Body=json.dumps(manifest, indent=2),
            ContentType="application/json",
        )
    except Exception:
        pass

    logger.info("Uploaded %d KB files to s3://%s/%s (%d errors)",
                uploaded, _s3_bucket, _s3_prefix, len(errors))
    return {"status": "uploaded", "files": uploaded, "errors": errors}


def download_kb_from_s3(knowledge_dir: str) -> dict:
    """Download KB files from S3 to local. Called on startup if local is empty/stale."""
    if not _s3_bucket:
        return {"status": "skipped", "reason": "KB_S3_BUCKET not configured"}

    knowledge_path = Path(knowledge_dir)
    knowledge_path.mkdir(parents=True, exist_ok=True)

    s3 = _get_s3_client()

    # Check manifest — is S3 newer than local?
    try:
        resp = s3.get_object(Bucket=_s3_bucket, Key=f"{_s3_prefix}_manifest.json")
        raw = resp["Body"].read()
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            logger.warning("S3 _manifest.json is not a dict (type=%s), treating as new", type(manifest).__name__)
            manifest = {"uploaded_at": datetime.now(timezone.utc).isoformat()}
        s3_timestamp = manifest.get("uploaded_at", "")
    except s3.exceptions.NoSuchKey:
        logger.info("No KB manifest in S3 — nothing to download")
        return {"status": "no_manifest"}
    except Exception as e:
        logger.warning("Failed to read S3 manifest: %s — downloading anyway", str(e)[:100])
        s3_timestamp = datetime.now(timezone.utc).isoformat()

    # Check local freshness — but only trust manifests where files were actually downloaded
    local_manifest = knowledge_path / "_manifest.json"
    if local_manifest.exists():
        try:
            with open(local_manifest) as f:
                local_data = json.load(f)
            local_timestamp = local_data.get("downloaded_at", "")
            local_file_count = local_data.get("file_count", 0)
            if local_file_count > 0 and local_timestamp >= s3_timestamp:
                logger.info("Local KB is current (local: %s, S3: %s, files: %d)", local_timestamp, s3_timestamp, local_file_count)
                return {"status": "current", "local": local_timestamp, "s3": s3_timestamp}
            if local_file_count == 0:
                logger.info("Local KB manifest has 0 files — re-downloading from S3")
        except Exception:
            pass

    # Download files
    downloaded = 0
    errors = []

    for filename in KB_FILES:
        s3_key = f"{_s3_prefix}{filename}"
        local_path = knowledge_path / filename
        try:
            s3.download_file(_s3_bucket, s3_key, str(local_path))
            downloaded += 1
        except Exception as e:
            if "404" not in str(e) and "NoSuchKey" not in str(e):
                errors.append(f"{filename}: {str(e)[:100]}")

    # Download directories
    for dirname in KB_DIRS:
        dir_path = knowledge_path / dirname
        dir_path.mkdir(exist_ok=True)
        try:
            resp = s3.list_objects_v2(Bucket=_s3_bucket, Prefix=f"{_s3_prefix}{dirname}/", MaxKeys=500)
            for obj in resp.get("Contents", []):
                filename = obj["Key"].split("/")[-1]
                if filename:
                    local_path = dir_path / filename
                    try:
                        s3.download_file(_s3_bucket, obj["Key"], str(local_path))
                        downloaded += 1
                    except Exception as e:
                        errors.append(f"{dirname}/{filename}: {str(e)[:100]}")
        except Exception as e:
            errors.append(f"{dirname}/: {str(e)[:100]}")

    # Write local manifest — only mark as successfully downloaded if we got files
    local_manifest_data = {
        "downloaded_at": datetime.now(timezone.utc).isoformat() if downloaded > 0 else "",
        "s3_timestamp": s3_timestamp,
        "file_count": downloaded,
        "errors": errors[:10] if errors else [],
    }
    with open(local_manifest, "w") as f:
        json.dump(local_manifest_data, f, indent=2)

    if downloaded == 0:
        logger.warning("S3 download got 0 files from s3://%s/%s — errors: %s",
                        _s3_bucket, _s3_prefix, errors[:5])
    else:
        logger.info("Downloaded %d KB files from s3://%s/%s (%d errors)",
                    downloaded, _s3_bucket, _s3_prefix, len(errors))
    return {"status": "downloaded", "files": downloaded, "errors": errors}
