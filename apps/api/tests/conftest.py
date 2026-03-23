from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from blockvault_api.config import reset_settings_cache
from blockvault_api.database import reset_database_cache
from blockvault_api.main import create_app
from blockvault_api.rate_limit import reset_rate_limiter
from blockvault_api.redaction_jobs import reset_redaction_runtime_cache
from blockvault_api.storage import reset_object_store_cache


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_MONGO_URI", "mongomock://localhost")
    monkeypatch.setenv("BLOCKVAULT_MONGO_DATABASE", "blockvault_test")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "test-secret-key-1234567890")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "127.0.0.1:5173")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "http://127.0.0.1:5173")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "true")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ARTIFACTS_DIR", str(tmp_path / "missing-zkpt-artifacts"))
    reset_settings_cache()
    reset_database_cache()
    reset_rate_limiter()
    reset_redaction_runtime_cache()
    reset_object_store_cache()
    yield
    reset_settings_cache()
    reset_database_cache()
    reset_rate_limiter()
    reset_redaction_runtime_cache()
    reset_object_store_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
