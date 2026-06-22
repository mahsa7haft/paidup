import os
import datetime
import boto3
from botocore.exceptions import ClientError

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    account_id  = os.environ.get("R2_ACCOUNT_ID")
    access_key  = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key  = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        return None
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    return _client


def _key(member_id: int, variant: str | None = None) -> str:
    month = datetime.date.today().strftime("%Y-%m")
    suffix = f"_{variant}" if variant else ""
    return f"cards/{member_id}_{month}{suffix}.png"


def get_card_url(member_id: int, variant: str | None = None) -> str | None:
    """Return the public CDN URL if a card for this month already exists, else None."""
    client = _get_client()
    bucket = os.environ.get("R2_BUCKET_NAME")
    public_url = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if not (client and bucket and public_url):
        return None
    key = _key(member_id, variant)
    try:
        client.head_object(Bucket=bucket, Key=key)
        return f"{public_url}/{key}"
    except ClientError:
        return None


def upload_card(member_id: int, png_bytes: bytes, variant: str | None = None) -> str | None:
    """Upload card PNG and return its public CDN URL, or None if R2 is not configured."""
    client = _get_client()
    bucket = os.environ.get("R2_BUCKET_NAME")
    public_url = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if not (client and bucket and public_url):
        return None
    try:
        key = _key(member_id, variant)
        client.put_object(Bucket=bucket, Key=key, Body=png_bytes, ContentType="image/png")
        return f"{public_url}/{key}"
    except Exception:
        return None
