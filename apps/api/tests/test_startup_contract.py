from __future__ import annotations

import pytest

from blockvault_api.config import reset_settings_cache
from blockvault_api.main import create_app


def test_create_app_allows_development_startup_when_zkpt_is_not_ready(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "development")
    monkeypatch.setattr(
        "blockvault_api.main.check_zkpt_readiness",
        lambda: {"ready": False, "errors": ["missing artifacts"]},
    )
    monkeypatch.setattr(
        "blockvault_api.main.get_redaction_runtime_status",
        lambda: {"ready": False},
    )
    reset_settings_cache()

    try:
        app = create_app()
    finally:
        reset_settings_cache()

    assert app.title == "BlockVault API"


def test_create_app_blocks_production_startup_when_zkpt_is_not_ready(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(
        "blockvault_api.main.get_object_store_status",
        lambda: {"ready": True, "backend": "s3", "error": None},
    )
    monkeypatch.setattr(
        "blockvault_api.main.check_zkpt_readiness",
        lambda: {"ready": False, "errors": ["selected profile is not authoritative"]},
    )
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="authoritative ZKPT runtime is not ready"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_when_redaction_runtime_is_not_ready(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(
        "blockvault_api.main.get_object_store_status",
        lambda: {"ready": True, "backend": "s3", "error": None},
    )
    monkeypatch.setattr(
        "blockvault_api.main.check_zkpt_readiness",
        lambda: {"ready": True, "errors": []},
    )
    monkeypatch.setattr(
        "blockvault_api.main.get_redaction_runtime_status",
        lambda: {"ready": False},
    )
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="redaction runtime is not ready"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_when_redaction_engine_mode_is_not_rust_cli(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(
        "blockvault_api.main.get_object_store_status",
        lambda: {"ready": True, "backend": "s3", "error": None},
    )
    monkeypatch.setattr(
        "blockvault_api.main.check_zkpt_readiness",
        lambda: {"ready": True, "errors": []},
    )
    monkeypatch.setattr(
        "blockvault_api.main.get_redaction_runtime_status",
        lambda: {"ready": True, "redaction_engine_mode": "python_fallback"},
    )
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="redaction engine must be rust_cli"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_when_storage_backend_is_not_s3(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(
        "blockvault_api.main.check_zkpt_readiness",
        lambda: {"ready": True, "errors": []},
    )
    monkeypatch.setattr(
        "blockvault_api.main.get_redaction_runtime_status",
        lambda: {"ready": True, "redaction_engine_mode": "rust_cli"},
    )
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="object storage backend must be s3"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_with_test_auth(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "true")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="test auth must be disabled"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_with_default_secret(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.delenv("BLOCKVAULT_SECRET_KEY", raising=False)
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="default secret key must be replaced"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_with_localhost_frontend_origin(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "http://127.0.0.1:5173")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "https://app.blockvault.example")
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="localhost CORS origins are not allowed"):
            create_app()
    finally:
        reset_settings_cache()


def test_create_app_blocks_production_startup_with_localhost_siwe_settings(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_APP_ENV", "production")
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    monkeypatch.setenv("BLOCKVAULT_SECRET_KEY", "production-secret-key-123456")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN", "https://app.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_FRONTEND_ORIGIN_ALT", "https://www.blockvault.example")
    monkeypatch.setenv("BLOCKVAULT_SIWE_DOMAIN", "127.0.0.1:5173")
    monkeypatch.setenv("BLOCKVAULT_SIWE_URI", "http://127.0.0.1:5173")
    reset_settings_cache()

    try:
        with pytest.raises(RuntimeError, match="SIWE domain and URI must not use localhost"):
            create_app()
    finally:
        reset_settings_cache()
