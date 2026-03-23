from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BLOCKVAULT_", extra="ignore")

    app_name: str = "BlockVault API"
    app_env: str = "development"
    debug: bool = False
    frontend_origin: str = "http://127.0.0.1:5173"
    frontend_origin_alt: str = "http://localhost:5173"
    frontend_origins: str | None = None
    frontend_origin_regex: str | None = None
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_database: str = "blockvault_fresh"
    storage_backend: str = "local"
    storage_root: Path = Path("data/object-store")
    storage_s3_endpoint_url: str | None = None
    storage_s3_region: str = "us-east-1"
    storage_s3_bucket: str = "blockvault-local"
    storage_s3_access_key_id: str | None = None
    storage_s3_secret_access_key: str | None = None
    storage_s3_force_path_style: bool = True
    storage_s3_auto_create_bucket: bool = True
    session_cookie_name: str = "bv_session"
    session_ttl_hours: int = 24
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    session_cookie_domain: str | None = None
    nonce_ttl_minutes: int = 10
    siwe_domain: str = "127.0.0.1:5173"
    siwe_uri: str = "http://127.0.0.1:5173"
    siwe_chain_id: int = 1
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    enable_test_auth: bool = False
    redaction_timeout_seconds: int = 300
    redaction_engine_mode: str = "rust_cli"
    redaction_engine_bin: str | None = None
    redaction_engine_expected_version: str = "0.1.0"
    proof_boundary: str = "canonical_segment_mask_v1"
    ocr_enabled: bool = True
    ocr_render_scale: float = 2.0
    ocr_min_confidence: float = 0.5
    zkpt_mode: str = "authoritative"
    zkpt_profiles_root: Path = Path("circuits/zkpt")
    zkpt_profile: str = "v4_sparse"
    zkpt_onchain_safe_profile: str = "v3a"
    zkpt_artifacts_dir: Path = Path("circuits/zkpt/v4_sparse")
    zkpt_artifact_version: str = "v4_sparse"
    zkpt_artifact_manifest: str = "artifact-manifest.json"
    zkpt_artifacts_auto_download: bool = False
    zkpt_artifacts_s3_endpoint_url: str | None = None
    zkpt_artifacts_s3_region: str = "us-east-1"
    zkpt_artifacts_s3_bucket: str | None = None
    zkpt_artifacts_s3_access_key_id: str | None = None
    zkpt_artifacts_s3_secret_access_key: str | None = None
    zkpt_artifacts_s3_force_path_style: bool | None = None
    zkpt_artifacts_s3_prefix: str = "zkpt-artifacts"
    zkpt_snarkjs_bin: str | None = None
    zkpt_node_bin: str | None = None
    zkpt_rapidsnark_bin: str | None = None
    zkpt_proof_timeout_seconds: int = 360
    zkpt_target_proof_seconds: int = 120
    zkpt_single_proof_target_seconds: int = 90
    zkpt_single_proof_timeout_seconds: int = 180
    zkpt_multi_shard_timeout_seconds: int = 900
    zkpt_max_parallel_shards: int = 2
    zkpt_preflight_max_supported_shards: int = 8
    zkpt_onchain_enabled: bool = False
    zkpt_onchain_chain_id: int = 11155111
    zkpt_onchain_rpc_url: str | None = None
    zkpt_onchain_receipt_registry_address: str | None = None
    zkpt_onchain_relayer_private_key: str | None = None
    zkpt_onchain_confirmations: int = 1
    zkpt_onchain_single_proof_only: bool = True
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_ping_timeout_seconds: float = 2.0
    redaction_runtime_status_ttl_seconds: float = 5.0
    allow_inline_redaction_fallback: bool = True
    max_upload_bytes: int = 25 * 1024 * 1024
    rate_limit_auth_requests: int = 20
    rate_limit_auth_window_seconds: int = 60
    rate_limit_write_requests: int = 10
    rate_limit_write_window_seconds: int = 60

    @property
    def cors_origins(self) -> list[str]:
        if self.frontend_origins:
            return list(dict.fromkeys(origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()))
        return list(dict.fromkeys(origin for origin in (self.frontend_origin, self.frontend_origin_alt) if origin))

    @property
    def resolved_zkpt_artifacts_s3_endpoint_url(self) -> str | None:
        return self.zkpt_artifacts_s3_endpoint_url or self.storage_s3_endpoint_url

    @property
    def resolved_zkpt_artifacts_s3_region(self) -> str:
        return self.zkpt_artifacts_s3_region or self.storage_s3_region

    @property
    def resolved_zkpt_artifacts_s3_bucket(self) -> str | None:
        return self.zkpt_artifacts_s3_bucket or self.storage_s3_bucket

    @property
    def resolved_zkpt_artifacts_s3_access_key_id(self) -> str | None:
        return self.zkpt_artifacts_s3_access_key_id or self.storage_s3_access_key_id

    @property
    def resolved_zkpt_artifacts_s3_secret_access_key(self) -> str | None:
        return self.zkpt_artifacts_s3_secret_access_key or self.storage_s3_secret_access_key

    @property
    def resolved_zkpt_artifacts_s3_force_path_style(self) -> bool:
        if self.zkpt_artifacts_s3_force_path_style is not None:
            return self.zkpt_artifacts_s3_force_path_style
        return self.storage_s3_force_path_style


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()



def reset_settings_cache() -> None:
    get_settings.cache_clear()
    for module_name, function_name in (
        ("blockvault_api.redaction_jobs", "reset_redaction_runtime_cache"),
        ("blockvault_api.storage", "reset_object_store_cache"),
        ("blockvault_api.zkpt_artifacts", "reset_zkpt_artifact_cache"),
        ("blockvault_api.zkpt_onchain", "reset_zkpt_onchain_cache"),
        ("blockvault_api.zkpt_policy", "reset_zkpt_policy_cache"),
        ("blockvault_api.zkpt_runtime", "reset_zkpt_runtime_cache"),
    ):
        try:
            module = __import__(module_name, fromlist=[function_name])
            getattr(module, function_name)()
        except Exception:
            continue
