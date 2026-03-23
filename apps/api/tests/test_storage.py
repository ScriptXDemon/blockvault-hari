from __future__ import annotations

from botocore.exceptions import ClientError

from blockvault_api.config import reset_settings_cache
from blockvault_api.storage import get_object_store, get_object_store_status, reset_object_store_cache


class _FakeBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeS3Client:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_bucket(self, *, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")

    def create_bucket(self, *, Bucket: str, **_: object) -> None:
        self.buckets.add(Bucket)

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: object) -> None:
        if Bucket not in self.buckets:
            raise ClientError({"Error": {"Code": "NoSuchBucket", "Message": "Missing bucket"}}, "PutObject")
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        try:
            payload = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Missing object"}}, "GetObject") from exc
        return {"Body": _FakeBody(payload)}

    def head_object(self, *, Bucket: str, Key: str) -> None:
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Missing object"}}, "HeadObject")


def test_s3_object_store_round_trip(monkeypatch):
    fake_client = _FakeS3Client()

    class _FakeSession:
        def client(self, *_args: object, **_kwargs: object) -> _FakeS3Client:
            return fake_client

    monkeypatch.setenv("BLOCKVAULT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_S3_BUCKET", "blockvault-local")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_S3_ACCESS_KEY_ID", "blockvault")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_S3_SECRET_ACCESS_KEY", "blockvault123")
    monkeypatch.setattr("blockvault_api.storage.boto3.session.Session", lambda: _FakeSession())
    reset_settings_cache()
    reset_object_store_cache()

    try:
        store = get_object_store()
        storage_key = store.put_bytes("vault", "example.bin", b"blockvault")
        assert storage_key == "vault/example.bin"
        assert store.exists(storage_key) is True
        assert store.read_bytes(storage_key) == b"blockvault"

        status = get_object_store_status()
        assert status["backend"] == "s3"
        assert status["ready"] is True
        assert status["bucket"] == "blockvault-local"
        assert status["endpointUrl"] == "http://minio:9000"
    finally:
        reset_settings_cache()
        reset_object_store_cache()
