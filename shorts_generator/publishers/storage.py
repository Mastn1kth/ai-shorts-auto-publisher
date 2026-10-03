"""Upload local clips to an S3-compatible bucket for Instagram ingestion."""

import os
import uuid
from urllib.parse import quote, urlparse

from .base import PublisherError


def public_video_url(video_path: str) -> str:
    """Return a hosted clip URL, uploading local files when necessary."""
    if video_path.startswith("https://"):
        return video_path
    if video_path.startswith("http://"):
        raise PublisherError("Instagram video URL must use HTTPS")
    if not os.path.isfile(video_path):
        raise PublisherError(f"Video file not found: {video_path}")

    bucket = os.getenv("MEDIA_S3_BUCKET", "").strip()
    public_base = os.getenv("MEDIA_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not bucket or not public_base:
        raise PublisherError(
            "Local Instagram clips need MEDIA_S3_BUCKET and MEDIA_PUBLIC_BASE_URL. "
            "The file must be uploaded before Instagram can read it."
        )
    parsed = urlparse(public_base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PublisherError("MEDIA_PUBLIC_BASE_URL must be a public HTTPS URL")
    try:
        import boto3
    except ImportError as exc:
        raise PublisherError("S3 upload requires boto3: pip install -r requirements-publish.txt") from exc

    key = f"shorts/{uuid.uuid4().hex}.mp4"
    options = {}
    endpoint = os.getenv("MEDIA_S3_ENDPOINT", "").strip()
    if endpoint:
        options["endpoint_url"] = endpoint
    try:
        client = boto3.client("s3", **options)
        client.upload_file(
            video_path,
            bucket,
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
    except Exception as exc:
        raise PublisherError(f"Could not upload clip to S3-compatible storage: {exc}") from exc
    return f"{public_base}/{quote(key)}"
