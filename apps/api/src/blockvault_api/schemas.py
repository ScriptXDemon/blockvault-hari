from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NonceRequest(BaseModel):
    walletAddress: str = Field(min_length=42, max_length=42)


class VerifyRequest(BaseModel):
    message: str
    signature: str


class TestLoginRequest(BaseModel):
    walletAddress: str = Field(min_length=42, max_length=42)
    displayName: str | None = Field(default=None, max_length=120)


class InitUploadRequest(BaseModel):
    originalName: str
    contentType: str
    size: int


class ShareRequest(BaseModel):
    recipientWallet: str = Field(min_length=42, max_length=42)


class CreateCaseRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=5000)


class NotarizeRequest(BaseModel):
    passphrase: str = Field(min_length=8, max_length=256)


class CreateRedactionJobRequest(BaseModel):
    documentId: str
    passphrase: str = Field(min_length=8, max_length=256)
    searchTerms: list[str] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    code: str
    message: str


class ZkptPayload(BaseModel):
    mode: str
    status: Literal["verified", "failed", "unsupported"]
    bundle_id: str | None
    artifact_version: str | None
    proof_boundary: Literal["canonical_segment_mask_v1"]
    verified_shards: int
    total_shards: int
    estimated_shards: int = 0
    predicted_proof_ms: float | None = None
    classification: Literal["single_proof_ready", "verified_bundle_only", "unsupported_until_v4"] = "verified_bundle_only"
    onchain_eligible: bool = False
    onchain_status: Literal["not_submitted", "submitted", "confirmed", "unsupported", "failed"] = "unsupported"
    document_binding_commitment: str | None = None
    fallback_mode: bool
    error: ErrorPayload | None
