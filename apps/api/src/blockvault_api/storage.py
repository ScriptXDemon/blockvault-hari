from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from .config import Settings, get_settings


class ObjectStoreError(RuntimeError):
    pass


class ObjectStore(Protocol):
    def put_bytes(self, namespace: str, key: str, payload: bytes) -> str:
        ...

    def read_bytes(self, storage_key: str) -> bytes:
        ...

    def exists(self, storage_key: str) -> bool:
        ...


class LocalObjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_settings().storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, namespace: str, key: str, payload: bytes) -> str:
        target = self.root / namespace / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return f"{namespace}/{key}"

    def read_bytes(self, storage_key: str) -> bytes:
        return (self.root / storage_key).read_bytes()

    def exists(self, storage_key: str) -> bool:
        return (self.root / storage_key).exists()


class S3ObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bucket = self.settings.storage_s3_bucket
        self.endpoint_url = self.settings.storage_s3_endpoint_url
        self.region = self.settings.storage_s3_region
        self.force_path_style = self.settings.storage_s3_force_path_style
        session = boto3.session.Session()
        self.client = session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.settings.storage_s3_access_key_id,
            aws_secret_access_key=self.settings.storage_s3_secret_access_key,
            config=BotoConfig(s3={"addressing_style": "path" if self.force_path_style else "auto"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise ObjectStoreError(f"S3 bucket check failed for '{self.bucket}': {exc}") from exc

        if not self.settings.storage_s3_auto_create_bucket:
            raise ObjectStoreError(f"S3 bucket '{self.bucket}' does not exist")

        create_kwargs: dict[str, object] = {"Bucket": self.bucket}
        if self.region and self.region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
        try:
            self.client.create_bucket(**create_kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError(f"Failed to create S3 bucket '{self.bucket}': {exc}") from exc

    @staticmethod
    def _object_key(namespace: str, key: str) -> str:
        return f"{namespace.strip('/')}/{key.lstrip('/')}"

    def put_bytes(self, namespace: str, key: str, payload: bytes) -> str:
        storage_key = self._object_key(namespace, key)
        try:
            self.client.put_object(Bucket=self.bucket, Key=storage_key, Body=payload, ContentType="application/octet-stream")
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError(f"Failed to write object '{storage_key}' to S3: {exc}") from exc
        return storage_key

    def read_bytes(self, storage_key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(storage_key) from exc
            raise ObjectStoreError(f"Failed to read object '{storage_key}' from S3: {exc}") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError(f"Failed to read object '{storage_key}' from S3: {exc}") from exc
        return response["Body"].read()

    def exists(self, storage_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=storage_key)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise ObjectStoreError(f"Failed to check object '{storage_key}' in S3: {exc}") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError(f"Failed to check object '{storage_key}' in S3: {exc}") from exc
        return True


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    settings = get_settings()
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        return LocalObjectStore(settings.storage_root)
    if backend == "s3":
        return S3ObjectStore(settings)
    raise ObjectStoreError(f"Unsupported storage backend '{settings.storage_backend}'")


def get_object_store_status() -> dict[str, object]:
    settings = get_settings()
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        root = settings.storage_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return {
            "backend": "local",
            "ready": True,
            "root": str(root),
            "bucket": None,
            "endpointUrl": None,
            "region": None,
            "forcePathStyle": None,
            "error": None,
        }

    if backend == "s3":
        try:
            store = get_object_store()
        except Exception as exc:  # pragma: no cover - exercised by readiness paths
            return {
                "backend": "s3",
                "ready": False,
                "root": None,
                "bucket": settings.storage_s3_bucket,
                "endpointUrl": settings.storage_s3_endpoint_url,
                "region": settings.storage_s3_region,
                "forcePathStyle": settings.storage_s3_force_path_style,
                "error": str(exc),
            }
        assert isinstance(store, S3ObjectStore)
        return {
            "backend": "s3",
            "ready": True,
            "root": None,
            "bucket": store.bucket,
            "endpointUrl": store.endpoint_url,
            "region": store.region,
            "forcePathStyle": store.force_path_style,
            "error": None,
        }

    return {
        "backend": backend,
        "ready": False,
        "root": None,
        "bucket": None,
        "endpointUrl": None,
        "region": None,
        "forcePathStyle": None,
        "error": f"Unsupported storage backend '{settings.storage_backend}'",
    }


def reset_object_store_cache() -> None:
    get_object_store.cache_clear()
