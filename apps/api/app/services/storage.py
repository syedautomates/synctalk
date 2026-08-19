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


# claude.md M7: "S3 lifecycle rule deletes raw uploads' temp copies after 7 days". This
# app doesn't stage uploads into a separate temp key before promoting them (presigned
# uploads land directly at their permanent key, per M1), and passed raw assets
# (reference photos/video/voice) are referenced indefinitely by later generation steps
# -- a blanket age-based expiry on all raw uploads would delete assets still in active
# use. The genuinely disposable case is a raw upload that FAILED validation: it will
# never be read again (see create_asset in routes/profiles.py). Those get tagged
# FAILED_VALIDATION_TAG at validation time, and this rule expires anything carrying
# that tag after 7 days -- a real, tag-filtered S3/MinIO Lifecycle rule, not an
# app-level cron. See DECISIONS.md's M7 entry for the full reasoning.
FAILED_VALIDATION_TAG = {"Key": "lifecycle", "Value": "expire-failed-validation"}
FAILED_VALIDATION_EXPIRY_DAYS = 7
_LIFECYCLE_RULE_ID = "expire-failed-validation-uploads"


def ensure_lifecycle_policy() -> None:
    _internal_client.put_bucket_lifecycle_configuration(
        Bucket=settings.s3_bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": _LIFECYCLE_RULE_ID,
                    "Status": "Enabled",
                    "Filter": {"Tag": FAILED_VALIDATION_TAG},
                    "Expiration": {"Days": FAILED_VALIDATION_EXPIRY_DAYS},
                }
            ]
        },
    )


def tag_for_expiry(s3_key: str) -> None:
    _internal_client.put_object_tagging(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Tagging={"TagSet": [FAILED_VALIDATION_TAG]},
    )


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
