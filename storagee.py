"""
MinIO / S3-compatible object storage helper for the Settlement PDF Splitter.

Config is read from environment variables (set these in the deployment):
    MINIO_URL          e.g. https://static.kashier.io
    MINIO_ACCESS_KEY
    MINIO_SECRET_KEY
    MINIO_BUCKET_NAME  e.g. settlement-pdf-splitter

If the env vars are missing, storage is disabled gracefully (uploads are skipped,
the app still works and serves the ZIP from local disk).
"""

import os
import logging
from datetime import timedelta
from urllib.parse import urlparse

logger = logging.getLogger("kashier_splitter")

try:
    from minio import Minio
    from minio.error import S3Error
    _MINIO_AVAILABLE = True
except Exception:  # library not installed
    _MINIO_AVAILABLE = False


# ---- Read config from environment ----
MINIO_URL = os.environ.get("MINIO_URL", "").strip()
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "").strip()
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "").strip()
MINIO_BUCKET_NAME = os.environ.get("MINIO_BUCKET_NAME", "settlement-pdf-splitter").strip()


def _parse_endpoint(url):
    """MinIO wants 'host[:port]' without scheme, plus a secure flag."""
    if not url:
        return None, True
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.netloc or parsed.path  # netloc empty if no scheme given
    secure = parsed.scheme != "http"
    return host, secure


_client = None


def get_client():
    """Return a cached MinIO client, or None if not configured/available."""
    global _client
    if _client is not None:
        return _client
    if not _MINIO_AVAILABLE:
        logger.warning("minio library not installed; object storage disabled")
        return None
    if not (MINIO_URL and MINIO_ACCESS_KEY and MINIO_SECRET_KEY):
        logger.warning("MinIO env vars not set; object storage disabled")
        return None

    endpoint, secure = _parse_endpoint(MINIO_URL)
    try:
        _client = Minio(
            endpoint,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=secure,
        )
        # Ensure the bucket exists (create if missing)
        if not _client.bucket_exists(MINIO_BUCKET_NAME):
            _client.make_bucket(MINIO_BUCKET_NAME)
            logger.info("Created MinIO bucket: %s", MINIO_BUCKET_NAME)
        logger.info("MinIO client ready: endpoint=%s bucket=%s secure=%s",
                    endpoint, MINIO_BUCKET_NAME, secure)
        return _client
    except Exception as e:
        logger.error("Could not init MinIO client: %s", e)
        return None


def is_enabled():
    return get_client() is not None


def upload_file(local_path, object_name, content_type="application/zip"):
    """
    Upload a local file to the bucket under object_name.
    Returns the object_name on success, or None on failure.
    """
    client = get_client()
    if client is None:
        return None
    try:
        client.fput_object(
            MINIO_BUCKET_NAME,
            object_name,
            local_path,
            content_type=content_type,
        )
        logger.info("Uploaded to MinIO: %s/%s", MINIO_BUCKET_NAME, object_name)
        return object_name
    except Exception as e:
        logger.error("MinIO upload failed for %s: %s", object_name, e)
        return None


def presigned_url(object_name, expires_days=7):
    """
    Return a temporary download URL for the object (default 7 days),
    or None if storage is disabled / the call fails.
    """
    client = get_client()
    if client is None:
        return None
    try:
        return client.presigned_get_object(
            MINIO_BUCKET_NAME,
            object_name,
            expires=timedelta(days=expires_days),
        )
    except Exception as e:
        logger.error("Could not create presigned URL for %s: %s", object_name, e)
        return None


def list_files(prefix=""):
    """List object names in the bucket (optionally under a prefix)."""
    client = get_client()
    if client is None:
        return []
    try:
        objs = client.list_objects(MINIO_BUCKET_NAME, prefix=prefix, recursive=True)
        return [o.object_name for o in objs]
    except Exception as e:
        logger.error("MinIO list failed: %s", e)
        return []
