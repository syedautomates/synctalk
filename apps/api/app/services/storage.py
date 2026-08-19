import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

PRESIGN_PUT_EXPIRES_SECONDS = 15 * 60
# Longer than the PUT window: a GET presign goes into a job payload that may sit in the
# queue for a while before a worker picks it up (pod might not be running yet).
PRESIGN_GET_EXPIRES_SECONDS = 60 * 60


def _client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


# Internal client: used server-side (bucket setup, downloading objects to validate).
_internal_client = _client(settings.s3_endpoint)

# Public client: only used to mint presigned URLs, so the signed host matches what
# the external client (browser, curl) will actually connect to.
_public_client = _client(settings.s3_public_endpoint_or_default)


def ensure_bucket_exists() -> None:
    try:
        _internal_client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        _internal_client.create_bucket(Bucket=settings.s3_bucket)


def build_object_key(profile_id: uuid.UUID, kind: str, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"profiles/{profile_id}/{kind}/{uuid.uuid4()}_{safe_name}"


def build_key(prefix: str, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"{prefix}/{uuid.uuid4()}_{safe_name}"


def presign_put(s3_key: str, content_type: str) -> str:
    return _public_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=PRESIGN_PUT_EXPIRES_SECONDS,
    )


def presign_get(s3_key: str) -> str:
    return _public_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key},
        ExpiresIn=PRESIGN_GET_EXPIRES_SECONDS,
    )


def object_exists(s3_key: str) -> bool:
    try:
        _internal_client.head_object(Bucket=settings.s3_bucket, Key=s3_key)
        return True
    except ClientError:
        return False


def get_object_bytes(s3_key: str) -> bytes:
    response = _internal_client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
    return response["Body"].read()


def put_object_bytes(s3_key: str, data: bytes, content_type: str) -> None:
    _internal_client.put_object(
        Bucket=settings.s3_bucket, Key=s3_key, Body=data, ContentType=content_type
    )
